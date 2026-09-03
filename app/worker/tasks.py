"""
Celery application and task definitions.
This module is loaded by the Celery worker process (see the
'command' for the worker service in docker-compose.yml).
"""

import json
import logging
import redis

from celery import Celery

from app.settings import REDIS_URL, CACHE_EXPIRY_SECONDS
from app.agent.orchestrator import run_agent_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

celery_app = Celery(
    "sql_agent_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

# Separate plain Redis client (not through Celery) used for our own
# question-answer cache, distinct from Celery's internal broker/backend usage.
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)


def normalize_question(question: str) -> str:
    """
    Normalizes a question so that minor differences in casing or
    whitespace still hit the same cache entry.

    Args:
        question (str): The raw user question.

    Returns:
        str: A normalized cache key string.
    """
    return " ".join(question.strip().lower().split())


@celery_app.task(name="app.worker.tasks.ping_task")
def ping_task() -> str:
    """
    Simple test task to confirm Celery, Redis, and the worker container
    are all wired together correctly.

    Returns:
        str: A confirmation message.
    """
    logger.info("ping_task received and executed successfully.")
    return "pong"


@celery_app.task(name="app.worker.tasks.run_sql_agent_task")
def run_sql_agent_task(question: str) -> dict:
    """
    Background task that runs the full SQL agent loop for a question,
    then caches the result in Redis (keyed by the normalized question)
    so repeated questions can be answered instantly next time.

    Args:
        question (str): The user's plain-English question.

    Returns:
        dict: The agent's result (see run_agent_loop's return shape),
              with an added "cached": False flag for this first run.
    """
    logger.info(f"Running agent for question: {question}")
    result = run_agent_loop(question)
    result["cached"] = False

    cache_key = f"answer:{normalize_question(question)}"
    try:
        redis_client.setex(cache_key, CACHE_EXPIRY_SECONDS, json.dumps(result))
        logger.info(f"Cached result under key: {cache_key}")
    except Exception as e:
        logger.error(f"Failed to cache result: {e}")

    return result