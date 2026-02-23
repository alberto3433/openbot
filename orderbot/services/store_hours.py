"""
Store Hours Service
===================

Pure functions for store hours checking, next-open-time calculation,
and scheduled pickup time validation.

All functions take hours data + timezone as arguments — no DB dependency.
Uses ``zoneinfo.ZoneInfo`` (stdlib) for timezone handling.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


# Day-name aliases for robust matching
_DAY_ALIASES: dict[str, int] = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

# isoweekday -> short name used in output
_WEEKDAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
                  4: "Friday", 5: "Saturday", 6: "Sunday"}

_WEEKDAY_SHORT = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu",
                  4: "Fri", 5: "Sat", 6: "Sun"}

# Regex to parse compact hour strings like "7-5", "07:00-17:00", "7am-5pm"
_HOUR_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_time_str(hour: int, minute: int, ampm: str | None) -> time:
    """Convert hour/minute/ampm to a ``datetime.time``."""
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
    # Heuristic: bare numbers < 7 probably mean PM (e.g. "7-5" = 7am-5pm)
    return time(hour, minute)


def _normalise_day_key(key: str) -> int | None:
    """Map a day string to weekday int (0=Mon … 6=Sun)."""
    return _DAY_ALIASES.get(key.lower().strip())


def _parse_single_range(value: dict) -> tuple[time, time] | None:
    """Parse a single ``{"open": "07:00", "close": "17:00"}`` dict into (open, close)."""
    try:
        open_parts = str(value["open"]).split(":")
        close_parts = str(value["close"]).split(":")
        open_t = time(int(open_parts[0]), int(open_parts[1]) if len(open_parts) > 1 else 0)
        close_t = time(int(close_parts[0]), int(close_parts[1]) if len(close_parts) > 1 else 0)
        return (open_t, close_t)
    except (KeyError, ValueError, IndexError):
        return None


def _format_time_12h(t: time) -> str:
    """Format a time as '7:00 AM' style string."""
    try:
        return t.strftime("%-I:%M %p")
    except ValueError:
        # Windows doesn't support %-I
        return t.strftime("%I:%M %p").lstrip("0")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# weekday -> list of (open, close) ranges
HoursConfig = dict[int, list[tuple[time, time]]]


def parse_hours_config(raw_hours: Any) -> HoursConfig | None:
    """Normalise hours from various DB formats into ``{weekday: [(open, close), ...]}``.

    Accepted input shapes:

    * ``{"monday": [{"open": "07:00", "close": "21:00"}]}``  — new list-of-ranges format
    * ``{"mon": "7-5", "tue": "7:00-17:00"}``   — compact string ranges (legacy)
    * ``{"mon": {"open": "07:00", "close": "17:00"}}`` — single dict (legacy)
    * ``{"monday": "7am-5pm"}``   — full day names with AM/PM (legacy)
    * ``None`` / empty / unparseable → returns ``None``

    Returns:
        Normalised mapping weekday-int → list of (open_time, close_time), or None.
    """
    if not raw_hours or not isinstance(raw_hours, dict):
        return None

    result: HoursConfig = {}
    for day_key, value in raw_hours.items():
        weekday = _normalise_day_key(str(day_key))
        if weekday is None:
            continue

        if isinstance(value, list):
            # New format: [{"open": "07:00", "close": "21:00"}, ...]
            ranges: list[tuple[time, time]] = []
            for entry in value:
                if isinstance(entry, dict):
                    parsed = _parse_single_range(entry)
                    if parsed:
                        ranges.append(parsed)
            if ranges:
                result[weekday] = ranges
            # Empty list = closed, so we don't add an entry

        elif isinstance(value, dict):
            # Legacy single dict: {"open": "07:00", "close": "17:00"}
            parsed = _parse_single_range(value)
            if parsed:
                result[weekday] = [parsed]

        elif isinstance(value, str):
            if value.lower() in ("closed", "off", ""):
                continue
            m = _HOUR_RANGE_RE.match(value.strip())
            if not m:
                continue
            open_h, open_m, open_ap, close_h, close_m, close_ap = m.groups()
            open_t = _parse_time_str(int(open_h), int(open_m or 0), open_ap)
            close_t = _parse_time_str(int(close_h), int(close_m or 0), close_ap)
            # Heuristic: if close <= open and no AM/PM given, assume close is PM
            if close_t <= open_t and not close_ap:
                close_t = time(close_t.hour + 12, close_t.minute)
            result[weekday] = [(open_t, close_t)]

    return result if result else None


def is_store_open_now(hours_config: HoursConfig | None, timezone_str: str) -> bool:
    """Check whether the store is currently open.

    Args:
        hours_config: Normalised hours from :func:`parse_hours_config`.
        timezone_str: IANA timezone string (e.g. ``"America/New_York"``).

    Returns:
        True if the store is open right now, False otherwise.
        Returns True (assume open) if hours_config is None.
    """
    if hours_config is None:
        return True  # No hours data → assume open

    now = datetime.now(ZoneInfo(timezone_str))
    weekday = now.weekday()  # 0=Mon
    ranges = hours_config.get(weekday)
    if ranges is None:
        return False  # No entry for today → closed

    return any(open_t <= now.time() < close_t for open_t, close_t in ranges)


def get_next_open_time(
    hours_config: HoursConfig | None,
    timezone_str: str,
) -> datetime | None:
    """Get the next datetime the store opens.

    Searches up to 7 days ahead. Returns None if hours_config is empty
    or no open day is found within a week.
    """
    if hours_config is None:
        return None

    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    for day_offset in range(0, 8):
        candidate = now + timedelta(days=day_offset)
        weekday = candidate.weekday()
        ranges = hours_config.get(weekday)
        if ranges is None:
            continue

        # Check each range sorted by open time — find earliest future open
        for open_t, _ in sorted(ranges, key=lambda r: r[0]):
            open_dt = candidate.replace(
                hour=open_t.hour, minute=open_t.minute, second=0, microsecond=0,
            )
            if open_dt > now:
                return open_dt

    return None


def get_next_open_time_display(
    hours_config: HoursConfig | None,
    timezone_str: str,
) -> str | None:
    """Human-readable string for the next open time.

    Examples: ``"tomorrow at 7:00 AM"``, ``"Monday at 7:00 AM"``.
    Returns None when no open time can be determined.
    """
    next_open = get_next_open_time(hours_config, timezone_str)
    if next_open is None:
        return None

    now = datetime.now(ZoneInfo(timezone_str))
    days_ahead = (next_open.date() - now.date()).days
    time_str = _format_time_12h(next_open.time())

    if days_ahead == 0:
        return f"today at {time_str}"
    elif days_ahead == 1:
        return f"tomorrow at {time_str}"
    else:
        day_name = _WEEKDAY_NAMES[next_open.weekday()]
        return f"{day_name} at {time_str}"


def validate_scheduled_time(
    requested_time: datetime,
    hours_config: HoursConfig | None,
    timezone_str: str,
    max_days: int = 3,
) -> tuple[bool, str | None]:
    """Validate a requested pickup time against store hours.

    Args:
        requested_time: The customer's requested pickup time (tz-aware).
        hours_config: Normalised store hours.
        timezone_str: IANA timezone string.
        max_days: Maximum days in the future to allow.

    Returns:
        ``(True, None)`` if valid, ``(False, error_message)`` otherwise.
    """
    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    # Ensure requested_time is tz-aware in the store's timezone
    if requested_time.tzinfo is None:
        requested_time = requested_time.replace(tzinfo=tz)

    # Check: not in the past
    if requested_time < now - timedelta(minutes=5):
        return False, "That time has already passed. Could you pick a later time?"

    # Check: not too far ahead
    max_future = now + timedelta(days=max_days)
    if requested_time > max_future:
        return False, f"We can only schedule orders up to {max_days} days ahead."

    # Check: store is open at that time
    if hours_config is not None:
        weekday = requested_time.weekday()
        ranges = hours_config.get(weekday)
        if ranges is None:
            day_name = _WEEKDAY_NAMES[weekday]
            return False, f"We're closed on {day_name}s. Would you like to pick another time?"

        req_time = requested_time.time()
        if not any(open_t <= req_time < close_t for open_t, close_t in ranges):
            # Build error message showing all ranges for that day
            range_strs = [
                f"{_format_time_12h(open_t)} to {_format_time_12h(close_t)}"
                for open_t, close_t in sorted(ranges, key=lambda r: r[0])
            ]
            hours_display = " and ".join(range_strs)
            return False, (
                f"We're open {hours_display} that day. "
                f"Could you pick a time during those hours?"
            )

    return True, None


def format_hours_display(hours: dict | None) -> str | None:
    """Convert structured hours JSON to a human-readable string.

    Groups consecutive days with identical hours for compact display.

    Examples:
        ``"Mon-Fri 7:00 AM - 9:00 PM, Sat-Sun Closed"``
        ``"Mon-Thu 7:00 AM - 9:00 PM, Fri 7:00 AM - 2:00 PM & 5:00 PM - 9:00 PM"``

    Args:
        hours: Structured hours dict from DB (``{"monday": [...], ...}``).

    Returns:
        Human-readable hours string, or None if hours is None/empty.
    """
    if not hours or not isinstance(hours, dict):
        return None

    day_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_short = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed",
                 "thursday": "Thu", "friday": "Fri", "saturday": "Sat", "sunday": "Sun"}

    # Build a description for each day
    day_descriptions: list[tuple[str, str]] = []  # (short_name, description)
    for day in day_order:
        short = day_short[day]
        ranges = hours.get(day, [])
        if not ranges:
            day_descriptions.append((short, "Closed"))
        else:
            range_strs = []
            for r in ranges:
                if isinstance(r, dict) and "open" in r and "close" in r:
                    try:
                        op = r["open"].split(":")
                        cl = r["close"].split(":")
                        open_t = time(int(op[0]), int(op[1]) if len(op) > 1 else 0)
                        close_t = time(int(cl[0]), int(cl[1]) if len(cl) > 1 else 0)
                        range_strs.append(f"{_format_time_12h(open_t)} - {_format_time_12h(close_t)}")
                    except (ValueError, IndexError):
                        continue
            if range_strs:
                day_descriptions.append((short, " & ".join(range_strs)))
            else:
                day_descriptions.append((short, "Closed"))

    # Group consecutive days with the same description
    groups: list[tuple[list[str], str]] = []
    for short_name, desc in day_descriptions:
        if groups and groups[-1][1] == desc:
            groups[-1][0].append(short_name)
        else:
            groups.append(([short_name], desc))

    # Format groups
    parts = []
    for names, desc in groups:
        if len(names) == 1:
            parts.append(f"{names[0]} {desc}")
        else:
            parts.append(f"{names[0]}-{names[-1]} {desc}")

    return ", ".join(parts) if parts else None
