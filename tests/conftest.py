import os
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Load environment variables from .env file
load_dotenv()

# Test admin credentials
TEST_ADMIN_USERNAME = "testadmin"
TEST_ADMIN_PASSWORD = "testpassword123"

# Use TEST_DATABASE_URL or derive from DATABASE_URL (checked lazily in fixtures)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture
def client():
    """Shared FastAPI TestClient using PostgreSQL test database.

    Uses transaction rollback for test isolation.
    Sets up test admin credentials for authentication.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL environment variable required")

    # Lazy imports to avoid requiring DATABASE_URL for non-db tests
    import sandwich_bot.db as db
    import sandwich_bot.main as main_mod
    import sandwich_bot.config as config_mod
    import sandwich_bot.auth as auth_mod
    from sandwich_bot.models import Base, MenuItem
    from sandwich_bot.main import app, SESSION_CACHE

    # Store original values from all modules that may cache these
    original_username = main_mod.ADMIN_USERNAME
    original_password = main_mod.ADMIN_PASSWORD
    original_config_username = config_mod.ADMIN_USERNAME
    original_config_password = config_mod.ADMIN_PASSWORD
    original_auth_username = auth_mod.ADMIN_USERNAME
    original_auth_password = auth_mod.ADMIN_PASSWORD

    # Set test credentials in all modules that may use them
    main_mod.ADMIN_USERNAME = TEST_ADMIN_USERNAME
    main_mod.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD
    config_mod.ADMIN_USERNAME = TEST_ADMIN_USERNAME
    config_mod.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD
    auth_mod.ADMIN_USERNAME = TEST_ADMIN_USERNAME
    auth_mod.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
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


@pytest.fixture
def disable_state_machine(monkeypatch):
    """Disable the state machine for tests that mock call_sandwich_bot.

    The state machine bypasses call_sandwich_bot entirely, so tests that
    rely on mocking call_sandwich_bot need to disable it to use the LLM path.
    """
    # Set the environment variable that controls the state machine
    monkeypatch.setenv("STATE_MACHINE_ENABLED", "false")
