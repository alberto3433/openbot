import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import sandwich_bot.db as db
import sandwich_bot.main as main_mod
from sandwich_bot.models import Base, MenuItem
from sandwich_bot.main import app, SESSION_CACHE

# Test admin credentials
TEST_ADMIN_USERNAME = "testadmin"
TEST_ADMIN_PASSWORD = "testpassword123"


@pytest.fixture
def client():
    """Shared FastAPI TestClient using an in-memory SQLite DB.

    Uses StaticPool so all connections share the same in-memory database.
    Sets up test admin credentials for authentication.
    """
    # Store original values
    original_username = main_mod.ADMIN_USERNAME
    original_password = main_mod.ADMIN_PASSWORD

    # Set test credentials
    main_mod.ADMIN_USERNAME = TEST_ADMIN_USERNAME
    main_mod.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the db module used by the app
    db.engine = engine
    db.SessionLocal = TestingSessionLocal

    # Create tables (including ChatSession)
    Base.metadata.create_all(bind=engine)

    # Seed minimal menu
    session = TestingSessionLocal()
    session.add(MenuItem(
        name="Turkey Club",
        category="sandwich",
        is_signature=True,
        base_price=8.0,
        available_qty=5,
        extra_metadata="{}",
    ))
    session.add(MenuItem(
        name="Veggie Delight",
        category="sandwich",
        is_signature=True,
        base_price=7.99,
        available_qty=10,
        extra_metadata="{}",
    ))
    session.add(MenuItem(
        name="Italian Stallion",
        category="sandwich",
        is_signature=True,
        base_price=9.49,
        available_qty=10,
        extra_metadata="{}",
    ))
    session.add(MenuItem(
        name="Custom Sandwich",
        category="sandwich",
        is_signature=False,
        base_price=5.99,
        available_qty=100,
        extra_metadata='{"is_custom": true}',
    ))
    session.add(MenuItem(
        name="soda",
        category="drink",
        is_signature=False,
        base_price=2.5,
        available_qty=10,
        extra_metadata="{}",
    ))
    session.add(MenuItem(
        name="Chips",
        category="side",
        is_signature=False,
        base_price=1.29,
        available_qty=40,
        extra_metadata="{}",
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

    # Clear session cache before each test
    SESSION_CACHE.clear()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()

    # Clear session cache after each test
    SESSION_CACHE.clear()

    # Restore original credentials
    main_mod.ADMIN_USERNAME = original_username
    main_mod.ADMIN_PASSWORD = original_password


@pytest.fixture
def admin_auth():
    """Returns HTTP Basic Auth tuple for admin endpoints."""
    return (TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)
