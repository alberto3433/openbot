"""
Response Pattern Utilities.

Consolidates common response pattern checking logic used throughout
the order handling code. Provides simple helper functions for checking
if user input matches affirmative, negative, or other response patterns.
"""

from orderbot.cache import menu_cache

__all__ = [
    "is_affirmative",
    "is_negative",
    "is_skip_response",
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
    user_lower = user_input.lower().strip()
    affirmative_patterns = get_affirmative_patterns()

    # Exact match
    if user_lower in affirmative_patterns:
        return True

    # Check if input starts with an affirmative pattern
    # This handles "yes please", "yeah that's fine", etc.
    for pattern in affirmative_patterns:
        if user_lower.startswith(pattern + " ") or user_lower.startswith(pattern + ","):
            return True
        # Also check for pattern anywhere in short inputs
        if len(user_lower) < 20 and pattern in user_lower.split():
            return True

    return False


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
    user_lower = user_input.lower().strip()
    negative_patterns = get_negative_patterns()

    # Exact match
    if user_lower in negative_patterns:
        return True

    # Check if input starts with a negative pattern
    for pattern in negative_patterns:
        if user_lower.startswith(pattern + " ") or user_lower.startswith(pattern + ","):
            return True
        # Also check for pattern anywhere in short inputs
        if len(user_lower) < 20 and pattern in user_lower.split():
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
