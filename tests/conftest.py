import os
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Load environment variables from .env file
load_dotenv()


def create_test_engine(database_url: str):
    """Create a database engine with connection pooling for better performance.

    Uses QueuePool with small pool size to reuse connections across queries,
    significantly reducing latency with remote Neon PostgreSQL (~50-100ms per connection).
    """
    from sqlalchemy.pool import QueuePool
    return create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=2,        # Small pool for tests
        max_overflow=3,     # Limited overflow
        pool_timeout=10,    # Fail fast if no connection
        pool_recycle=300,   # Recycle every 5 min
        pool_pre_ping=True,  # Verify connection is alive
    )

# Test admin credentials
TEST_ADMIN_USERNAME = "testadmin"
TEST_ADMIN_PASSWORD = "testpassword123"

# Use TEST_DATABASE_URL or derive from DATABASE_URL (checked lazily in fixtures)
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture(scope="session")
def _app_client_session():
    """Session-scoped FastAPI TestClient setup.

    Creates the TestClient once for the entire test session to avoid
    restarting the server (lifespan events) for every test.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL environment variable required")

    # Lazy imports to avoid requiring DATABASE_URL for non-db tests
    import orderbot.db as db
    import orderbot.config as config_mod
    from orderbot.models import Base, MenuItem
    from orderbot.main import app

    # Store original values
    original_config_username = config_mod.ADMIN_USERNAME
    original_config_password = config_mod.ADMIN_PASSWORD

    # Set test credentials
    config_mod.ADMIN_USERNAME = TEST_ADMIN_USERNAME
    config_mod.ADMIN_PASSWORD = TEST_ADMIN_PASSWORD

    engine = create_test_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the db module used by the app
    db.engine = engine
    db.SessionLocal = TestingSessionLocal

    # Create tables (including ChatSession)
    Base.metadata.create_all(bind=engine)

    # Seed minimal menu (using get-or-create to avoid duplicates)
    session = TestingSessionLocal()

    test_menu_items = [
        {
            "name": "Turkey Club",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 8.0,
            "available_qty": 5,
            "extra_metadata": "{}",
        },
        {
            "name": "Veggie Delight",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 7.99,
            "available_qty": 10,
            "extra_metadata": "{}",
        },
        {
            "name": "Italian Stallion",
            "category": "sandwich",
            "is_signature": True,
            "base_price": 9.49,
            "available_qty": 10,
            "extra_metadata": "{}",
        },
        {
            "name": "Custom Sandwich",
            "category": "sandwich",
            "is_signature": False,
            "base_price": 5.99,
            "available_qty": 100,
            "extra_metadata": '{"is_custom": true}',
        },
        {
            "name": "soda",
            "category": "drink",
            "is_signature": False,
            "base_price": 2.5,
            "available_qty": 10,
            "extra_metadata": "{}",
        },
        {
            "name": "Chips",
            "category": "side",
            "is_signature": False,
            "base_price": 1.29,
            "available_qty": 40,
            "extra_metadata": "{}",
        },
    ]

    for item_data in test_menu_items:
        existing = session.query(MenuItem).filter(MenuItem.name == item_data["name"]).first()
        if not existing:
            session.add(MenuItem(**item_data))

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

    # Create TestClient once - this triggers lifespan events (startup/shutdown)
    # only once for the entire test session
    with TestClient(app) as test_client:
        yield test_client

    # Cleanup after all tests complete
    app.dependency_overrides.clear()

    # Restore original credentials
    config_mod.ADMIN_USERNAME = original_config_username
    config_mod.ADMIN_PASSWORD = original_config_password


@pytest.fixture
def client(_app_client_session):
    """Function-scoped client that reuses the session-scoped TestClient.

    Clears session cache before/after each test for isolation.
    The server is NOT restarted between tests - only the cache is cleared.
    """
    from orderbot.services.session import SESSION_CACHE

    # Clear session cache before test
    SESSION_CACHE.clear()

    yield _app_client_session

    # Clear session cache after test
    SESSION_CACHE.clear()


@pytest.fixture
def admin_auth():
    """Returns HTTP Basic Auth tuple for admin endpoints."""
    return (TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def menu_cache_loaded():
    """Load the menu cache and menu data from the database for all tests.

    This is a session-scoped autouse fixture so the cache is loaded once at the
    start of the test session. This is required because spread/bagel types are
    loaded from the database - there are no hardcoded fallbacks.

    Also builds the menu_index dict and sets it as global menu_data for
    OrderStateMachine to use when tests don't explicitly pass menu_data.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("DATABASE_URL environment variable required - spread/bagel types are loaded from database")

    from orderbot.menu_data_cache import menu_cache
    from orderbot.menu_index_builder import build_menu_index
    from orderbot.tasks.state_machine import set_global_menu_data

    engine = create_test_engine(TEST_DATABASE_URL)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    try:
        # Load menu cache (spread types, bagel types, etc.)
        menu_cache.load_from_db(db, fail_on_error=True)

        # Build menu index dict and set as global for OrderStateMachine
        menu_data = build_menu_index(db)
        set_global_menu_data(menu_data)
    finally:
        db.close()

    return menu_cache
