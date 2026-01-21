"""
Unified attribute value normalization for order handling.

This module consolidates normalization logic that was previously duplicated across:
- modifier_change_handler._normalize_attribute_value()
- menu_item_config_handler._normalize_for_matching()

All handlers should use these functions for consistent value resolution.
"""
from __future__ import annotations

import re

from orderbot.menu_data_cache import menu_cache, singularize


# Negation patterns that indicate user wants to remove/clear an attribute
NEGATION_PATTERNS = frozenset({
    "no", "none", "nothing", "without", "remove", "black",
    "skip", "pass", "na", "n/a", "plain", "regular",
})


# Shot quantity normalizations (coffee domain, but data-driven through aliases)
SHOT_NORMALIZATIONS: dict[str, str] = {
    "1": "single", "one": "single",
    "2": "double", "two": "double",
    "3": "triple", "three": "triple",
    "4": "quad", "four": "quad",
}


def normalize_for_option_match(text: str) -> str:
    """
    Normalize user input for option matching.

    Handles common patterns users type when ordering:
    - Shot quantities: "two shots" → "double", "3 shots" → "triple"
    - Leading quantities: "2 scrambled eggs" → "scrambled eggs"
    - Plural forms: "scrambled eggs" → "scrambled egg"

    Args:
        text: Raw user input

    Returns:
        Normalized text suitable for option matching
    """
    text = text.lower().strip()

    # Handle "X shot(s)" pattern FIRST before stripping quantities:
    # "two shots" → "double", "3 shots" → "triple", "one shot" → "single"
    shot_pattern = re.match(r'^(\w+)\s+shots?$', text)
    if shot_pattern:
        num_word = shot_pattern.group(1)
        if num_word in SHOT_NORMALIZATIONS:
            return SHOT_NORMALIZATIONS[num_word]

    # Strip leading quantity patterns (numbers like "2", "2x", words like "two")
    text = re.sub(r'^(\d+x?\s+)', '', text)  # "2 ", "2x ", "10 "
    text = re.sub(
        r'^(one|two|three|four|five|six|seven|eight|nine|ten)\s+',
        '', text, flags=re.IGNORECASE
    )
    text = re.sub(r'^(a|an)\s+', '', text)  # "a scrambled egg", "an egg"

    # Normalize plurals to singular for matching
    # "eggs" → "egg", "bagels" → "bagel", "syrups" → "syrup", etc.
    words = text.split()
    text = " ".join(singularize(word) for word in words)

    # Also handle exact matches: "two" → "double", "3" → "triple"
    if text in SHOT_NORMALIZATIONS:
        text = SHOT_NORMALIZATIONS[text]

    return text.strip()


def resolve_to_canonical(
    attr_slug: str,
    value: str,
    item_type_slug: str | None = None,
) -> str | bool | None:
    """
    Resolve an attribute value to its canonical form using data-driven option resolution.

    Uses menu_cache.resolve_option_by_alias() to find canonical option values
    from the database. Handles special cases:
    - Negation patterns ("no", "none", "black") return None for nullable attrs
    - Boolean attributes return True/False based on option match
    - Falls back to cleaned input if no option match found

    Args:
        attr_slug: The attribute slug (e.g., "size", "milk", "bread")
        value: The raw user input value
        item_type_slug: Optional item type for context-specific resolution

    Returns:
        Normalized value: canonical option slug, boolean, None, or cleaned input
    """
    value_clean = value.lower().strip()

    # Check for negation patterns - user wants to remove/clear the attribute
    first_word = value_clean.split()[0] if value_clean else ""
    if first_word in NEGATION_PATTERNS:
        return None

    # Get attribute info to check input_type
    attr_info = _get_attribute_info(attr_slug, item_type_slug)

    # Handle boolean attributes (data-driven via options with "true"/"false" slugs)
    input_type = attr_info.get("input_type") if attr_info else None
    if input_type == "boolean":
        # Boolean attributes have options with slugs "true" and "false"
        # Aliases like "decaf", "yes" → "true" and "regular", "no" → "false"
        option = menu_cache.resolve_option_by_alias(attr_slug, value_clean)
        if option:
            return option.get("slug", "").lower() == "true"
        # No match found - return None to indicate unknown value
        return None

    # Try to resolve via option alias lookup (data-driven)
    option = menu_cache.resolve_option_by_alias(attr_slug, value_clean)
    if option:
        return option.get("slug", value_clean)

    # Return the cleaned value as fallback
    return value_clean


def _get_attribute_info(
    attr_slug: str,
    item_type_slug: str | None = None,
) -> dict | None:
    """
    Get attribute info from menu cache.

    Searches the specified item type first, then falls back to searching
    all item types if not found.

    Args:
        attr_slug: The attribute slug
        item_type_slug: Optional item type to search first

    Returns:
        Attribute info dict or None if not found
    """
    # Try specified item type first
    if item_type_slug:
        try:
            attrs = menu_cache.get_item_type_attributes(item_type_slug)
            attr_info = attrs.get(attr_slug)
            if attr_info:
                return attr_info
        except Exception:
            pass

    # Fall back to searching all item types
    try:
        for type_slug in menu_cache.get_all_item_type_slugs():
            attrs = menu_cache.get_item_type_attributes(type_slug)
            if attr_slug in attrs:
                return attrs[attr_slug]
    except Exception:
        pass

    return None


def get_attribute_display_name(attr_slug: str) -> str:
    """
    Get human-readable display name for an attribute.

    First tries the database, then falls back to converting the slug
    to readable form.

    Args:
        attr_slug: The attribute slug (e.g., "size", "milk_type")

    Returns:
        Human-readable display name (e.g., "Size", "Milk Type")
    """
    attr_info = _get_attribute_info(attr_slug)
    if attr_info:
        return attr_info.get("display_name", attr_slug)
    # Fallback: convert slug to readable form
    return attr_slug.replace("_", " ").title()


def normalize_for_match(s: str) -> str:
    """
    Normalize a string for fuzzy matching.

    Handles variations like:
    - "blue berry" matching "blueberry"
    - "black and white" matching "black & white"

    Args:
        s: The string to normalize

    Returns:
        Normalized string with spaces removed and & converted to "and"
    """
    return s.replace("&", "and").replace(" ", "")
