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
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

# Database URL must be set via environment variable
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=2,           # Keep pool small per process
    max_overflow=3,        # Limited overflow connections
    pool_timeout=10,       # Fail fast if no connection available
    pool_recycle=300,      # Recycle connections every 5 min
    connect_args={
        "connect_timeout": 10,  # 10 second connection timeout
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
        db.close()
