"""
Time Expression Parser
======================

Deterministic regex-based parser for natural language time expressions
in customer messages. Returns a ``ParsedTime`` when a time expression
is found, otherwise ``None``.

Supported formats:
  - Absolute: "3pm", "3:30 PM", "at 3", "15:00"
  - Relative: "in 2 hours", "in 30 minutes"
  - Day + time: "tomorrow at 3pm", "Saturday at noon"
  - Named periods: "morning", "afternoon", "evening"
  - ASAP: "now", "ASAP", "as soon as possible"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo


@dataclass
class ParsedTime:
    """Result of parsing a time expression."""
    time_value: datetime | None  # Resolved datetime (tz-aware), None for ASAP
    is_asap: bool
    raw_text: str


# ---------------------------------------------------------------------------
# Named time periods → (hour, minute)
# ---------------------------------------------------------------------------

_NAMED_PERIODS: dict[str, tuple[int, int]] = {
    "morning": (7, 0),     # Will use store opening time if available
    "afternoon": (12, 0),
    "evening": (17, 0),
    "noon": (12, 0),
    "lunchtime": (12, 0),
    "lunch": (12, 0),
}


# ---------------------------------------------------------------------------
# Day name mapping
# ---------------------------------------------------------------------------

_DAY_NAMES: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3,
    "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6,
}


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# ASAP patterns
_ASAP_RE = re.compile(
    r"\b(?:asap|a\.s\.a\.p\.?|as\s+soon\s+as\s+possible|right\s+now|right\s+away)\b",
    re.IGNORECASE,
)

# Word-number mapping for relative time expressions
_WORD_NUMBERS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "forty-five": 45, "forty five": 45, "ninety": 90,
}

# Relative time: "in 2 hours", "in 30 minutes", "in an hour", "in one hour"
_WORD_NUM_ALTS = "|".join(_WORD_NUMBERS.keys())
_RELATIVE_RE = re.compile(
    r"\bin\s+(?:(?:an?|(\d+)|(" + _WORD_NUM_ALTS + r"))\s+)?(hours?|minutes?|mins?|hrs?)\b",
    re.IGNORECASE,
)

# Absolute time: "3pm", "3:30 PM", "at 3", "15:00", "at 3:30pm"
_ABSOLUTE_TIME_RE = re.compile(
    r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)

# Day references: "tomorrow", "today", day names
_DAY_REF_RE = re.compile(
    r"\b(today|tomorrow|"
    + "|".join(_DAY_NAMES.keys())
    + r")\b",
    re.IGNORECASE,
)

# Named period: "morning", "afternoon", "evening", "noon"
_NAMED_PERIOD_RE = re.compile(
    r"\b(" + "|".join(_NAMED_PERIODS.keys()) + r")\b",
    re.IGNORECASE,
)

# Full pattern: "[day] at [time]" or "[day] [period]"
# e.g., "tomorrow at 3pm", "tomorrow morning", "Saturday at noon"
_DAY_TIME_RE = re.compile(
    r"\b(today|tomorrow|"
    + "|".join(_DAY_NAMES.keys())
    + r")\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?",
    re.IGNORECASE,
)

_DAY_PERIOD_RE = re.compile(
    r"\b(today|tomorrow|"
    + "|".join(_DAY_NAMES.keys())
    + r")\s+(?:at\s+|in\s+the\s+)?(" + "|".join(_NAMED_PERIODS.keys()) + r")\b",
    re.IGNORECASE,
)

# "pickup at 3pm", "for 3pm", "pickup for tomorrow"
_SCHEDULING_CONTEXT_RE = re.compile(
    r"\b(?:pick\s*up|schedule|scheduled|for)\s+",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_day_reference(day_ref: str, now: datetime) -> datetime:
    """Resolve 'today', 'tomorrow', or a weekday name to a date."""
    day_lower = day_ref.lower().strip()
    if day_lower == "today":
        return now
    if day_lower == "tomorrow":
        return now + timedelta(days=1)

    target_weekday = _DAY_NAMES.get(day_lower)
    if target_weekday is not None:
        current_weekday = now.weekday()
        days_ahead = (target_weekday - current_weekday) % 7
        if days_ahead == 0:
            days_ahead = 7  # Next week's same day
        return now + timedelta(days=days_ahead)

    return now


def _resolve_absolute_time(
    hour: int, minute: int, ampm: str | None, now: datetime
) -> datetime:
    """Resolve an absolute time to a datetime (today or tomorrow)."""
    if ampm:
        ampm_clean = ampm.lower().replace(".", "")
        if ampm_clean == "pm" and hour != 12:
            hour += 12
        elif ampm_clean == "am" and hour == 12:
            hour = 0
    else:
        # No AM/PM: use heuristic — hours 1-6 → PM, 7-12 → contextual
        if 1 <= hour <= 6:
            hour += 12

    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # If the time is in the past, assume tomorrow
    if result <= now:
        result += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_time_expression(
    text: str,
    timezone_str: str = "America/New_York",
) -> ParsedTime | None:
    """Parse a natural language time expression from user input.

    Args:
        text: User's message text.
        timezone_str: IANA timezone for resolving times.

    Returns:
        ``ParsedTime`` if a time expression was found, ``None`` otherwise.
    """
    tz = ZoneInfo(timezone_str)
    now = datetime.now(tz)

    # 1. ASAP
    m = _ASAP_RE.search(text)
    if m:
        return ParsedTime(time_value=None, is_asap=True, raw_text=m.group())

    # 2. Day + absolute time: "tomorrow at 3pm"
    m = _DAY_TIME_RE.search(text)
    if m:
        day_ref, hour_s, min_s, ampm = m.groups()
        base_date = _resolve_day_reference(day_ref, now)
        hour = int(hour_s)
        minute = int(min_s) if min_s else 0
        if ampm:
            ampm_clean = ampm.lower().replace(".", "")
            if ampm_clean == "pm" and hour != 12:
                hour += 12
            elif ampm_clean == "am" and hour == 12:
                hour = 0
        else:
            if 1 <= hour <= 6:
                hour += 12
        result_dt = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return ParsedTime(time_value=result_dt, is_asap=False, raw_text=m.group())

    # 3. Day + named period: "tomorrow morning"
    m = _DAY_PERIOD_RE.search(text)
    if m:
        day_ref, period = m.groups()
        base_date = _resolve_day_reference(day_ref, now)
        period_time = _NAMED_PERIODS.get(period.lower(), (12, 0))
        result_dt = base_date.replace(
            hour=period_time[0], minute=period_time[1], second=0, microsecond=0,
        )
        return ParsedTime(time_value=result_dt, is_asap=False, raw_text=m.group())

    # 4. Relative time: "in 2 hours", "in 30 minutes"
    m = _RELATIVE_RE.search(text)
    if m:
        digit_str, word_str, unit = m.groups()
        if digit_str:
            qty = int(digit_str)
        elif word_str:
            qty = _WORD_NUMBERS.get(word_str.lower(), 1)
        else:
            qty = 1  # "in an hour" / "in a minute"
        unit_lower = unit.lower()
        if unit_lower.startswith("h"):
            delta = timedelta(hours=qty)
        else:
            delta = timedelta(minutes=qty)
        result_dt = now + delta
        return ParsedTime(time_value=result_dt, is_asap=False, raw_text=m.group())

    # 5. Standalone absolute time with scheduling context: "pickup at 3pm", "for 3pm"
    # Only match if there's scheduling context to avoid false positives
    if _SCHEDULING_CONTEXT_RE.search(text):
        m = _ABSOLUTE_TIME_RE.search(text)
        if m:
            hour_s, min_s, ampm = m.groups()
            hour = int(hour_s)
            # Skip very large numbers that aren't times
            if hour > 24:
                return None
            minute = int(min_s) if min_s else 0
            result_dt = _resolve_absolute_time(hour, minute, ampm, now)
            return ParsedTime(time_value=result_dt, is_asap=False, raw_text=m.group())

    # 6. Standalone absolute time with explicit AM/PM (higher confidence)
    m = _ABSOLUTE_TIME_RE.search(text)
    if m:
        hour_s, min_s, ampm = m.groups()
        if ampm:  # Only match if AM/PM is explicit (avoid false positives on bare numbers)
            hour = int(hour_s)
            if hour > 12:
                return None
            minute = int(min_s) if min_s else 0
            result_dt = _resolve_absolute_time(hour, minute, ampm, now)
            return ParsedTime(time_value=result_dt, is_asap=False, raw_text=m.group())

    return None
