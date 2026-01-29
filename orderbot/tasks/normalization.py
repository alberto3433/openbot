"""
Unified attribute value normalization for order handling.

This module consolidates normalization logic previously duplicated across handlers.
All handlers should use these functions for consistent value resolution.
"""
from __future__ import annotations

import logging
import re

from orderbot.menu_data_cache import menu_cache
from orderbot.cache.base import singularize
from orderbot.exceptions import MenuDataNotLoadedError

logger = logging.getLogger(__name__)


def _get_negation_patterns() -> frozenset[str]:
    """Load negation patterns from database via cache.

    Returns patterns that indicate user wants to remove/clear an attribute
    (e.g., "no milk", "black coffee", "plain bagel").
    """
    return frozenset(menu_cache.get_response_patterns("skip"))


# Note: Shot normalization was removed when shots moved to quantity-based system.
# Instead of discrete options (single/double/triple/quad), shots now use
# numeric quantities like syrups (e.g., "2 shots" → quantity=2).
# The extraction code in parsers/deterministic/extraction.py handles
# "double" → 2, "triple" → 3 conversions at parse time.


def normalize_for_option_match(text: str) -> str:
    """
    Normalize user input for option matching.

    Handles common patterns users type when ordering:
    - Leading quantities: "2 scrambled eggs" → "scrambled eggs"
    - Plural forms: "scrambled eggs" → "scrambled egg"

    Note: Shot quantities ("two shots" → "double") are no longer normalized here
    since shots now use a quantity-based system like syrups. The extraction code
    handles "double" → 2, "triple" → 3 conversions at parse time.

    Args:
        text: Raw user input

    Returns:
        Normalized text suitable for option matching
    """
    text = text.lower().strip()

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
    if first_word in _get_negation_patterns():
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
        except MenuDataNotLoadedError:
            logger.debug("Menu cache not loaded when getting attribute info for %s", attr_slug)

    # Fall back to searching all item types
    try:
        for type_slug in menu_cache.get_all_item_type_slugs():
            attrs = menu_cache.get_item_type_attributes(type_slug)
            if attr_slug in attrs:
                return attrs[attr_slug]
    except MenuDataNotLoadedError:
        logger.debug("Menu cache not loaded when searching for attribute %s", attr_slug)

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


def normalize_to_slug(text: str) -> str:
    """
    Normalize text to slug format for matching against database slugs.

    This is the canonical way to convert user input or display names to
    slug format for option matching. Handles:
    - Lowercase conversion
    - Whitespace stripping
    - Spaces and dashes converted to underscores

    Args:
        text: The text to normalize (e.g., "Vanilla Syrup", "oat-milk")

    Returns:
        Slug-formatted string (e.g., "vanilla_syrup", "oat_milk")

    Examples:
        >>> normalize_to_slug("Vanilla Syrup")
        "vanilla_syrup"
        >>> normalize_to_slug("oat-milk")
        "oat_milk"
        >>> normalize_to_slug("  Extra Shot  ")
        "extra_shot"
    """
    return text.lower().strip().replace(" ", "_").replace("-", "_")


def format_slug_for_display(
    slug: str,
    category: str | None = None,
    *,
    check_cache: bool = True,
) -> str:
    """
    Convert a slug to a human-readable display name.

    This is the canonical way to format slugs for display throughout the codebase.
    It first attempts to look up the display name from the database cache, falling
    back to converting the slug format (underscores to spaces, title case).

    Args:
        slug: The slug to format (e.g., "garlic_bagel", "vanilla_syrup")
        category: Optional category for more specific cache lookup
        check_cache: Whether to check the database cache for display names (default True).
                     Set to False for pure string formatting without DB lookup.

    Returns:
        Human-readable display name (e.g., "Garlic Bagel", "Vanilla Syrup")

    Examples:
        >>> format_slug_for_display("garlic_bagel")
        "Garlic Bagel"  # Or DB display_name if available
        >>> format_slug_for_display("vanilla", category="syrup")
        "Vanilla Syrup"  # From DB if available
        >>> format_slug_for_display("custom_thing", check_cache=False)
        "Custom Thing"  # Pure string conversion
    """
    if check_cache:
        try:
            # Try global attribute option lookup first (for attributes like bread, size)
            if category:
                display_name = menu_cache.get_global_option_display_name(category, slug)
                if display_name:
                    return display_name

            # Try ingredient lookup
            display_name = menu_cache.get_ingredient_display_name(slug)
            if display_name:
                return display_name
        except Exception:
            # Cache not loaded or lookup failed - fall through to string conversion
            pass

    # Fallback: convert slug to readable form
    return slug.replace("_", " ").title()
