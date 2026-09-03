"""
Database connection utilities.
Provides a single SQLAlchemy engine used across the app
to connect to the Postgres database defined in settings.py.
"""

import logging
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.settings import DATABASE_URL

logger = logging.getLogger(__name__)


def get_engine() -> Engine:
    """
    Create and return a SQLAlchemy engine connected to Postgres.

    Returns:
        Engine: a SQLAlchemy engine instance using DATABASE_URL
                from settings.py.
    """
    try:
        engine = create_engine(DATABASE_URL)
        logger.info("Database engine created successfully.")
        return engine
    except Exception as e:
        logger.error(f"Failed to create database engine: {e}")
        raise