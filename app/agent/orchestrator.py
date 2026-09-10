"""
Orchestrates the SQL agent loop:
1. SQL Generator agent writes + executes a SQL query, producing an answer.
2. Reviewer agent judges (via its own LLM reasoning) whether to trust it.
3. Python only ROUTES based on the reviewer's decision (accept/retry) -
   it never judges correctness itself. Capped at MAX_AGENT_RETRIES.

Note: we do NOT use CrewAI's output_pydantic here. On Groq, output_pydantic
makes CrewAI force a synthetic "json" tool call to get structured output,
and Groq's strict tool validation rejects that (since "json" isn't a
declared tool) - see: 400 tool_use_failed, "attempted to call tool 'json'
which was not in request.tools". Instead, we ask the agent for plain JSON
text and parse it ourselves with json_repair (tolerant of minor formatting
issues an LLM might produce).
"""

import logging
import time
from typing import Optional

from json_repair import loads as json_repair_loads
from pydantic import BaseModel
from crewai import Task, Crew, Process

from app.agent.crew import sql_generator_agent, reviewer_agent, DATABASE_SCHEMA
from app.settings import MAX_AGENT_RETRIES

# Groq's free tier caps tokens-per-minute (TPM). A single attempt (generator
# + reviewer calls) can use most of that budget, so retries need a short
# pause to let the TPM window refresh before firing again.
RETRY_DELAY_SECONDS = 25

logger = logging.getLogger(__name__)


class SQLAttempt(BaseModel):
    """Structured output expected from the SQL generator agent."""
    sql_query: str
    answer: str


class ReviewResult(BaseModel):
    """Structured output expected from the reviewer agent."""
    trustworthy: bool
    reason: str


def _parse_json_output(raw_text: str, model_cls):
    """
    Parses a Pydantic model out of raw LLM text output. Uses json_repair
    to tolerate minor formatting issues (markdown fences, trailing text)
    since we no longer rely on CrewAI's native structured-output mode.

    Returns None if parsing/validation fails.
    """
    try:
        parsed = json_repair_loads(raw_text)
        if isinstance(parsed, dict):
            return model_cls(**parsed)
    except Exception as e:
        logger.error(f"Failed to parse JSON output: {e}. Raw text: {raw_text!r}")
    return None


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
        if attempt > 1:
            logger.info(f"Waiting {RETRY_DELAY_SECONDS}s before retry to respect Groq's TPM limit.")
            time.sleep(RETRY_DELAY_SECONDS)
        logger.info(f"Attempt {attempt} for question: {question}")

        generate_task = Task(
            description=(
                f"Database schema:\n{DATABASE_SCHEMA}\n\n"
                f"Question: {question}\n\n"
                + (f"Feedback from previous attempt (fix this): {feedback}\n\n" if feedback else "")
                + "Write a PostgreSQL SELECT query that answers the question, "
                  "execute it using the Execute SQL Query tool, and then give "
                  "a short plain-English answer based on the actual result.\n\n"
                  "Respond with ONLY a raw JSON object (no markdown fences, no "
                  "extra text before or after) in exactly this shape: "
                  '{"sql_query": "<the exact SQL used>", "answer": "<plain-English answer>"}'
            ),
            expected_output="A raw JSON object with 'sql_query' and 'answer'.",
            agent=sql_generator_agent,
        )

        review_task = Task(
            description=(
                f"Database schema (use this as the ground truth for what each "
                f"metric/wording means):\n{DATABASE_SCHEMA}\n\n"
                f"Original question: {question}\n\n"
                "Carefully read the actual SQL query text (not just the final "
                "answer). Check specifically: (1) Does the SQL correctly JOIN "
                "all tables needed to apply any status filter the question "
                "requires? (2) Does the WHERE clause include exactly the "
                "order_status values the question asks for - no more, no "
                "fewer? (3) Is the numeric answer consistent with what the "
                "SQL query would actually produce? (4) Does the query's "
                "interpretation of the question match the definitions given "
                "in the database schema above (e.g. how averages should be "
                "computed) - if the schema defines a specific meaning for a "
                "term used in the question, that definition takes priority "
                "over your own assumption. A query that omits a required "
                "JOIN or WHERE filter, or that contradicts a definition given "
                "in the schema, is NOT trustworthy even if the number looks "
                "plausible. If anything is wrong, mark it as not trustworthy "
                "and state precisely which JOIN, WHERE clause, or schema "
                "definition was missed.\n\n"
                "Respond with ONLY a raw JSON object (no markdown fences, no "
                "extra text before or after) in exactly this shape: "
                '{"trustworthy": true or false, "reason": "<your reason>"}'
            ),
            expected_output="A raw JSON object with 'trustworthy' and 'reason'.",
            agent=reviewer_agent,
            context=[generate_task],
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

        sql_result: Optional[SQLAttempt] = _parse_json_output(generate_task.output.raw, SQLAttempt)
        review_result: Optional[ReviewResult] = _parse_json_output(review_task.output.raw, ReviewResult)

        if sql_result is None:
            feedback = "Your previous response was not valid JSON in the required shape; return ONLY the raw JSON object, nothing else."
            continue

        if review_result is None:
            feedback = "Reviewer did not return a valid judgment; try a clearer, simpler query."
            continue

        if review_result.trustworthy:
            logger.info(f"Accepted on attempt {attempt}.")
            return {
                "status": "success",
                "answer": sql_result.answer,
                "sql_used": sql_result.sql_query,
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