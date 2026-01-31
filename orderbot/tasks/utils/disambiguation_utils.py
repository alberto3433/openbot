"""
Shared utilities for disambiguation matching.

Provides common matching logic used by both item disambiguation
(selecting between menu items) and config disambiguation (selecting
between attribute options).
"""

import logging

from .text import format_numbered_list

logger = logging.getLogger(__name__)

# Selection patterns for ordinal/number matching
# Format: (pattern, 0-based index)
ORDINAL_PATTERNS = [
    ("first", 0), ("1", 0), ("one", 0),
    ("second", 1), ("2", 1), ("two", 1),
    ("third", 2), ("3", 2), ("three", 2),
    ("fourth", 3), ("4", 3), ("four", 3),
    ("fifth", 4), ("5", 4), ("five", 4),
    ("sixth", 5), ("6", 5), ("six", 5),
]


def normalize_input(user_input: str) -> str:
    """Normalize user input by removing common filler words.

    Args:
        user_input: Raw user input

    Returns:
        Cleaned, lowercased input
    """
    input_lower = user_input.lower().strip()
    # Remove common filler words
    for filler in ["the ", "please", "i want ", "i'll take ", "just "]:
        input_lower = input_lower.replace(filler, "").strip()
    return input_lower


def match_by_ordinal(user_input: str, options: list[dict], name_key: str = "name") -> dict | None:
    """Match user input to an option by ordinal/number.

    Handles inputs like "first", "1", "second one", etc.

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts
        name_key: Key to use for option name (default: "name", could be "display_name")

    Returns:
        Matched option dict or None
    """
    # Reject negative numbers
    if user_input.startswith('-') or user_input.startswith('−'):
        return None

    for pattern, idx in ORDINAL_PATTERNS:
        if pattern in user_input or user_input == f"{pattern} one":
            if idx < len(options):
                logger.debug(
                    "DISAMBIGUATION: Matched option %d ('%s') by ordinal '%s'",
                    idx + 1, options[idx].get(name_key, ""), pattern
                )
                return options[idx]
            else:
                logger.debug(
                    "DISAMBIGUATION: Ordinal '%s' out of range (only %d options)",
                    pattern, len(options)
                )
                return None
    return None


def match_by_name_exact(
    user_input: str,
    options: list[dict],
    name_key: str = "name",
    slug_key: str = "slug",
) -> dict | None:
    """Match user input to an option by exact name match.

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts
        name_key: Key for display name
        slug_key: Key for slug

    Returns:
        Matched option dict or None
    """
    for opt in options:
        # Exact match on name
        name = opt.get(name_key, "").lower()
        if name == user_input:
            return opt

        # Exact match on slug (with underscores as spaces)
        slug = opt.get(slug_key, "").replace("_", " ")
        if slug == user_input:
            return opt

    return None


def match_by_alias_exact(user_input: str, options: list[dict]) -> dict | None:
    """Match user input to an option by exact alias match.

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts with optional "aliases" field

    Returns:
        Matched option dict or None
    """
    for opt in options:
        for alias in get_aliases(opt):
            if alias.lower() == user_input:
                return opt
    return None


def match_by_name_in_input(
    user_input: str,
    options: list[dict],
    name_key: str = "name",
) -> dict | None:
    """Match if option name appears in user input.

    Handles cases like "black forest ham please" -> "Black Forest Ham"

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts
        name_key: Key for display name

    Returns:
        Matched option dict or None
    """
    for opt in options:
        name = opt.get(name_key, "").lower()
        if name and name in user_input:
            return opt
    return None


def match_by_input_in_name(
    user_input: str,
    options: list[dict],
    name_key: str = "name",
    min_length: int = 3,
) -> dict | None:
    """Match if user input appears in option name.

    Handles partial matches like "classic" -> "The Classic BEC"

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts
        name_key: Key for display name
        min_length: Minimum input length for matching

    Returns:
        Matched option dict or None
    """
    if len(user_input) < min_length:
        return None

    for opt in options:
        name = opt.get(name_key, "").lower()
        if user_input in name:
            return opt

    return None


def match_by_word(
    user_input: str,
    options: list[dict],
    name_key: str = "name",
    min_word_length: int = 3,
) -> dict | None:
    """Match if any word in user input appears in option name.

    Args:
        user_input: Normalized user input (lowercase)
        options: List of option dicts
        name_key: Key for display name
        min_word_length: Minimum word length for matching

    Returns:
        Matched option dict or None
    """
    for word in user_input.split():
        if len(word) < min_word_length:
            continue
        for opt in options:
            name = opt.get(name_key, "").lower()
            if word in name:
                return opt
    return None


def get_aliases(opt: dict) -> list[str]:
    """Extract aliases from an option dict.

    Handles both pipe-separated and comma-separated formats.

    Args:
        opt: Option dict with optional "aliases" field

    Returns:
        List of alias strings
    """
    aliases_raw = opt.get("aliases", [])
    if isinstance(aliases_raw, str):
        if "|" in aliases_raw:
            return [a.strip() for a in aliases_raw.split("|") if a.strip()]
        return [a.strip() for a in aliases_raw.split(",") if a.strip()]
    return aliases_raw or []


def format_options_list(
    options: list[dict],
    name_key: str = "name",
    show_prices: bool = False,
    price_key: str = "base_price",
) -> str:
    """Format options as a numbered list.

    Args:
        options: List of option dicts
        name_key: Key for display name
        show_prices: Whether to show prices
        price_key: Key for price field

    Returns:
        Formatted string with numbered options
    """
    return format_numbered_list(
        options,
        name_key=name_key,
        show_prices=show_prices,
        price_key=price_key,
    )
