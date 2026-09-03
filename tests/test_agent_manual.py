"""
Manual/quick test script to run the agent loop directly (outside the
Celery/FastAPI flow) to verify the CrewAI agent logic works correctly
before wiring it into the full pipeline.
"""

from app.agent.orchestrator import run_agent_loop

if __name__ == "__main__":
    question = "What is the total revenue from delivered orders?"
    result = run_agent_loop(question)
    print("\n\n=== FINAL RESULT ===")
    print(result)