"""
Response Pattern Utilities.

Consolidates common response pattern checking logic used throughout
the order handling code. Provides simple helper functions for checking
if user input matches affirmative, negative, or other response patterns.
"""

from orderbot.cache import menu_cache
from orderbot.tasks.utils.text import normalize_text

__all__ = [
    "is_affirmative",
    "is_negative",
    "is_skip_response",
    "has_trailing_done_signal",
    "get_affirmative_patterns",
    "get_negative_patterns",
]


def get_affirmative_patterns() -> set[str]:
    """Get the set of affirmative response patterns from the database.

    Returns:
        Set of lowercase patterns like {"yes", "yeah", "yep", "sure", ...}
    """
    return menu_cache.get_response_patterns("affirmative")


def get_negative_patterns() -> set[str]:
    """Get the set of negative response patterns from the database.

    Returns:
        Set of lowercase patterns like {"no", "nope", "nah", ...}
    """
    return menu_cache.get_response_patterns("negative")


def _matches_pattern_set(user_input: str, patterns: set[str]) -> bool:
    """Check if user input matches any pattern in a set.

    Matching strategy:
    1. Exact match against the full normalized input
    2. Prefix match: input starts with "pattern " or "pattern,"
    3. Word match (short inputs <20 chars): pattern appears as a word

    Args:
        user_input: The user's input text
        patterns: Set of lowercase patterns to match against

    Returns:
        True if any pattern matches, False otherwise
    """
    user_lower = normalize_text(user_input)

    if user_lower in patterns:
        return True

    for pattern in patterns:
        if user_lower.startswith(pattern + " ") or user_lower.startswith(pattern + ","):
            return True
        if len(user_lower) < 20 and pattern in user_lower.split():
            return True

    return False


def is_affirmative(user_input: str) -> bool:
    """Check if user input is an affirmative response.

    Handles common variations like "yes", "yeah", "yep", "sure", "ok", etc.
    Also handles phrases like "yes please" and "yeah that's fine".

    Args:
        user_input: The user's input text

    Returns:
        True if the input is affirmative, False otherwise

    Examples:
        >>> is_affirmative("yes")
        True
        >>> is_affirmative("yeah please")
        True
        >>> is_affirmative("no thanks")
        False
    """
    return _matches_pattern_set(user_input, get_affirmative_patterns())


def is_negative(user_input: str) -> bool:
    """Check if user input is a negative response.

    Handles common variations like "no", "nope", "nah", "no thanks", etc.

    Args:
        user_input: The user's input text

    Returns:
        True if the input is negative, False otherwise

    Examples:
        >>> is_negative("no")
        True
        >>> is_negative("no thanks")
        True
        >>> is_negative("yes please")
        False
    """
    return _matches_pattern_set(user_input, get_negative_patterns())


def has_trailing_done_signal(text: str) -> bool:
    """Check if text ends with a 'done' signal phrase (e.g., 'nothing else', 'that's it').

    Tests the last 1-5 words of the input against menu_cache.is_done(),
    which uses DB-stored response_pattern entries (pattern_type='done').

    Args:
        text: The user's input text

    Returns:
        True if the text ends with a done signal, False otherwise
    """
    words = normalize_text(text).split()
    if not words:
        return False
    for n in range(1, min(6, len(words) + 1)):
        tail = " ".join(words[-n:])
        if menu_cache.is_done(tail):
            return True
    return False


def is_skip_response(user_input: str) -> bool:
    """Check if user input indicates they want to skip something.

    This is typically used for optional questions where the user can
    decline with "no", "none", "skip", "no thanks", etc.

    Args:
        user_input: The user's input text

    Returns:
        True if the input indicates skipping, False otherwise
    """
    # Skip responses are essentially negative responses
    return is_negative(user_input)
