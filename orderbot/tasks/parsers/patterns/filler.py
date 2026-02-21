"""
Filler Word Patterns.

Regex patterns and utilities for detecting and stripping conversational filler:
- FILLER_WORDS_PATTERN - Leading filler words
- MID_SENTENCE_FILLER_PATTERN - Mid-sentence hesitation sounds
- strip_leading_fillers() - Remove leading fillers only
- strip_conversational_fillers() - Remove leading fillers and mid-sentence noise
- ORDERING_LANGUAGE_PATTERN - Detect ordering phrases
"""

import re

# Import consolidated hesitation fillers from constants
from ..constants import HESITATION_FILLERS, MID_SENTENCE_HESITATION_FILLERS


def _build_filler_pattern() -> re.Pattern:
    """Build regex pattern from HESITATION_FILLERS set.

    Special handling:
    - "actually" only matches with comma OR before cancel/remove words
    - "never mind" / "nevermind" only matches with comma
    - Single words match with comma or whitespace after
    - Multi-word phrases match with optional comma/whitespace after
    """
    # Special cases that need context-aware matching
    special_patterns = [
        r"actually,\s*",  # "actually," with comma is filler
        r"actually\s+(?=cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off|no\s|i\s|i')",
        r"never\s*mind,\s*",  # "never mind," when followed by another command
    ]

    # Words to exclude from generic pattern (handled specially above)
    special_words = {"actually", "never mind", "nevermind"}

    # Build patterns for remaining fillers
    generic_patterns = []
    for filler in sorted(HESITATION_FILLERS, key=len, reverse=True):
        if filler in special_words:
            continue
        # Escape regex special chars
        escaped = re.escape(filler)
        # Match with comma or whitespace after
        generic_patterns.append(rf"{escaped}[,\s]+")

    # Combine all patterns
    all_patterns = special_patterns + generic_patterns
    pattern_str = r"^(?:" + "|".join(all_patterns) + r")"

    return re.compile(pattern_str, re.IGNORECASE)


# Filler words pattern - words that add no meaning and should be stripped before parsing
FILLER_WORDS_PATTERN = _build_filler_pattern()

# Mid-sentence hesitation pattern - pure noise sounds safe to strip from anywhere
_mid_fillers = "|".join(
    re.escape(f) for f in sorted(MID_SENTENCE_HESITATION_FILLERS, key=len, reverse=True)
)
MID_SENTENCE_FILLER_PATTERN = re.compile(rf'\b(?:{_mid_fillers})\b', re.IGNORECASE)


def strip_leading_fillers(text: str) -> str:
    """Remove only leading conversational fillers (greetings, hesitations).

    Unlike strip_conversational_fillers(), this does NOT strip mid-sentence
    words like "also" or "so". Use this when you need to preserve meaningful
    mid-sentence words after removing greetings like "hi there".

    Args:
        text: User input text

    Returns:
        Text with leading conversational fillers removed
    """
    result = text
    while True:
        match = FILLER_WORDS_PATTERN.match(result)
        if match:
            result = result[match.end():].strip()
        else:
            break
    return result


def strip_conversational_fillers(text: str) -> str:
    """Remove conversational filler words from the start of user input.

    Strips hesitation markers and conversational fillers that appear at the
    beginning of user input, such as "um", "uh", "actually,", "wait,", etc.

    Unlike normalization.strip_filler_words() which removes articles and
    ordering phrases from anywhere in the text, this function specifically
    handles conversational hesitation at the start of input.

    Args:
        text: User input text

    Returns:
        Text with leading conversational fillers removed

    Examples:
        >>> strip_conversational_fillers("um, I want a bagel")
        "I want a bagel"
        >>> strip_conversational_fillers("actually, make it two")
        "make it two"
        >>> strip_conversational_fillers("wait, cancel that")
        "cancel that"
    """
    result = text
    while True:
        match = FILLER_WORDS_PATTERN.match(result)
        if match:
            result = result[match.end():].strip()
        else:
            break

    # Strip mid-sentence hesitation sounds (uh, um, er, etc.) from ANYWHERE in text.
    # These are pure noise sounds that never appear in food/menu item names.
    # Word boundaries protect against false matches in longer words (e.g., "butter").
    # e.g., "Can uh you add skim" -> "Can you add skim"
    # e.g., "I want um a bagel" -> "I want a bagel"
    result = MID_SENTENCE_FILLER_PATTERN.sub(' ', result)

    # Strip mid-sentence "so"/"also" - common fillers that never appear
    # in food names as standalone words (word boundary protects "miso", "espresso", etc.)
    # e.g., "no raisin so bagel please" -> "no raisin bagel please"
    # e.g., "also add veggie" -> "add veggie"
    result = re.sub(r'\b(?:so|also)\b', ' ', result, flags=re.IGNORECASE)
    result = re.sub(r'\s+', ' ', result).strip()

    # Strip trailing courtesy phrases like "thank you", "thanks", "and thank you"
    # This runs after mid-sentence "please" is already stripped, so:
    # "...Iced Tea please please and thank you" → "...Iced Tea and thank you" → "...Iced Tea"
    result = re.sub(
        r'(?:[,\s]+(?:and\s+)?(?:thank\s+you|thanks|thx|please))+\s*$',
        '', result, flags=re.IGNORECASE
    ).strip()

    return result


# =============================================================================
# Ordering Language Pattern
# =============================================================================

ORDERING_LANGUAGE_PATTERN = re.compile(
    r"(?:"
    r"i(?:'?d|\s*would)?\s*(?:also\s+)?(?:like|want|need|take|have|get)"
    r"|(?:can|could|may)\s+i\s+(?:also\s+)?(?:get|have)"
    r"|give\s+me"
    r"|let\s*(?:me|'s)\s*(?:also\s+)?(?:get|have)"
    r")",
    re.IGNORECASE
)
