"""
Entry point for the FastAPI application.
Defines the API routes described in the project's API contract:
POST /ask, GET /status/{job_id}, plus a /health check.
"""

import json
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from celery.result import AsyncResult

from app.worker.tasks import celery_app, run_sql_agent_task, ping_task, redis_client, normalize_question

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SQL Analysis Agent")


class AskRequest(BaseModel):
    """Request body shape for POST /ask."""
    question: str


@app.get("/health")
def health_check() -> dict:
    """
    Simple endpoint to confirm the API service is running.

    Returns:
        dict: A status message.
    """
    logger.info("Health check endpoint was called.")
    return {"status": "ok", "message": "API is running"}


@app.get("/test-task")
def test_task() -> dict:
    """
    Triggers the Celery ping_task in the background and returns
    its task_id immediately (does not wait for the result).

    Returns:
        dict: The task_id that can be used to check status later.
    """
    result = ping_task.delay()
    logger.info(f"Dispatched ping_task with id: {result.id}")
    return {"task_id": result.id, "status": "dispatched"}


@app.post("/ask")
def ask_question(request: AskRequest) -> dict:
    """
    Accepts a natural-language question. If a cached answer exists for
    the (normalized) question, it is returned immediately via a
    synthetic job_id. Otherwise, dispatches a background Celery task
    to run the agent and returns its job_id for polling.

    Args:
        request (AskRequest): Contains the user's question.

    Returns:
        dict: {"job_id": str}
    """
    cache_key = f"answer:{normalize_question(request.question)}"
    cached_value = redis_client.get(cache_key)

    if cached_value:
        logger.info(f"Cache hit for question: {request.question}")
        cached_result = json.loads(cached_value)
        cached_result["cached"] = True
        # Store this cached result under a fresh job_id so /status works
        # the same way for cached and non-cached answers.
        job_id = f"cached-{normalize_question(request.question)[:40]}"
        redis_client.setex(f"job:{job_id}", 300, json.dumps(cached_result))
        return {"job_id": job_id}

    logger.info(f"Cache miss, dispatching agent for question: {request.question}")
    task = run_sql_agent_task.delay(request.question)
    return {"job_id": task.id}


@app.get("/status/{job_id}")
def get_status(job_id: str) -> dict:
    """
    Checks the status of a previously dispatched question.
    Handles both real Celery job_ids and synthetic "cached-..." job_ids
    used for immediate cache hits.

    Args:
        job_id (str): The job_id returned by POST /ask.

    Returns:
        dict: {"status": "pending"} while running, or the full result
              (status/answer/sql_used/attempts/cached or status/reason)
              once done.
    """
    # Handle cached responses stored directly under a "job:" key
    if job_id.startswith("cached-"):
        cached_value = redis_client.get(f"job:{job_id}")
        if cached_value:
            return json.loads(cached_value)
        return {"status": "failed", "reason": "Cached job expired or not found."}

    # Otherwise, check real Celery task status
    task_result = AsyncResult(job_id, app=celery_app)

    if not task_result.ready():
        return {"status": "pending"}

    result = task_result.result
    if isinstance(result, Exception):
        logger.error(f"Task {job_id} failed: {result}")
        return {"status": "failed", "reason": str(result)}

    return result