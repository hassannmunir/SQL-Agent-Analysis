"""
Defines the CrewAI agents used in the SQL analysis pipeline:
1. sql_generator_agent - reads the question + schema and writes SQL
2. reviewer_agent       - looks at the SQL result and decides (via its
                           own reasoning) whether to trust it or retry
"""

from crewai import Agent, LLM

from app.settings import GROQ_API_KEY, LLM_MODEL
from app.agent.sql_tool import execute_sql_query

# --- Workaround for CrewAI bug #5886 ---
# CrewAI unconditionally injects a "cache_breakpoint" key into system
# messages (meant only for Anthropic's prompt-caching feature). Non-
# Anthropic providers like Groq reject this key with a 400 error.
# We patch mark_cache_breakpoint to a no-op so no such key is added.
import crewai.llms.cache as _crewai_cache


def _noop_mark_cache_breakpoint(message):
    return message


_crewai_cache.mark_cache_breakpoint = _noop_mark_cache_breakpoint

# Shared LLM configuration used by both agents
llm = LLM(
    model=LLM_MODEL,
    api_key=GROQ_API_KEY,
)

# Description of our database schema, given to the SQL generator agent
# so it knows what tables and columns are available to query.
DATABASE_SCHEMA = """
Tables:
customers(customer_id, customer_unique_id, customer_zip_code_prefix, customer_city, customer_state)
products(product_id, product_category_name)
orders(order_id, customer_id, order_status, order_purchase_timestamp, order_approved_at, order_delivered_carrier_date, order_delivered_customer_date, order_estimated_delivery_date)
order_items(order_id, order_item_id, product_id, price, freight_value)

Rules:
- order_status values: delivered, shipped, canceled, unavailable, invoiced, processing, created, approved.
- Exclude canceled/unavailable from REVENUE/SUM(price) unless asked. Do NOT exclude for simple COUNT questions.
- "average order value"/"average price" = AVG(price) directly on order_items rows (per line-item), NOT avg of per-order SUM(price).
"""

sql_generator_agent = Agent(
    role="SQL Query Generator",
    goal="Write correct PostgreSQL SELECT queries that answer the user's question about the e-commerce database.",
    backstory=(
        "You are an expert data analyst who writes precise SQL queries. "
        "You are careful about status filters (like excluding canceled or "
        "unavailable orders) when the question implies only valid/completed "
        "transactions should be counted."
    ),
    tools=[execute_sql_query],
    llm=llm,
    verbose=True,
)

reviewer_agent = Agent(
    role="Result Reviewer",
    goal=(
        "Critically evaluate whether a SQL query's result actually and "
        "correctly answers the original question, and decide whether to "
        "accept it or request a retry with a specific reason."
    ),
    backstory=(
        "You are a skeptical senior analyst who double-checks junior "
        "analysts' work. You look for missed edge cases such as unfiltered "
        "statuses, wrong joins, or implausible numbers before approving "
        "any result."
    ),
    llm=llm,
    verbose=True,
)