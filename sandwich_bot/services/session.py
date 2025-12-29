"""
Session Management Service for Sandwich Bot
============================================

This module manages chat session state with a two-tier storage strategy:
1. **In-Memory Cache**: Fast access for active sessions
2. **Database Persistence**: Durable storage for session recovery

Architecture Overview:
----------------------
The session system uses a write-through cache pattern:
- Reads check the cache first, then fall back to the database
- Writes update both the cache and database simultaneously
- Cache entries have TTL and LRU eviction to bound memory usage

This design optimizes for the common case (active conversations) while
ensuring no data loss if the server restarts.

Session Data Structure:
-----------------------
Each session contains:
- history: List of conversation messages [{role: "user"|"assistant", content: str}]
- order: Current order state (items, customer info, status, totals)
- menu_version: Hash of menu sent to LLM (for cache invalidation)
- store_id: Which store this session is associated with
- caller_id: Phone number for returning customer lookup
- returning_customer: Cached customer history for personalization

Cache Eviction Strategy:
------------------------
1. **TTL-based**: Sessions not accessed within SESSION_TTL_SECONDS are eligible
   for eviction. Checked probabilistically (~1% of requests) to avoid overhead.

2. **LRU-based**: When cache reaches SESSION_MAX_CACHE_SIZE, the oldest 10% of
   sessions (by last access time) are evicted to make room.

Thread Safety:
--------------
All cache operations are protected by a threading.Lock to ensure safe concurrent
access. This is important because FastAPI handles requests in multiple threads.

Performance Characteristics:
----------------------------
- Cache hit: O(1) dictionary lookup
- Cache miss: O(1) database query (indexed by session_id)
- Eviction: O(n log n) for sorting, but runs infrequently and on small batches

Configuration:
--------------
See config.py for these settings:
- SESSION_TTL_SECONDS: How long sessions stay in cache (default: 1 hour)
- SESSION_MAX_CACHE_SIZE: Maximum cached sessions (default: 1000)

Usage:
------
    from sandwich_bot.services.session import get_or_create_session, save_session

    # Get existing session or None if not found
    session = get_or_create_session(db, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")

    # Modify session data
    session["history"].append({"role": "user", "content": message})

    # Save changes to cache and database
    save_session(db, session_id, session)

Production Considerations:
--------------------------
For multi-worker deployments (e.g., Gunicorn with multiple workers), consider:
- Using Redis instead of in-memory cache for shared state
- Implementing cache invalidation across workers
- Adding distributed locking for session updates

The current in-memory implementation works well for single-worker deployments
and development. The database persistence ensures no data loss regardless of
cache strategy.
"""

import logging
import random
import threading
import time
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..config import SESSION_TTL_SECONDS, SESSION_MAX_CACHE_SIZE
from ..models import ChatSession


logger = logging.getLogger(__name__)


# =============================================================================
# Session Cache
# =============================================================================
# In-memory cache for active sessions. Structure:
# {session_id: {"data": {...session_data...}, "last_access": timestamp}}

SESSION_CACHE: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


# =============================================================================
# Cache Maintenance Functions
# =============================================================================

def _cleanup_expired_sessions() -> int:
    """
    Remove expired sessions from the cache.

    Sessions are considered expired if they haven't been accessed within
    SESSION_TTL_SECONDS. This is called probabilistically during normal
    operations to avoid dedicated cleanup overhead.

    Returns:
        int: Number of sessions removed from cache

    Note:
        This only removes sessions from the in-memory cache. The sessions
        remain in the database and can be restored on next access.
    """
    now = time.time()
    expired = []

    with _cache_lock:
        for sid, entry in SESSION_CACHE.items():
            if now - entry.get("last_access", 0) > SESSION_TTL_SECONDS:
                expired.append(sid)

        for sid in expired:
            del SESSION_CACHE[sid]

    if expired:
        logger.debug("Cleaned up %d expired sessions from cache", len(expired))

    return len(expired)


def _evict_oldest_sessions(count: int) -> None:
    """
    Evict the oldest sessions from cache to make room for new ones.

    Uses LRU (Least Recently Used) strategy based on last_access timestamp.
    Called when cache size exceeds SESSION_MAX_CACHE_SIZE.

    Args:
        count: Number of sessions to evict

    Note:
        Sessions evicted from cache are NOT deleted from the database.
        They will be restored to cache on next access.
    """
    with _cache_lock:
        if len(SESSION_CACHE) <= SESSION_MAX_CACHE_SIZE:
            return

        # Sort by last_access timestamp (oldest first)
        sorted_sessions = sorted(
            SESSION_CACHE.items(),
            key=lambda x: x[1].get("last_access", 0)
        )

        # Remove the oldest entries
        to_remove = sorted_sessions[:count]
        for sid, _ in to_remove:
            del SESSION_CACHE[sid]

        logger.debug("Evicted %d oldest sessions from cache", len(to_remove))


# =============================================================================
# Public Session Management Functions
# =============================================================================

def get_or_create_session(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
    """
    Get session data from cache or database.

    Implements the read path of the write-through cache:
    1. Check in-memory cache (fast path)
    2. If not in cache, query database
    3. If found in database, populate cache for future access
    4. Return None if session doesn't exist

    Args:
        db: SQLAlchemy database session for queries
        session_id: UUID string identifying the chat session

    Returns:
        Dict containing session data if found, None otherwise.
        Session data includes: history, order, menu_version, store_id,
        caller_id, and optionally returning_customer.

    Side Effects:
        - Updates last_access timestamp on cache hit
        - Populates cache on database hit
        - May trigger probabilistic cache cleanup (~1% of calls)
        - May evict old sessions if cache is full
    """
    # Probabilistic cleanup to avoid dedicated maintenance
    # Runs roughly once per 100 calls
    if random.randint(1, 100) == 1:
        _cleanup_expired_sessions()

    # Fast path: check cache first
    with _cache_lock:
        if session_id in SESSION_CACHE:
            entry = SESSION_CACHE[session_id]
            entry["last_access"] = time.time()
            return entry["data"]

    # Slow path: query database
    db_session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if db_session:
        # Restore session data from database
        session_data = {
            "history": db_session.history or [],
            "order": db_session.order_state or {},
            "menu_version": db_session.menu_version_sent,
            "store_id": db_session.store_id,
            "caller_id": db_session.caller_id,
        }

        # Add to cache for future access
        with _cache_lock:
            # Check if we need to evict before adding
            if len(SESSION_CACHE) >= SESSION_MAX_CACHE_SIZE:
                _evict_oldest_sessions(SESSION_MAX_CACHE_SIZE // 10)

            SESSION_CACHE[session_id] = {
                "data": session_data,
                "last_access": time.time(),
            }

        return session_data

    # Session not found anywhere
    return None


def save_session(db: Session, session_id: str, session_data: Dict[str, Any]) -> None:
    """
    Save session data to both cache and database.

    Implements the write path of the write-through cache:
    1. Update in-memory cache with new data and timestamp
    2. Upsert to database (update if exists, insert if new)
    3. Commit database transaction

    Args:
        db: SQLAlchemy database session for persistence
        session_id: UUID string identifying the chat session
        session_data: Dict containing session state to persist

    Side Effects:
        - Updates or creates cache entry
        - May evict old sessions if cache is full
        - Commits database transaction
        - Marks JSON columns as modified for SQLAlchemy change detection

    Note:
        Uses flag_modified() to ensure SQLAlchemy detects changes to mutable
        JSON columns. Without this, in-place mutations like list.append()
        would not be persisted to the database.
    """
    # Update cache
    with _cache_lock:
        # Evict if needed before adding new entry
        if len(SESSION_CACHE) >= SESSION_MAX_CACHE_SIZE and session_id not in SESSION_CACHE:
            _evict_oldest_sessions(SESSION_MAX_CACHE_SIZE // 10)

        SESSION_CACHE[session_id] = {
            "data": session_data,
            "last_access": time.time(),
        }

    # Persist to database (upsert pattern)
    db_session = db.query(ChatSession).filter(
        ChatSession.session_id == session_id
    ).first()

    if db_session:
        # Update existing session
        db_session.history = session_data.get("history", [])
        db_session.order_state = session_data.get("order", {})
        db_session.menu_version_sent = session_data.get("menu_version")
        db_session.store_id = session_data.get("store_id")
        db_session.caller_id = session_data.get("caller_id")

        # Force SQLAlchemy to detect changes to mutable JSON columns
        # Without this, in-place mutations (like list.append()) are not detected
        flag_modified(db_session, "history")
        flag_modified(db_session, "order_state")
    else:
        # Create new session
        db_session = ChatSession(
            session_id=session_id,
            history=session_data.get("history", []),
            order_state=session_data.get("order", {}),
            menu_version_sent=session_data.get("menu_version"),
            store_id=session_data.get("store_id"),
            caller_id=session_data.get("caller_id"),
        )
        db.add(db_session)

    db.commit()


def clear_cache() -> int:
    """
    Clear all sessions from the in-memory cache.

    Useful for testing and maintenance. Does NOT affect database storage.

    Returns:
        int: Number of sessions that were in cache before clearing
    """
    with _cache_lock:
        count = len(SESSION_CACHE)
        SESSION_CACHE.clear()
        logger.info("Cleared %d sessions from cache", count)
        return count


def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the session cache.

    Useful for monitoring and debugging cache behavior.

    Returns:
        Dict with cache statistics:
        - size: Current number of cached sessions
        - max_size: Maximum allowed sessions
        - ttl_seconds: TTL for cache entries
        - oldest_access: Timestamp of oldest entry (or None if empty)
        - newest_access: Timestamp of newest entry (or None if empty)
    """
    with _cache_lock:
        if not SESSION_CACHE:
            return {
                "size": 0,
                "max_size": SESSION_MAX_CACHE_SIZE,
                "ttl_seconds": SESSION_TTL_SECONDS,
                "oldest_access": None,
                "newest_access": None,
            }

        access_times = [entry["last_access"] for entry in SESSION_CACHE.values()]
        return {
            "size": len(SESSION_CACHE),
            "max_size": SESSION_MAX_CACHE_SIZE,
            "ttl_seconds": SESSION_TTL_SECONDS,
            "oldest_access": min(access_times),
            "newest_access": max(access_times),
        }
