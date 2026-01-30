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
    "a": 1, "an": 1, "one": 1,
    # Two
    "two": 2, "couple": 2, "a couple": 2, "a couple of": 2, "couple of": 2, "double": 2,
    # Three
    "three": 3, "a few": 3, "few": 3, "triple": 3,
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
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "double": 2, "triple": 3, "quad": 4, "quadruple": 4,
}


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
        r'(one|two|three|four|five|six|seven|eight|nine|ten|'
        r'double|triple|quad|quadruple|extra)\s+' + escaped_pattern + r's?'
    )
    word_match = re.search(word_pattern, user_input)
    if word_match:
        word = word_match.group(1).lower()
        if word == "extra":
            return 2
        return BASIC_WORD_TO_NUM.get(word, 1)

    return 1


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

    Scans capture groups 1-7 for the first non-None group and parses it
    as a quantity via parse_make_it_n_quantity.

    Args:
        match: A regex match object from MAKE_IT_N_PATTERN.

    Returns:
        Target quantity (>= 2) if found, None otherwise.
    """
    for i in range(1, 8):
        group = match.group(i)
        if group:
            return parse_make_it_n_quantity(group.lower())
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
