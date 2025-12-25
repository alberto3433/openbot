"""
Database connection management.

This module provides both single-tenant (legacy) and multi-tenant database access.

For multi-tenant mode:
    - Use get_tenant_db() dependency with tenant resolution from request
    - The tenant is determined by TenantMiddleware

For single-tenant mode (backward compatibility):
    - Use get_db() dependency which uses the default database

Environment variables:
    - DATABASE_URL: Override the default database URL
    - TENANT_SLUG: Current tenant identifier (set by run_tenant.py)
"""

import os
from typing import Generator, Optional

from fastapi import Request, Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

# Database URL must be set via environment variable
# For testing, use in-memory SQLite if DATABASE_URL is not set
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    if os.environ.get("TESTING") == "1":
        DATABASE_URL = "sqlite:///:memory:"
    else:
        raise ValueError("DATABASE_URL environment variable is required")

# Ensure directory exists for SQLite databases
if DATABASE_URL.startswith("sqlite:///./"):
    db_path = DATABASE_URL.replace("sqlite:///./", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Create tables on module load
Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a SQLAlchemy Session.

    This is the legacy single-tenant version for backward compatibility.
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
    """
    from .tenant import get_tenant_manager

    # Get tenant slug from request state (set by TenantMiddleware)
    if not hasattr(request.state, "tenant_slug"):
        # Fall back to legacy database if tenant not set
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
        return

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
