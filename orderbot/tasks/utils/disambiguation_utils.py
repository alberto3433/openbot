"""
Disambiguation display utilities.

This module provides display formatting utilities for disambiguation scenarios.
All matching logic has been consolidated into OptionMatcher.match_from_numbered_list().

Utilities:
- get_aliases(): Extract aliases from an option dict
- format_options_list(): Format options as a numbered list

For matching, use:
    from orderbot.tasks.utils import OptionMatcher
    matcher = OptionMatcher()
    match = matcher.match_from_numbered_list(user_input, options)

For input normalization, use:
    from orderbot.tasks.normalization import strip_filler_words
"""

from .text import format_numbered_list


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
