"""
Selection Utilities.

Utility functions and constants for selection processing.
Extracted from select_input_handler.py for reusability.
"""

import logging
from orderbot.cache.base import singularize

logger = logging.getLogger(__name__)


# Stop words to exclude when matching partial input
SELECTION_STOP_WORDS = frozenset({
    "what", "which", "do", "you", "have", "are", "the", "a", "an",
    "is", "there", "any", "some", "can", "i", "get", "want", "like",
    "options", "option", "choices", "choice", "available", "kind",
    "kinds", "type", "types", "of", "for", "with", "please", "thanks",
})


def extract_meaningful_words(user_input: str, min_length: int = 3) -> list[str]:
    """Extract meaningful words from user input, excluding stop words.

    Args:
        user_input: Raw user input string
        min_length: Minimum word length to include

    Returns:
        List of meaningful words with punctuation stripped
    """
    user_lower = user_input.lower().strip()
    return [
        word.strip("?.,!")
        for word in user_lower.split()
        if len(word.strip("?.,!")) >= min_length
        and word.strip("?.,!") not in SELECTION_STOP_WORDS
    ]


def find_partial_matches(
    words: list[str],
    options: list[dict],
) -> tuple[list[dict], str | None]:
    """Find options that partially match any of the given words.

    Args:
        words: List of words to match
        options: List of option dicts with "display_name" key

    Returns:
        Tuple of (matching_options, matched_term)
    """
    matching_options = []
    matched_term = None

    for word in words:
        singular_word = singularize(word)

        for opt in options:
            display_lower = opt["display_name"].lower()

            if singular_word in display_lower or word in display_lower:
                if opt not in matching_options:
                    matching_options.append(opt)
                    if not matched_term:
                        matched_term = singular_word

    return matching_options, matched_term


def find_numeric_options(options: list[dict]) -> set[str]:
    """Find options with numeric slugs.

    Args:
        options: List of option dicts with "slug" key

    Returns:
        Set of numeric slug strings
    """
    return {opt["slug"] for opt in options if opt["slug"].isdigit()}
