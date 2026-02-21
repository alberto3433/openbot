"""Shared utilities for POS integrations (Square, Toast, etc.)."""

import logging

logger = logging.getLogger(__name__)

_httpx = None


def get_httpx():
    """Lazy-import httpx to avoid hard dependency at module level.

    Returns the httpx module if available, or None with a warning if not installed.
    Caches the result after first import.
    """
    global _httpx
    if _httpx is not None:
        return _httpx
    try:
        import httpx
        _httpx = httpx
        return _httpx
    except ImportError:
        logger.warning("httpx package not installed; POS integration disabled")
        return None
