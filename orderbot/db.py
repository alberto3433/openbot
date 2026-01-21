"""
Database connection management.

This module provides database access for the application.

For multi-tenant mode:
    - Use get_tenant_db() dependency with tenant resolution from request
    - The tenant is determined by TenantMiddleware

For single-tenant mode:
    - Use get_db() dependency which uses the default database

Environment variables:
    - DATABASE_URL: PostgreSQL connection URL (required)
    - TENANT_SLUG: Current tenant identifier (set by run_tenant.py)
"""

import os
from typing import Generator

from fastapi import Request
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
# Use init_legacy_db() if you need to create tables programmatically.


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a SQLAlchemy Session.

    This is the single-tenant version that uses the default database.
    For multi-tenant support, use get_tenant_db() instead.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_db(request: Request) -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a tenant-specific database session.

    The tenant is resolved from the request by TenantMiddleware.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_tenant_db)):
            ...

    Raises:
        ValueError: If tenant is not set in request state (TenantMiddleware not configured)
    """
    from .tenant import get_tenant_manager

    # Get tenant slug from request state (set by TenantMiddleware)
    if not hasattr(request.state, "tenant_slug"):
        raise ValueError(
            "Tenant not set in request. Ensure TenantMiddleware is configured."
        )

    tenant_slug = request.state.tenant_slug
    manager = get_tenant_manager()

    db = manager.get_db_session(tenant_slug)
    try:
        yield db
    finally:
        db.close()


def init_legacy_db() -> None:
    """Initialize the legacy single-tenant database tables."""
    Base.metadata.create_all(bind=engine)
