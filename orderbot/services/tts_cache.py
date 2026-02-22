"""
TTS Prefetch Cache
==================

In-memory cache that pre-synthesizes TTS audio in parallel with token streaming,
so audio is ready by the time the frontend requests it.

Architecture:
    Server generates reply → prefetch_tts() schedules async TTS synthesis
    → tokens stream to frontend (~300ms) → frontend GETs /tts/audio/{id}
    → audio already cached, returned immediately

Thread safety:
    The generate_stream() runs in a sync generator (thread), while TTS synthesis
    is async. We use asyncio.run_coroutine_threadsafe() to schedule the async
    TTS call on the main event loop, and threading.Event for cross-thread sync.
"""

import asyncio
import logging
import time
import threading
import uuid

logger = logging.getLogger(__name__)

# Cache storage: {audio_id: {"bytes": bytes|None, "ready": Event, "created_at": float}}
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()

# Reference to the main asyncio event loop, set at startup
_main_loop: asyncio.AbstractEventLoop | None = None

# TTL for cache entries (seconds)
_ENTRY_TTL = 60


def init_tts_cache(loop: asyncio.AbstractEventLoop) -> None:
    """Store the main event loop reference. Called once from lifespan startup."""
    global _main_loop
    _main_loop = loop


def prefetch_tts(text: str, voice_id: str | None = None, speed: float = 1.0) -> str | None:
    """
    Schedule TTS synthesis in the background and return an audio_id immediately.

    Safe to call from any thread (sync generator or async context).
    Returns None if the cache is not initialized.
    """
    if _main_loop is None:
        logger.debug("TTS prefetch cache not initialized, skipping prefetch")
        return None

    if not text or not text.strip():
        return None

    # Resolve the TTS provider name synchronously (DB access) so the async
    # coroutine doesn't need to open its own session.
    provider_name: str | None = None
    try:
        from ..db import SessionLocal
        from .store_service import get_or_create_company

        db = SessionLocal()
        try:
            company = get_or_create_company(db)
            provider_name = company.tts_provider
        finally:
            db.close()
    except (ImportError, OSError, ValueError, TypeError) as exc:
        logger.debug("Could not read TTS provider from company: %s", exc)

    audio_id = uuid.uuid4().hex[:16]
    ready_event = threading.Event()

    with _cache_lock:
        # Lazy cleanup of expired entries
        _cleanup_expired()
        _cache[audio_id] = {
            "bytes": None,
            "ready": ready_event,
            "created_at": time.monotonic(),
        }

    # Schedule the async TTS synthesis on the main event loop
    asyncio.run_coroutine_threadsafe(
        _synthesize_and_cache(audio_id, text, voice_id, speed, provider_name),
        _main_loop,
    )

    logger.debug("TTS prefetch scheduled: %s (%d chars)", audio_id, len(text))
    return audio_id


async def _synthesize_and_cache(
    audio_id: str, text: str, voice_id: str | None, speed: float,
    provider_name: str | None = None,
) -> None:
    """Run TTS synthesis and store result in cache. Always sets ready event."""
    try:
        from .tts import get_tts_provider

        provider = get_tts_provider(provider_name)
        audio_bytes = await provider.synthesize(text=text, voice_id=voice_id, speed=speed)

        with _cache_lock:
            entry = _cache.get(audio_id)
            if entry is not None:
                entry["bytes"] = audio_bytes
                logger.debug("TTS prefetch complete: %s (%d bytes)", audio_id, len(audio_bytes))
    except Exception:
        logger.warning("TTS prefetch failed for %s", audio_id, exc_info=True)
    finally:
        # Always unblock waiters
        with _cache_lock:
            entry = _cache.get(audio_id)
            if entry is not None:
                entry["ready"].set()


def get_cached_audio(audio_id: str, timeout: float = 10.0) -> bytes | None:
    """
    Wait for prefetched audio and return it. Removes entry from cache.

    Returns None on timeout, cache miss, or synthesis failure.
    Blocking call — use asyncio.to_thread() from async context.
    """
    with _cache_lock:
        entry = _cache.get(audio_id)
        if entry is None:
            return None

    # Wait outside the lock
    entry["ready"].wait(timeout=timeout)

    with _cache_lock:
        entry = _cache.pop(audio_id, None)
        if entry is None:
            return None
        return entry.get("bytes")


def _cleanup_expired() -> None:
    """Remove expired cache entries. Must be called with _cache_lock held."""
    now = time.monotonic()
    expired = [k for k, v in _cache.items() if now - v["created_at"] > _ENTRY_TTL]
    for k in expired:
        _cache.pop(k, None)
    if expired:
        logger.debug("TTS cache cleanup: removed %d expired entries", len(expired))
