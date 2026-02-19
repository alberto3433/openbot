"""
Database connection management.

This module provides database access for the application.
Use get_db() dependency for database sessions.

Environment variables:
    - DATABASE_URL: PostgreSQL connection URL (required)
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base
from orderbot.config import (
    DB_POOL_SIZE,
    DB_MAX_OVERFLOW,
    DB_POOL_TIMEOUT,
    DB_POOL_RECYCLE_SECONDS,
    DB_CONNECT_TIMEOUT,
)

# Database URL must be set via environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
    pool_recycle=DB_POOL_RECYCLE_SECONDS,
    connect_args={
        "connect_timeout": DB_CONNECT_TIMEOUT,
        # NOTE: statement_timeout not supported by Neon's connection pooler
    },
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# NOTE: Tables are created via alembic migrations, not on module import.
# This avoids blocking database connections during import.


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy Session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()
