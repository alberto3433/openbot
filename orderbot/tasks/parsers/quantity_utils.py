"""
Quantity extraction utilities.

This module provides a single source of truth for converting word quantities to numbers
and extracting quantities from user input. Consolidates duplicate implementations from:
- constants.py (WORD_TO_NUM, extract_quantity)
- deterministic.py (_extract_quantity, _extract_leading_quantity)
- taking_items_handler.py (_extract_quantity_from_input)
- menu_item_config_handler.py (_extract_quantity_from_input)
- state_machine.py, checkout_handler.py (inline word_to_num dicts)
"""

import re

# =============================================================================
# Word to Number Mapping
# =============================================================================

# Comprehensive mapping from word quantities to numbers
# This is the single source of truth - import this instead of defining inline dicts
WORD_TO_NUM: dict[str, int] = {
    # Single
    "a": 1, "an": 1, "one": 1, "single": 1,
    # Two
    "two": 2, "couple": 2, "a couple": 2, "a couple of": 2, "couple of": 2, "double": 2,
    "a few": 2, "few": 2,
    # Three
    "three": 3, "triple": 3,
    # Four
    "four": 4, "quad": 4, "quadruple": 4,
    # Five through twelve
    "five": 5,
    "six": 6, "half dozen": 6, "half a dozen": 6, "a half dozen": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12, "dozen": 12, "a dozen": 12,
}

# Subset for basic number words (useful for pattern matching in specific contexts)
BASIC_WORD_TO_NUM: dict[str, int] = {
    "one": 1, "single": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "double": 2, "triple": 3, "quad": 4, "quadruple": 4,
}

# Words that modify quantity but aren't ingredients themselves.
# Used to filter these from "unmatched" lists in fallback parsing.
QUANTITY_MODIFIER_WORDS: frozenset[str] = frozenset({
    "more", "extra", "double", "triple", "another", "additional", "few", "couple"
})

# Reverse mapping: number to word (for display purposes)
NUM_TO_WORD: dict[int, str] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve",
}

# Maximum quantity allowed per individual modifier (e.g., sugars, syrups)
MAX_MODIFIER_QUANTITY: int = 10

# ── Regex fragments derived from the mappings above ──────────────────
# Use these in regex patterns instead of hand-writing word lists.

# Basic number words: one|two|...|ten|single|double|triple|quad|quadruple
_BASIC_WORDS = sorted(BASIC_WORD_TO_NUM.keys(), key=len, reverse=True)
QTY_WORDS_RE: str = "|".join(re.escape(w) for w in _BASIC_WORDS)

# Extended: also includes eleven, twelve, dozen, etc.
_EXTENDED_WORDS = sorted(
    (k for k in WORD_TO_NUM if " " not in k),  # exclude multi-word like "a dozen"
    key=len,
    reverse=True,
)
QTY_WORDS_EXTENDED_RE: str = "|".join(re.escape(w) for w in _EXTENDED_WORDS)


# =============================================================================
# Quantity Extraction Functions
# =============================================================================

def extract_quantity_word(text: str) -> int | None:
    """Extract quantity from a word or phrase like 'three', 'a dozen', 'couple of'.

    This handles the full range of quantity expressions without context
    about what the quantity is for.

    Args:
        text: Text containing a quantity word (e.g., "three", "a dozen", "couple")

    Returns:
        Integer quantity if recognized, None otherwise.

    Examples:
        >>> extract_quantity_word("three")
        3
        >>> extract_quantity_word("a dozen")
        12
        >>> extract_quantity_word("couple of")
        2
        >>> extract_quantity_word("hello")
        None
    """
    text = text.lower().strip()
    # Remove trailing "of" for phrases like "couple of"
    text = re.sub(r"\s+of$", "", text)
    # Normalize whitespace for compound expressions like "a  dozen" -> "a dozen"
    text = re.sub(r"\s+", " ", text)

    if text.isdigit():
        return int(text)

    return WORD_TO_NUM.get(text)


def extract_leading_quantity(text: str) -> tuple[int | None, str]:
    """Extract leading quantity from text and return remaining text.

    Handles both numeric ("2 bagels") and word quantities ("three lattes").

    Args:
        text: Input text like "2 bagels", "a coffee", "three lattes"

    Returns:
        (quantity, remaining_text) - quantity and text with quantity removed.
        If no quantity found, returns (None, original_text).

    Examples:
        >>> extract_leading_quantity("2 bagels")
        (2, "bagels")
        >>> extract_leading_quantity("a coffee")
        (1, "coffee")
        >>> extract_leading_quantity("three lattes")
        (3, "lattes")
        >>> extract_leading_quantity("coffee")
        (None, "coffee")
        >>> extract_leading_quantity("2x bagels")
        (2, "bagels")
    """
    text = text.strip()
    text_lower = text.lower()

    # Check for numeric prefix (with optional 'x' suffix like "2x")
    match = re.match(r'^(\d+)x?\s+', text)
    if match:
        return int(match.group(1)), text[match.end():].strip()

    # Check for quantity words - sorted by length descending to match longer phrases first
    for word, qty in sorted(WORD_TO_NUM.items(), key=lambda x: -len(x[0])):
        if text_lower.startswith(word + " "):
            return qty, text[len(word):].strip()
        if text_lower == word:
            return qty, ""

    return None, text


def extract_quantity_for_pattern(user_input: str, pattern: str) -> int:
    """Extract quantity from user input for a given pattern.

    Handles both numeric ("2 vanilla") and word ("two vanilla") quantities
    appearing before a modifier pattern. Also treats "extra" as quantity=2.

    Args:
        user_input: The user's input string (will be lowercased)
        pattern: The pattern to look for (e.g., "vanilla", "shot")

    Returns:
        The extracted quantity, defaulting to 1 if not found.

    Examples:
        >>> extract_quantity_for_pattern("2 vanilla syrups", "vanilla")
        2
        >>> extract_quantity_for_pattern("triple espresso", "espresso")
        3
        >>> extract_quantity_for_pattern("extra bacon", "bacon")
        2
        >>> extract_quantity_for_pattern("add vanilla", "vanilla")
        1
    """
    user_input = user_input.lower()
    escaped_pattern = re.escape(pattern)

    # Try digit match first: "2 vanilla syrups"
    digit_match = re.search(rf'(\d+)\s*{escaped_pattern}s?', user_input)
    if digit_match:
        return int(digit_match.group(1))

    # Try word match: "two vanilla syrups", "double shot", "triple espresso", "extra bacon"
    # Note: "extra" is treated as quantity=2 for modifiers
    word_pattern = (
        rf'({QTY_WORDS_RE}|extra)\s+' + escaped_pattern + r's?'
    )
    word_match = re.search(word_pattern, user_input)
    if word_match:
        word = word_match.group(1).lower()
        if word == "extra":
            return 2
        return BASIC_WORD_TO_NUM.get(word, 1)

    return 1


def extract_additive_quantity(user_input: str, pattern: str) -> tuple[int, bool]:
    """Extract quantity and detect if it's an additive request.

    Additive patterns indicate adding to existing quantity:
    - "another shot" = +1 (additive)
    - "one more shot" = +1 (additive)
    - "2 more shots" = +2 (additive)

    Non-additive patterns set absolute quantity:
    - "double shot" = 2 (absolute)
    - "two shots" = 2 (absolute)

    Args:
        user_input: The user's input string (will be lowercased)
        pattern: The pattern to look for (e.g., "shot")

    Returns:
        Tuple of (quantity, is_additive).

    Examples:
        >>> extract_additive_quantity("another shot", "shot")
        (1, True)
        >>> extract_additive_quantity("one more shot", "shot")
        (1, True)
        >>> extract_additive_quantity("2 more shots", "shot")
        (2, True)
        >>> extract_additive_quantity("double shot", "shot")
        (2, False)
    """
    user_lower = user_input.lower()
    escaped_pattern = re.escape(pattern)

    # Check for "another X" pattern
    another_match = re.search(rf'another\s+{escaped_pattern}s?', user_lower)
    if another_match:
        return 1, True

    # Check for "N more X" or "more X" patterns
    # "one more shot", "2 more shots", "a few more shots"
    more_match = re.search(
        rf'(one|two|three|four|five|\d+|a few|a couple(?: of)?|another)?\s*more\s+{escaped_pattern}s?',
        user_lower
    )
    if more_match:
        qty_word = more_match.group(1)
        if qty_word:
            qty_word = qty_word.lower().strip()
            if qty_word.isdigit():
                return int(qty_word), True
            elif qty_word == "another":
                return 1, True
            else:
                return WORD_TO_NUM.get(qty_word, 1), True
        return 1, True  # Just "more shot" = 1 more

    # Not an additive pattern - use regular extraction
    qty = extract_quantity_for_pattern(user_input, pattern)
    return qty, False


def parse_make_it_n_quantity(num_str: str) -> int | None:
    """Parse quantity from 'make it N' style expressions.

    Handles both numeric strings ("2", "10") and word strings ("two", "three").
    Used for expressions like "make it 2", "make it three", etc.

    Args:
        num_str: The extracted number string from the regex match

    Returns:
        Integer quantity (2+) if valid, None otherwise.
        Returns None for quantities less than 2 since "make it 1" doesn't make sense.

    Examples:
        >>> parse_make_it_n_quantity("2")
        2
        >>> parse_make_it_n_quantity("three")
        3
        >>> parse_make_it_n_quantity("1")
        None
        >>> parse_make_it_n_quantity("invalid")
        None
    """
    num_str = num_str.lower().strip()

    if num_str.isdigit():
        qty = int(num_str)
    else:
        qty = BASIC_WORD_TO_NUM.get(num_str, 0)

    # Only return for quantities >= 2 (make it 1 doesn't make sense)
    return qty if qty >= 2 else None


def extract_make_it_n_target(match: re.Match) -> int | None:
    """Extract target quantity from a MAKE_IT_N_PATTERN match.

    Scans all capture groups for the first non-None group and parses it
    as a quantity via parse_make_it_n_quantity.

    Args:
        match: A regex match object from MAKE_IT_N_PATTERN.

    Returns:
        Target quantity (>= 2) if found, None otherwise.
    """
    for i in range(1, 15):
        try:
            group = match.group(i)
            if group:
                return parse_make_it_n_quantity(group.lower())
        except IndexError:
            break
    return None


def parse_numeric_input(user_input: str) -> int | None:
    """Parse numeric value from user input.

    Handles both raw digits and word numbers. Used for attributes with
    numeric option slugs (e.g., shots with options "1", "2", "3", "4").

    Args:
        user_input: User's input string (e.g., "3", "three", "triple")

    Returns:
        Integer value if found, None otherwise.

    Examples:
        >>> parse_numeric_input("3")
        3
        >>> parse_numeric_input("three shots")
        3
        >>> parse_numeric_input("triple")
        3
        >>> parse_numeric_input("hello")
        None
    """
    user_lower = user_input.lower().strip()

    # Try raw digit match first: "3", "2 shots", etc.
    digit_match = re.search(r'\b(\d+)\b', user_lower)
    if digit_match:
        return int(digit_match.group(1))

    # Try word number match: "three", "triple", etc.
    # Sort by length descending to match longer phrases first
    for word, num in sorted(WORD_TO_NUM.items(), key=lambda x: -len(x[0])):
        if word in user_lower.split():
            return num

    return None


def extract_modifier_quantity(
    prefix_quantity: int | None,
    raw_user_input: str | None,
    modifier_pattern: str,
    modifier_text: str | None = None,
) -> int:
    """Extract quantity for a modifier using 3-level fallback.

    This is the standard approach for determining modifier quantity:
    1. Use quantity from modifier prefix (e.g., "2 vanilla" -> 2)
    2. Search full user input for pattern match (e.g., "add two vanilla syrups" -> 2)
    3. Check for "(extra)" qualifier in modifier text (e.g., "bacon (extra)" -> 2)

    Args:
        prefix_quantity: Quantity extracted from modifier prefix, or None
        raw_user_input: The full user input string for pattern matching
        modifier_pattern: The modifier pattern to search for (e.g., "vanilla")
        modifier_text: Optional modifier text to check for "(extra)" qualifier

    Returns:
        The extracted quantity, defaulting to 1 if not found.

    Examples:
        >>> extract_modifier_quantity(2, "add 2 vanilla", "vanilla")
        2
        >>> extract_modifier_quantity(None, "add two vanilla syrups", "vanilla")
        2
        >>> extract_modifier_quantity(None, "add bacon", "bacon", "bacon (extra)")
        2
        >>> extract_modifier_quantity(None, "add bacon", "bacon")
        1
    """
    # Level 1: Use prefix quantity if provided
    if prefix_quantity and prefix_quantity > 0:
        return prefix_quantity

    # Level 2: Search full user input for pattern
    if raw_user_input:
        pattern_qty = extract_quantity_for_pattern(raw_user_input, modifier_pattern)
        if pattern_qty > 1:
            return pattern_qty

    # Level 3: Check for "(extra)" qualifier
    if modifier_text and "(extra)" in modifier_text.lower():
        return 2

    return 1
