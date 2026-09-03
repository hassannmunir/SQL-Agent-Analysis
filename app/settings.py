"""
Central configuration file for the SQL Agent project.
All hardcoded values (URLs, limits, credentials) live here
instead of being repeated across the codebase.
"""

import os
from dotenv import load_dotenv

# Load variables from the .env file into the environment
load_dotenv()

# --- Database settings ---
POSTGRES_USER = os.getenv("POSTGRES_USER", "sqlagent")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "sqlagent_pass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "sqlagent_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")  # service name in docker-compose
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

DATABASE_URL = (
    f"postgresql+psycopg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# --- Redis settings ---
REDIS_HOST = os.getenv("REDIS_HOST", "redis")  # service name in docker-compose
REDIS_PORT = os.getenv("REDIS_PORT", "6379")
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/0"

# --- LLM settings ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
LLM_MODEL = "gemini/gemini-3.5-flash"

# --- Agent behavior settings ---
MAX_AGENT_RETRIES = 3  # per task requirement: max 3 attempts before giving up

# --- Cache settings ---
CACHE_EXPIRY_SECONDS = 60 * 60 * 24  # cached answers expire after 24 hours