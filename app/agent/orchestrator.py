"""
Orchestrates the SQL agent loop:
1. SQL Generator agent writes + executes a SQL query, producing an answer.
2. Reviewer agent judges (via its own LLM reasoning) whether to trust it.
3. Python only ROUTES based on the reviewer's decision (accept/retry) -
   it never judges correctness itself. Capped at MAX_AGENT_RETRIES.
"""

import logging
from pydantic import BaseModel
from crewai import Task, Crew, Process

from app.agent.crew import sql_generator_agent, reviewer_agent, DATABASE_SCHEMA
from app.settings import MAX_AGENT_RETRIES

logger = logging.getLogger(__name__)


class SQLAttempt(BaseModel):
    """Structured output expected from the SQL generator agent."""
    sql_query: str
    answer: str


class ReviewResult(BaseModel):
    """Structured output expected from the reviewer agent."""
    trustworthy: bool
    reason: str


def run_agent_loop(question: str) -> dict:
    """
    Runs the generate -> review -> (accept | retry) loop for a given
    natural language question, capped at MAX_AGENT_RETRIES attempts.

    Args:
        question (str): The user's plain-English question.

    Returns:
        dict: On success: {"status": "success", "answer": str,
              "sql_used": str, "attempts": int}
              On failure: {"status": "failed", "reason": str, "attempts": int}
    """
    feedback = ""

    for attempt in range(1, MAX_AGENT_RETRIES + 1):
        logger.info(f"Attempt {attempt} for question: {question}")

        generate_task = Task(
            description=(
                f"Database schema:\n{DATABASE_SCHEMA}\n\n"
                f"Question: {question}\n\n"
                + (f"Feedback from previous attempt (fix this): {feedback}\n\n" if feedback else "")
                + "Write a PostgreSQL SELECT query that answers the question, "
                  "execute it using the Execute SQL Query tool, and then give "
                  "a short plain-English answer based on the actual result."
            ),
            expected_output="A JSON object with 'sql_query' (the exact SQL used) and 'answer' (plain-English answer).",
            agent=sql_generator_agent,
            output_pydantic=SQLAttempt,
        )

        review_task = Task(
            description=(
                f"Original question: {question}\n\n"
                "Look at the SQL query and answer produced above. Decide whether "
                "this result plausibly and correctly answers the question, "
                "paying attention to edge cases such as status filters "
                "(e.g. canceled/unavailable orders should usually be excluded "
                "from revenue or sales totals). If it looks wrong or you are "
                "not confident, mark it as not trustworthy and explain exactly "
                "what should be fixed."
            ),
            expected_output="A JSON object with 'trustworthy' (true/false) and 'reason'.",
            agent=reviewer_agent,
            context=[generate_task],
            output_pydantic=ReviewResult,
        )

        crew = Crew(
            agents=[sql_generator_agent, reviewer_agent],
            tasks=[generate_task, review_task],
            process=Process.sequential,
            verbose=True,
        )

        try:
            crew.kickoff()
        except Exception as e:
            logger.error(f"Crew execution failed on attempt {attempt}: {e}")
            feedback = f"The previous attempt raised an error: {e}"
            continue

        sql_result: SQLAttempt = generate_task.output.pydantic
        review_result: ReviewResult = review_task.output.pydantic

        if review_result is None:
            feedback = "Reviewer did not return a valid judgment; try a clearer, simpler query."
            continue

        if review_result.trustworthy:
            logger.info(f"Accepted on attempt {attempt}.")
            return {
                "status": "success",
                "answer": sql_result.answer if sql_result else "",
                "sql_used": sql_result.sql_query if sql_result else "",
                "attempts": attempt,
            }

        # Reviewer said not trustworthy - feed its reason into the next attempt
        feedback = review_result.reason
        logger.info(f"Attempt {attempt} rejected by reviewer: {feedback}")

    logger.warning(f"Failed after {MAX_AGENT_RETRIES} attempts for question: {question}")
    return {
        "status": "failed",
        "reason": "Agent could not produce a confident result after 3 attempts",
        "attempts": MAX_AGENT_RETRIES,
    }