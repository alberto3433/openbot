"""
Rate limiting configuration for the Orderbot API.

Provides a shared limiter instance and key function used by both
main.py and routes/chat.py.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import RATE_LIMIT_ENABLED


def get_session_id_or_ip(request: Request) -> str:
    """Get rate limit key from session_id or fall back to IP."""
    if hasattr(request.state, "body_json") and request.state.body_json:
        session_id = request.state.body_json.get("session_id")
        if session_id:
            return f"session:{session_id}"
    return get_remote_address(request)


limiter = Limiter(key_func=get_session_id_or_ip, enabled=RATE_LIMIT_ENABLED)
