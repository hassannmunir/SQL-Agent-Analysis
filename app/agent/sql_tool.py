"""
Custom tool that lets the CrewAI agent execute SQL queries against
the Postgres database and see either the result or the error message.
Giving the agent the raw error (instead of hiding it) lets it reason
about what went wrong and try a better query.
"""

import logging
from crewai.tools import tool
from sqlalchemy import text

from app.db.connection import get_engine

logger = logging.getLogger(__name__)


@tool("Execute SQL Query")
def execute_sql_query(sql_query: str) -> str:
    """
    Executes a SQL SELECT query against the e-commerce Postgres database
    and returns the result rows as text, or an error message if the
    query fails.

    Args:
        sql_query (str): A valid PostgreSQL SELECT query.

    Returns:
        str: The query result rows, or an error message starting with
             "ERROR:" if the query failed.
    """
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_query))
            rows = result.fetchall()
            columns = list(result.keys())

        if not rows:
            return "Query executed successfully but returned no rows."

        # Format as simple readable text: header + rows
        header = " | ".join(columns)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows[:50])
        logger.info(f"Query executed successfully, {len(rows)} rows returned.")
        return f"{header}\n{body}"

    except Exception as e:
        logger.warning(f"Query failed: {e}")
        return f"ERROR: {str(e)}"