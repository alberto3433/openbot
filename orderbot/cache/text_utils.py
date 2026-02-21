"""
Text normalization utilities for the cache layer.

This module contains the canonical ``normalize_text`` function and the
heavier ``normalize_for_matching`` used during menu-item matching.
"""

import re


# Pattern for abbreviation periods (Dr., Mr., Mrs., Ms., St.)
_ABBREV_PERIOD_PATTERN = re.compile(r'\b(dr|mr|mrs|ms|st)\.', re.IGNORECASE)

# Smart quote to straight quote mapping
# Use Unicode ordinals to avoid encoding issues
_SMART_QUOTE_MAP = str.maketrans({
    '\u2018': "'",  # Left single quotation mark
    '\u2019': "'",  # Right single quotation mark
    '\u201C': '"',  # Left double quotation mark
    '\u201D': '"',  # Right double quotation mark
})


def normalize_text(text: str | None) -> str:
    """Normalize text for comparison by lowercasing and stripping whitespace.

    This is the canonical definition used by both cache and task modules.
    Task modules import via ``from orderbot.tasks.utils.text import normalize_text``
    which re-exports this function.

    Args:
        text: The text to normalize, or None.

    Returns:
        Lowercased and whitespace-stripped text (empty string for None).

    Examples:
        >>> normalize_text("  Bacon  ")
        'bacon'
        >>> normalize_text(None)
        ''
    """
    return (text or "").lower().strip()


def normalize_for_matching(text: str) -> str:
    """Normalize text for matching by standardizing special characters.

    Used for menu item matching where user input like "dr brown" should
    match database values like "Dr. Brown's".

    Transforms applied:
    - Lowercase and strip whitespace
    - Normalize smart quotes to straight quotes
    - Remove periods after common abbreviations (Dr., Mr., Mrs., Ms., St.)
    - Replace & with ' and '
    - Replace hyphens with spaces
    - Remove possessive 's (e.g., "Brown's" -> "Brown")
    - Remove remaining apostrophes (contractions)
    - Collapse multiple spaces to single space

    Args:
        text: The text to normalize.

    Returns:
        Normalized text for matching.

    Examples:
        >>> normalize_for_matching("Dr. Brown's")
        'dr brown'
        >>> normalize_for_matching("dr brown")
        'dr brown'
        >>> normalize_for_matching("Bacon & Eggs")
        'bacon and eggs'
        >>> normalize_for_matching("cream-cheese")
        'cream cheese'
        >>> normalize_for_matching("St. Mark's")
        'st mark'
    """
    text = text.lower().strip()
    text = text.translate(_SMART_QUOTE_MAP)
    text = _ABBREV_PERIOD_PATTERN.sub(r'\1', text)
    text = text.replace('&', ' and ')
    text = text.replace('-', ' ')
    # Remove possessive 's at word boundaries (e.g., "Brown's" -> "Brown")
    text = re.sub(r"'s\b", '', text)
    # Remove remaining apostrophes (contractions like "don't" -> "dont")
    text = text.replace("'", '')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
