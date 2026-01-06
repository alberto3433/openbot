"""
Tests for session persistence functionality.
"""
import os
import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sandwich_bot.models import Base, ChatSession
from sandwich_bot.services.session import (
    get_or_create_session,
    save_session,
    SESSION_CACHE,
    _cleanup_expired_sessions,
)


def unique_session_id(prefix: str = "test") -> str:
    """Generate a unique session ID for testing."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

# Use TEST_DATABASE_URL or derive from DATABASE_URL
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


@pytest.fixture
def db_session():
    """Create a PostgreSQL database session for testing."""
    # Clear cache before test
    SESSION_CACHE.clear()

    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL required for this test")

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    yield session
    session.close()

    # Clear the cache after each test
    SESSION_CACHE.clear()


class TestSessionPersistence:
    """Test session save and load from database."""

    def test_save_session_creates_new_record(self, db_session):
        """Test that save_session creates a new ChatSession record."""
        session_id = unique_session_id("save-new")
        session_data = {
            "history": [{"role": "assistant", "content": "Hello!"}],
            "order": {"status": "pending", "items": []},
        }

        save_session(db_session, session_id, session_data)

        # Verify record was created
        db_record = db_session.query(ChatSession).filter_by(session_id=session_id).first()
        assert db_record is not None
        assert db_record.session_id == session_id
        assert db_record.history == session_data["history"]
        assert db_record.order_state == session_data["order"]

    def test_save_session_updates_existing_record(self, db_session):
        """Test that save_session updates an existing ChatSession record."""
        session_id = unique_session_id("save-update")

        # Create initial session
        initial_data = {
            "history": [{"role": "assistant", "content": "Hello!"}],
            "order": {"status": "pending", "items": []},
        }
        save_session(db_session, session_id, initial_data)

        # Update session
        updated_data = {
            "history": [
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "I want a sandwich"},
            ],
            "order": {"status": "collecting_items", "items": [{"name": "Turkey Club"}]},
        }
        save_session(db_session, session_id, updated_data)

        # Verify only one record exists and it's updated
        records = db_session.query(ChatSession).filter_by(session_id=session_id).all()
        assert len(records) == 1
        assert records[0].history == updated_data["history"]
        assert records[0].order_state == updated_data["order"]

    def test_get_or_create_session_returns_none_for_unknown(self, db_session):
        """Test that get_or_create_session returns None for unknown session."""
        result = get_or_create_session(db_session, unique_session_id("nonexistent"))
        assert result is None

    def test_get_or_create_session_loads_from_database(self, db_session):
        """Test that get_or_create_session loads session from database."""
        session_id = unique_session_id("db-load")
        session_data = {
            "history": [{"role": "assistant", "content": "Welcome!"}],
            "order": {"status": "pending", "items": [], "total_price": 0.0},
        }

        # Save directly to database (bypassing cache)
        db_record = ChatSession(
            session_id=session_id,
            history=session_data["history"],
            order_state=session_data["order"],
        )
        db_session.add(db_record)
        db_session.commit()

        # Clear cache to force database lookup
        SESSION_CACHE.clear()

        # Load session
        result = get_or_create_session(db_session, session_id)

        assert result is not None
        assert result["history"] == session_data["history"]
        assert result["order"] == session_data["order"]

    def test_session_survives_cache_clear(self, db_session):
        """Test that session can be recovered after cache is cleared."""
        session_id = unique_session_id("persistent")
        session_data = {
            "history": [
                {"role": "assistant", "content": "Hello!"},
                {"role": "user", "content": "Hi there"},
            ],
            "order": {
                "status": "collecting_items",
                "items": [{"menu_item_name": "Turkey Club", "quantity": 1}],
            },
        }

        # Save session (goes to both cache and DB)
        save_session(db_session, session_id, session_data)

        # Clear cache (simulates server restart)
        SESSION_CACHE.clear()

        # Session should still be recoverable from DB
        result = get_or_create_session(db_session, session_id)

        assert result is not None
        assert result["history"] == session_data["history"]
        assert result["order"] == session_data["order"]


class TestSessionPersistenceIntegration:
    """Integration tests for session persistence with API endpoints."""

    def test_chat_start_creates_database_session(self, client):
        """Test that /chat/start creates a session in the database."""
        import sandwich_bot.db as db_mod

        resp = client.post("/chat/start")
        assert resp.status_code == 200

        session_id = resp.json()["session_id"]

        # Check database has the session
        TestingSessionLocal = db_mod.SessionLocal
        db_sess = TestingSessionLocal()
        db_record = db_sess.query(ChatSession).filter_by(session_id=session_id).first()
        db_sess.close()

        assert db_record is not None
        assert len(db_record.history) == 1  # Initial greeting
        assert db_record.order_state["status"] == "pending"


class TestSessionCacheTTL:
    """Test session cache TTL and eviction functionality."""

    def test_session_cache_stores_last_access_time(self, client):
        """Test that cache entries include last_access timestamp."""
        import time

        # Start a session via API (this goes through the proper DB)
        before = time.time()
        resp = client.post("/chat/start")
        after = time.time()

        session_id = resp.json()["session_id"]

        # Check cache entry has last_access
        assert session_id in SESSION_CACHE
        entry = SESSION_CACHE[session_id]
        assert "last_access" in entry
        assert "data" in entry
        assert before <= entry["last_access"] <= after

    def test_expired_sessions_are_cleaned_up(self, client, monkeypatch):
        """Test that expired sessions are removed from cache."""
        import time
        import sandwich_bot.db as db_mod
        import sandwich_bot.services.session as session_mod

        # Set a very short TTL for testing
        monkeypatch.setattr(session_mod, "SESSION_TTL_SECONDS", 1)

        # Start a session via API
        resp = client.post("/chat/start")
        session_id = resp.json()["session_id"]
        assert session_id in SESSION_CACHE

        # Artificially age the session
        SESSION_CACHE[session_id]["last_access"] = time.time() - 10

        # Cleanup should remove expired session
        removed = _cleanup_expired_sessions()
        assert removed >= 1
        assert session_id not in SESSION_CACHE

        # Session should still be in database
        TestingSessionLocal = db_mod.SessionLocal
        db_sess = TestingSessionLocal()
        db_record = db_sess.query(ChatSession).filter_by(session_id=session_id).first()
        db_sess.close()
        assert db_record is not None
