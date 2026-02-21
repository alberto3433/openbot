"""Shared utilities for POS integrations (Square, Toast, etc.)."""

import logging

logger = logging.getLogger(__name__)


def get_httpx():
    """Lazy-import httpx to avoid hard dependency at module level.

    Returns the httpx module if available, or None with a warning if not installed.
    """
    try:
        import httpx
        return httpx
    except ImportError:
        logger.warning("httpx package not installed; POS integration disabled")
        return None
