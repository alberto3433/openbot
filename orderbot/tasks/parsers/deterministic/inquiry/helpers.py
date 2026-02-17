"""Common helpers for inquiry parsers.

These utilities reduce boilerplate in inquiry parsers without
forcing them into a rigid base class structure.
"""

import logging
import re
from re import Pattern, Match

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text

logger = logging.getLogger(__name__)


def first_match(patterns: list[Pattern], text: str) -> Match | None:
    """Return the first matching pattern's match object, or None.

    Args:
        patterns: List of compiled regex patterns
        text: Text to search

    Returns:
        First successful Match object, or None if no match
    """
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match
    return None


def any_pattern_matches(patterns: list[Pattern], text: str) -> bool:
    """Check if any pattern matches the text.

    Args:
        patterns: List of compiled regex patterns
        text: Text to search

    Returns:
        True if any pattern matches
    """
    return any(pattern.search(text) for pattern in patterns)


def extract_group(match: Match, group: int) -> str | None:
    """Safely extract and clean a capture group from a match.

    Args:
        match: Regex match object
        group: Group number to extract (1-based)

    Returns:
        Cleaned extracted text, or None if extraction fails
    """
    if group <= 0:
        return None
    try:
        text = match.group(group)
        if text:
            return clean_extracted_text(text.strip())
    except (IndexError, AttributeError):
        pass
    return None


def log_inquiry(inquiry_type: str, text: str, **details) -> None:
    """Log an inquiry detection with consistent formatting.

    Args:
        inquiry_type: Type of inquiry (e.g., "PRICE", "MENU", "STORE HOURS")
        text: Original user text (will be truncated)
        **details: Additional details to log
    """
    detail_str = ", ".join(f"{k}={v}" for k, v in details.items()) if details else ""
    if detail_str:
        logger.info("%s INQUIRY: '%s' -> %s", inquiry_type, text[:50], detail_str)
    else:
        logger.info("%s INQUIRY: '%s'", inquiry_type, text[:50])


def simple_inquiry_check(
    patterns: list[Pattern],
    text: str,
    inquiry_type: str,
    response_kwargs: dict,
) -> OpenInputResponse | None:
    """Check patterns and return response if any match.

    This is the simplest inquiry pattern - check if any pattern matches
    and return a fixed response. Use for store hours, general menu queries, etc.

    Args:
        patterns: List of compiled regex patterns
        text: Text to search (should be lowercased)
        inquiry_type: Type for logging (e.g., "STORE HOURS")
        response_kwargs: Kwargs to pass to OpenInputResponse

    Returns:
        OpenInputResponse if matched, None otherwise

    Example:
        return simple_inquiry_check(
            STORE_HOURS_PATTERNS,
            text_lower,
            "STORE HOURS",
            {"asks_store_hours": True}
        )
    """
    if any_pattern_matches(patterns, text):
        log_inquiry(inquiry_type, text)
        return OpenInputResponse(**response_kwargs)
    return None
