"""Scheduling Patterns - pickup-later, time change, time selection."""

import re

PICKUP_LATER_PATTERN = re.compile(
    r'\b(?:pick\s*up|pickup)\b.*\blater\b'
    r'|\blater\b.*\b(?:pick\s*up|pickup)\b'
    r'|\bschedule\s+(?:a\s+)?(?:pick\s*up|pickup)\b',
    re.IGNORECASE,
)

TIME_UPDATE_PATTERN = re.compile(
    r'\b(?:change|update|modify|set|edit)\s+(?:pickup|delivery|order)?\s*time\b',
    re.IGNORECASE,
)

TIME_SELECTION_PATTERN = re.compile(
    r'\bchoose\s+a?\s*(?:specific\s+)?time\b',
    re.IGNORECASE,
)
