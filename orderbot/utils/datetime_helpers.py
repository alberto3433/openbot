"""Timezone-aware datetime helpers.

Replaces deprecated ``datetime.utcnow()`` with timezone-aware equivalents.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def format_datetime_for_api(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with a trailing ``Z`` suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
