import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import sandwich_bot.db as db
from sandwich_bot.models import Base, MenuItem
from sandwich_bot.main import app


@pytest.fixture
def client():
    """Shared FastAPI TestClient using an in-memory SQLite DB.

    Uses StaticPool so all connections share the same in-memory database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the db module used by the app
    db.engine = engine
    db.SessionLocal = TestingSessionLocal

    # Create tables
    Base.metadata.create_all(bind=engine)

    # Seed minimal menu
    session = TestingSessionLocal()
    session.add(MenuItem(
        name="Turkey Club",
        category="sandwich",
        is_signature=True,
        base_price=8.0,
        available_qty=5,
        extra_metadata={},
    ))
    session.add(MenuItem(
        name="soda",
        category="drink",
        is_signature=False,
        base_price=2.5,
        available_qty=10,
        extra_metadata={},
    ))
    session.commit()
    session.close()

    # Override FastAPI DB dependency
    def override_get_db():
        db_sess = TestingSessionLocal()
        try:
            yield db_sess
        finally:
            db_sess.close()

    app.dependency_overrides[db.get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
