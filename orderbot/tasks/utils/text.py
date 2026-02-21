"""
Text formatting utilities for human-readable output.
"""

import re

from orderbot.cache.base import normalize_text  # noqa: F401 — canonical def in cache/base, re-exported here

# =============================================================================
# Unified Ordinal Definitions
# =============================================================================
# Single source of truth for ordinal mappings used across the codebase.

# Base ordinal words
_BASE_ORDINALS = {
    "first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4, "sixth": 5,
}

# Numeric representations
_NUMERIC = {"1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5}

# Suffixed ordinals (1st, 2nd, etc.)
_SUFFIXED = {"1st": 0, "2nd": 1, "3rd": 2, "4th": 3, "5th": 4}

# Number words
_WORDS = {"one": 0, "two": 1, "three": 2, "four": 3, "five": 4, "six": 5}

# For dict lookups (selection parsing) - includes "the first", "the first one", etc.
ORDINAL_MAP = {
    **_BASE_ORDINALS,
    **_SUFFIXED,
    **_NUMERIC,
    **{f"the {k}": v for k, v in _BASE_ORDINALS.items()},
    **{f"the {k} one": v for k, v in _BASE_ORDINALS.items()},
}

# For pattern matching (list selection) - tuples sorted longest first
# Used by OptionMatcher._match_by_ordinal()
ORDINAL_PATTERNS: list[tuple[str, int]] = sorted(
    [(k, v) for d in [_BASE_ORDINALS, _NUMERIC, _WORDS] for k, v in d.items()],
    key=lambda x: -len(x[0])  # Longest first to match "second" before "one"
)


def parse_selection(text: str, max_options: int) -> int | None:
    """Parse user's selection from a numbered list.

    Handles direct numbers ("1", "2") and ordinal words ("first", "the second one").

    Args:
        text: User's response text (will be lowercased and stripped).
        max_options: Maximum number of valid options (1-indexed).

    Returns:
        0-based index of the selection, or None if not parseable.

    Examples:
        >>> parse_selection("1", 5)
        0
        >>> parse_selection("first", 5)
        0
        >>> parse_selection("the second one", 3)
        1
        >>> parse_selection("10", 5)  # Out of range
        None
        >>> parse_selection("hello", 5)  # Not a selection
        None
    """
    text = normalize_text(text)

    # Direct number
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < max_options:
            return idx
        return None

    # Ordinal words
    for key, idx in ORDINAL_MAP.items():
        if text == key or text.startswith(key + " "):
            if idx < max_options:
                return idx

    return None


def format_paginated_list(
    items: list[str],
    limit: int,
    offset: int = 0,
) -> tuple[str, int]:
    """Format a paginated list with "and X more" suffix.

    Args:
        items: Full list of item names.
        limit: Maximum items to show in this batch.
        offset: Starting offset (for "show more" pagination).

    Returns:
        Tuple of (formatted_string, new_offset):
        - If all items shown, new_offset is 0 (signals complete).
        - Otherwise, new_offset is where to continue from.

    Examples:
        >>> format_paginated_list(["A", "B", "C"], limit=2)
        ('A, B, and 1 more', 2)
        >>> format_paginated_list(["A", "B", "C"], limit=5)
        ('A, B, and C', 0)
        >>> format_paginated_list(["A", "B", "C", "D", "E"], limit=2, offset=2)
        ('C, D, and 1 more', 4)
    """
    batch = items[offset:offset + limit]
    remaining = len(items) - offset - len(batch)

    if remaining > 0:
        formatted = ", ".join(batch) + f", and {remaining} more"
        return formatted, offset + len(batch)
    else:
        return format_english_list(batch), 0


def number_to_word(n: int) -> str:
    """Convert small integers (1-10) to words for natural language output.

    Args:
        n: Integer to convert (numbers > 10 return string representation)

    Returns:
        Word form for 1-10 ("one", "two", etc.), or str(n) for larger numbers.

    Examples:
        >>> number_to_word(1)
        'one'
        >>> number_to_word(5)
        'five'
        >>> number_to_word(15)
        '15'
    """
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    }
    return words.get(n, str(n))


def format_english_list(items: list[str], conjunction: str = "and") -> str:
    """Format a list of strings as an English list with Oxford comma.

    Args:
        items: List of strings to format.
        conjunction: Word to use before the last item ("and" or "or").

    Returns:
        Formatted string, e.g. "a, b, and c".

    Examples:
        >>> format_english_list([])
        ''
        >>> format_english_list(["apples"])
        'apples'
        >>> format_english_list(["apples", "bananas"])
        'apples and bananas'
        >>> format_english_list(["apples", "bananas", "cherries"])
        'apples, bananas, and cherries'
        >>> format_english_list(["a", "b"], conjunction="or")
        'a or b'
    """
    if len(items) == 0:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} {items[-1]}"


def format_display_list(
    items: list[dict],
    key: str = "display_name",
    conjunction: str = "or",
) -> str:
    """Format a list of dicts for display.

    Extracts a specific key from each dict and formats as English list.

    Args:
        items: List of dicts containing the display values
        key: Key to extract from each dict (default: "display_name")
        conjunction: Word to join items (default: "or")

    Returns:
        Formatted string like "A, B, or C"

    Examples:
        >>> format_display_list([{"display_name": "Apple"}, {"display_name": "Banana"}])
        'Apple or Banana'
    """
    names = [item.get(key, "") for item in items if item.get(key)]
    return format_english_list(names, conjunction=conjunction)


def format_numbered_list(
    items: list[dict] | list[str],
    name_key: str = "name",
    show_prices: bool = False,
    price_key: str = "base_price",
) -> str:
    """Format items as a numbered list.

    Args:
        items: List of dicts with name/price keys, or list of strings.
        name_key: Key for display name in dicts (ignored if items are strings).
        show_prices: Whether to show prices after names.
        price_key: Key for price field in dicts.

    Returns:
        Formatted string with numbered options, e.g.:
        "1. Apple
         2. Banana ($1.50)
         3. Cherry"

    Examples:
        >>> format_numbered_list(["Apple", "Banana"])
        '1. Apple\\n2. Banana'
        >>> format_numbered_list([{"name": "Apple"}, {"name": "Banana"}])
        '1. Apple\\n2. Banana'
        >>> format_numbered_list([{"name": "Latte", "base_price": 4.50}], show_prices=True)
        '1. Latte ($4.50)'
    """
    lines = []
    for i, item in enumerate(items, 1):
        # Handle both string lists and dict lists
        if isinstance(item, str):
            name = item
            price = 0
        else:
            name = item.get(name_key, "Unknown")
            price = item.get(price_key, 0) if show_prices else 0

        if show_prices and price > 0:
            lines.append(f"{i}. {name} (${price:.2f})")
        else:
            lines.append(f"{i}. {name}")
    return "\n".join(lines)


def strip_leading_article(text: str) -> str:
    """Remove leading 'the ' from text if present.

    Common pattern used when normalizing user input for modifier/item matching.
    The article 'the' is often used by customers but not part of item names.

    Args:
        text: The text to process (should already be lowercase/stripped).

    Returns:
        Text with leading 'the ' removed, or original text if not present.

    Examples:
        >>> strip_leading_article("the bacon")
        'bacon'
        >>> strip_leading_article("bacon")
        'bacon'
        >>> strip_leading_article("theater")  # Not stripped - 'the' is part of word
        'theater'
    """
    if text.startswith("the "):
        return text[4:]
    return text


def word_boundary_match(needle: str, haystack: str, case_insensitive: bool = False) -> bool:
    """Check if needle appears as a whole word/phrase in haystack using word boundaries.

    Args:
        needle: The word/phrase to search for (will be regex-escaped).
        haystack: The text to search in.
        case_insensitive: If True, match regardless of case.

    Returns:
        True if needle appears with word boundaries in haystack.

    Examples:
        >>> word_boundary_match("ham", "ham and cheese")
        True
        >>> word_boundary_match("ham", "graham cracker")
        False
        >>> word_boundary_match("tea", "Hot Tea", case_insensitive=True)
        True
    """
    flags = re.IGNORECASE if case_insensitive else 0
    return bool(re.search(rf'\b{re.escape(needle)}\b', haystack, flags))


def find_first_word_boundary_match(
    text: str,
    candidates: list[str] | set[str],
    normalize_func=None,
) -> str | None:
    """Find the first matching candidate using word-boundary matching.

    Candidates are sorted by length (longest first) to prevent partial matches
    from taking precedence (e.g., "egg" matching before "egg whites").

    Args:
        text: The text to search in (should be lowercase).
        candidates: List/set of candidate strings to match against.
        normalize_func: Optional function to normalize the matched value.
                       If provided, returns normalize_func(match) instead of match.

    Returns:
        The first matching candidate (optionally normalized), or None if no match.

    Examples:
        >>> find_first_word_boundary_match("add vanilla syrup", ["vanilla", "chocolate"])
        'vanilla'
        >>> find_first_word_boundary_match("veggie omelette", ["egg", "veggie"])
        'veggie'  # Not 'egg' because word boundary prevents matching 'egg' in 'veggie'
    """
    for candidate in sorted(candidates, key=len, reverse=True):
        if word_boundary_match(candidate, text):
            if normalize_func:
                return normalize_func(candidate)
            return candidate
    return None


_WHAT_WHICH_RE = re.compile(r'(?:what|which)\s+(.+?)\s*\?', re.IGNORECASE)
_HOW_QUESTION_RE = re.compile(
    r'how\s+(?:would|do)\s+you\s+(?:like|want)\s+(?:your\s+)?(.+?)\s*\?',
    re.IGNORECASE,
)


def extract_question_phrase(question_text: str) -> str | None:
    """Extract the noun phrase from a question.

    Handles 'what/which X?' and 'how would you like (your) X?' patterns.

    Args:
        question_text: The question to extract a phrase from.

    Returns:
        The extracted noun phrase, or None if no match.

    Examples:
        >>> extract_question_phrase("What type of tea?")
        'type of tea'
        >>> extract_question_phrase("How would you like your eggs?")
        'eggs'
        >>> extract_question_phrase("Would you like it toasted?")
    """
    m = _WHAT_WHICH_RE.search(question_text)
    if m:
        return m.group(1).strip()
    m = _HOW_QUESTION_RE.search(question_text)
    return m.group(1).strip() if m else None
