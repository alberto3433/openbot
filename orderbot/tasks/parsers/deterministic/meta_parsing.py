"""
Meta / Greeting / Filler Parsing.

Contains functions for detecting greetings, gratitude, help requests,
done ordering, small talk, repeat orders, and filler-only text.
"""

import logging

from orderbot.cache import menu_cache

from ...schemas import OpenInputResponse

from ..constants import (
    GRATITUDE_PATTERNS,
    HELP_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    match_small_talk,
)

logger = logging.getLogger(__name__)


def _is_only_filler(text: str) -> bool:
    """Check if text contains only filler words after stripping order type.

    Args:
        text: Text to check

    Returns:
        True if text is empty or only contains filler words
    """
    # Remove common filler words and check if anything meaningful remains
    filler_words = {
        "and", "also", "i", "want", "would", "like", "to", "a", "an", "the", "please",
        "this", "is", "it", "that", "for", "can", "you", "be",
    }
    words = text.lower().split()
    meaningful_words = [w for w in words if w not in filler_words]
    return len(meaningful_words) == 0


def _try_parse_greeting_or_meta(text: str) -> OpenInputResponse | None:
    """Check for greetings, gratitude, help requests, done ordering, repeat order.

    Args:
        text: Cleaned user input text (after abbreviation expansion).

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for greetings (patterns loaded from database)
    if menu_cache.is_greeting(text):
        logger.debug("Deterministic parse: greeting detected")
        return OpenInputResponse(is_greeting=True)

    # Check for gratitude ("thank you", "thanks", etc.)
    if GRATITUDE_PATTERNS.match(text):
        logger.debug("Deterministic parse: gratitude detected")
        return OpenInputResponse(is_gratitude=True)

    # Check for help requests ("help", "I'm confused", "what can you do")
    if HELP_PATTERNS.match(text):
        logger.debug("Deterministic parse: help request detected")
        return OpenInputResponse(is_help_request=True)

    # Check for done ordering (patterns loaded from database)
    # Must run BEFORE small talk so "I'm good" is treated as done ordering, not social chat
    if menu_cache.is_done(text):
        logger.debug("Deterministic parse: done ordering detected")
        return OpenInputResponse(done_ordering=True)

    # Check for small talk ("how are you?", "what's up?", etc.)
    small_talk_response = match_small_talk(text)
    if small_talk_response:
        logger.debug("Deterministic parse: small talk detected")
        return OpenInputResponse(is_small_talk=True, small_talk_response=small_talk_response)

    # Check for repeat order
    if REPEAT_ORDER_PATTERNS.match(text):
        logger.debug("Deterministic parse: repeat order detected")
        return OpenInputResponse(wants_repeat_order=True)

    return None
