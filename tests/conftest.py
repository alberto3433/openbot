import os
import pytest
import filelock
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Register conversation capture plugin (activate with --capture-convos)
pytest_plugins = ["tests.pytest_conversation_capture"]

# Load environment variables from .env file
load_dotenv()


def get_worker_lock_dir(tmp_path_factory):
    """Get a shared lock directory for all xdist workers.

    When running with pytest-xdist, each worker has its own tmp directory.
    We use the parent of these directories as a shared location for locks.
    """
    # Get the root temp directory shared by all workers
    return tmp_path_factory.getbasetemp().parent


def get_session_lock(tmp_path_factory, lock_name: str):
    """Get a file lock that coordinates across xdist workers."""
    lock_dir = get_worker_lock_dir(tmp_path_factory)
    lock_file = lock_dir / f"{lock_name}.lock"
    return filelock.FileLock(str(lock_file), timeout=120)


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
def _app_client_session(tmp_path_factory, menu_cache_loaded):
    """Session-scoped FastAPI TestClient setup.

    Creates the TestClient once for the entire test session to avoid
    restarting the server (lifespan events) for every test.

    Depends on menu_cache_loaded to ensure the cache is populated before
    TestClient triggers the app lifespan (which also calls load_from_db).
    With _is_loaded=True, the lifespan's load_from_db returns immediately.

    Uses file locking to coordinate database initialization across
    pytest-xdist workers, preventing race conditions.
    """
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL environment variable required")

    # Lazy imports to avoid requiring DATABASE_URL for non-db tests
    import orderbot.db as db
    import orderbot.config as config_mod
    from orderbot.db.models import Base, MenuItem
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

    # Use file lock to coordinate database setup across xdist workers
    # This prevents multiple workers from racing to create tables/seed data
    db_lock = get_session_lock(tmp_path_factory, "db_setup")
    with db_lock:
        # Create tables (including ChatSession)
        Base.metadata.create_all(bind=engine)

        # Seed minimal menu (using get-or-create to avoid duplicates)
        session = TestingSessionLocal()

        # Use distinctive names so we can identify and clean up test data
        test_menu_items = [
            {
                "name": "TEST Turkey Club",
                "is_signature": True,
                "available_qty": 5,
            },
            {
                "name": "TEST Veggie Delight",
                "is_signature": True,
                "available_qty": 10,
            },
            {
                "name": "TEST Italian Stallion",
                "is_signature": True,
                "available_qty": 10,
            },
            {
                "name": "TEST Custom Sandwich",
                "is_signature": False,
                "available_qty": 100,
            },
            {
                "name": "TEST soda",
                "is_signature": False,
                "available_qty": 10,
            },
            {
                "name": "TEST Chips",
                "is_signature": False,
                "available_qty": 40,
            },
        ]

        # Track IDs of items we create for cleanup
        created_item_ids = []
        for item_data in test_menu_items:
            existing = session.query(MenuItem).filter(MenuItem.name == item_data["name"]).first()
            if not existing:
                item = MenuItem(**item_data)
                session.add(item)
                session.flush()  # Get the ID
                created_item_ids.append(item.id)

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

    # Clean up test menu items we created
    with db_lock:
        cleanup_session = TestingSessionLocal()
        try:
            # Delete any menu items with TEST prefix (our test data)
            cleanup_session.query(MenuItem).filter(
                MenuItem.name.like("TEST %")
            ).delete(synchronize_session=False)
            cleanup_session.commit()
        except Exception as e:
            cleanup_session.rollback()
            print(f"Warning: Failed to clean up test menu items: {e}")
        finally:
            cleanup_session.close()

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
def menu_cache_loaded(tmp_path_factory):
    """Load the menu cache and menu data from the database for all tests.

    This is a session-scoped autouse fixture so the cache is loaded once at the
    start of the test session. This is required because spread/bagel types are
    loaded from the database - there are no hardcoded fallbacks.

    Also builds the menu_index dict and sets it as global menu_data for
    OrderStateMachine to use when tests don't explicitly pass menu_data.

    Uses file locking to coordinate cache loading across pytest-xdist workers,
    preventing race conditions during parallel test execution.

    Includes retry logic for Neon PostgreSQL serverless connections which may
    close unexpectedly during long test runs.
    """
    import time
    from sqlalchemy.exc import OperationalError

    if not TEST_DATABASE_URL:
        pytest.skip("DATABASE_URL environment variable required - spread/bagel types are loaded from database")

    from orderbot.cache import menu_cache
    from orderbot.menu_index import build_menu_index
    from orderbot.tasks.state_machine import set_global_menu_data

    # Use file lock to coordinate menu cache loading across xdist workers
    # Each worker still loads into its own process memory, but this prevents
    # database connection pool exhaustion during parallel initialization
    cache_lock = get_session_lock(tmp_path_factory, "menu_cache")

    max_retries = 3
    for attempt in range(max_retries):
        # Create fresh engine on each attempt (handles stale connections)
        engine = create_test_engine(TEST_DATABASE_URL)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        with cache_lock:
            db = TestingSessionLocal()
            try:
                # Load menu cache (spread types, bagel types, etc.)
                menu_cache.load_from_db(db, fail_on_error=True)

                # Build menu index dict and set as global for OrderStateMachine
                menu_data = build_menu_index(db)
                set_global_menu_data(menu_data)
                return menu_cache
            except OperationalError as e:
                db.close()
                engine.dispose()
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"DB connection failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    raise
            finally:
                if 'db' in dir():
                    db.close()

    return menu_cache


@pytest.fixture
def order_and_sm():
    """Create a fresh OrderTask (in TAKING_ITEMS phase) and OrderStateMachine.

    Usage in resiliency tests::

        def test_example(self, order_and_sm):
            order, sm = order_and_sm
            order.items.add_item(some_item)
            result = sm.process("user input", order)
    """
    from orderbot.tasks.state_machine import OrderStateMachine, OrderPhase
    from orderbot.tasks.models import OrderTask

    order = OrderTask()
    order.phase = OrderPhase.TAKING_ITEMS.value
    sm = OrderStateMachine()
    return order, sm
