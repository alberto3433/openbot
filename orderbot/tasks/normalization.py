"""
Unified text normalization for order handling.

This module is the SINGLE SOURCE OF TRUTH for all text normalization in the orderbot.
All handlers, parsers, and matchers should use these functions for consistent behavior.

## Public API

### Text Cleaning
- `strip_ordering_prefix(text)` - Remove "I want", "can I get", etc.
- `strip_filler_words(text)` - Remove "the", "please", "just", etc. (anywhere in text)
- `strip_leading_filler_words(text)` - Remove "a", "an", "the", "some" from start only

### For Option Matching
- `normalize_for_option_match(text)` - Strip quantities, singularize plurals
- `normalize_for_match(text)` - Remove spaces/& for fuzzy matching

### Slug Conversion
- `normalize_to_slug(text)` - Convert to slug format (e.g., "Vanilla Syrup" -> "vanilla_syrup")
- `format_slug_for_display(slug)` - Convert slug to display (e.g., "vanilla_syrup" -> "Vanilla Syrup")

### Value Resolution
- `resolve_to_canonical(attr_slug, value)` - Resolve to DB canonical form
- `singularize(word)` - Convert plural to singular (re-exported from cache.base)

## Usage Examples

```python
from orderbot.tasks.normalization import (
    strip_filler_words,
    normalize_for_option_match,
    normalize_to_slug,
)

# Clean user input
clean = strip_filler_words("the bacon please")  # -> "bacon"

# Prepare for matching
normalized = normalize_for_option_match("2 scrambled eggs")  # -> "scrambled egg"

# Convert to slug
slug = normalize_to_slug("Vanilla Syrup")  # -> "vanilla_syrup"
```
"""
from __future__ import annotations

import logging
import re

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize  # Re-export for convenience
from orderbot.exceptions import MenuDataNotLoadedError

logger = logging.getLogger(__name__)

# Re-export singularize so callers can import from this module
__all__ = [
    # Text cleaning
    "strip_ordering_prefix",
    "strip_filler_words",
    "strip_leading_filler_words",
    # Option matching
    "normalize_for_option_match",
    "normalize_for_match",
    # Slug conversion
    "normalize_to_slug",
    "format_slug_for_display",
    # Value resolution
    "resolve_to_canonical",
    "get_attribute_display_name",
    # Re-exported
    "singularize",
]


# Pattern to strip common ordering prefixes from attribute answers
# e.g., "make it a double" -> "double", "I want avocado" -> "avocado"
_ORDERING_PREFIX_PATTERN = re.compile(
    r"^(?:i(?:'?d)?\s*(?:want|like|need|have)|"
    r"(?:can\s+i\s+(?:get|have))|"
    r"(?:give\s+me)|"
    r"(?:make\s+it(?:\s+a)?)|"
    r"(?:let(?:'?s)?\s+(?:do|go\s+with))|"
    r"(?:i(?:'?ll)?\s+(?:take|have|get)))\s+",
    re.IGNORECASE
)


def strip_ordering_prefix(user_input: str) -> str:
    """Strip common ordering prefixes from user input.

    Handles patterns like:
    - "I want avocado" -> "avocado"
    - "can I get cream cheese" -> "cream cheese"
    - "make it a double" -> "double"
    - "I'd like the everything" -> "the everything"
    - "give me tomatoes" -> "tomatoes"
    - "let's go with scrambled please" -> "scrambled"

    Also strips trailing "please".

    Args:
        user_input: The user's raw input

    Returns:
        The input with ordering prefixes and trailing "please" stripped
    """
    stripped = _ORDERING_PREFIX_PATTERN.sub("", user_input.strip())
    # Also strip trailing "please"
    stripped = re.sub(r"\s+please\s*$", "", stripped, flags=re.IGNORECASE)
    return stripped.strip()


# Common filler words to remove for matching
# These are words that don't affect the meaning for option matching
_FILLER_WORDS = frozenset(["the", "please", "i want", "i'll take", "just", "a", "an"])


def strip_filler_words(user_input: str) -> str:
    """Strip common filler words from user input for matching.

    Removes articles, politeness words, and ordering phrases that don't
    affect the core meaning. Simpler than strip_ordering_prefix() - use
    this for disambiguation matching where you just need clean tokens.

    Handles patterns like:
    - "the bacon" -> "bacon"
    - "please" -> ""
    - "just coffee" -> "coffee"
    - "the first one please" -> "first one"

    Args:
        user_input: The user's raw input

    Returns:
        Cleaned, lowercased input with filler words removed

    Examples:
        >>> strip_filler_words("the bacon please")
        "bacon"
        >>> strip_filler_words("I want the first one")
        "first one"
    """
    input_lower = user_input.lower().strip()
    # Remove filler phrases (order matters - longer phrases first)
    for filler in ["i want ", "i'll take ", "just ", "the ", "please", "a ", "an "]:
        input_lower = input_lower.replace(filler, "").strip()
    return input_lower


def strip_leading_filler_words(text: str) -> str:
    """Strip common filler words from the START of user input only.

    Removes leading articles (some, a, an, the) for cleaner display names.
    Unlike strip_filler_words(), this only removes words at the beginning,
    preserving words like "the" that may appear in item names.

    Handles patterns like:
    - "some hash browns" -> "hash browns"
    - "a croissant" -> "croissant"
    - "the classic" -> "classic"
    - "an iced coffee" -> "iced coffee"

    Args:
        text: The text to clean

    Returns:
        Text with leading filler words removed (preserves original case)

    Examples:
        >>> strip_leading_filler_words("some hash browns")
        "hash browns"
        >>> strip_leading_filler_words("The Classic BEC")
        "Classic BEC"
    """
    import re
    # Strip leading filler words (case-insensitive)
    cleaned = re.sub(r'^(some|a|an|the)\s+', '', text.strip(), flags=re.IGNORECASE)
    return cleaned or text


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
    - Boolean attributes return True/False based on option match
    - Negation patterns ("no", "none", "plain" when alone) return None for nullable attrs
    - Falls back to cleaned input if no option match found

    Args:
        attr_slug: The attribute slug (e.g., "size", "milk", "bread")
        value: The raw user input value
        item_type_slug: Optional item type for context-specific resolution

    Returns:
        Normalized value: canonical option slug, boolean, None, or cleaned input
    """
    value_clean = value.lower().strip()

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

    # Try ingredient/modifier normalization for attributes that use ingredient values
    # (e.g., bread attribute uses ingredient table: "plain bagel" -> "plain_bagel")
    normalized = menu_cache.normalize_modifier(value_clean)
    if normalized != value_clean:
        # Found a match - convert display name to slug format
        # "Plain Bagel" -> "plain_bagel"
        return normalized.lower().replace(" ", "_")

    # Check for negation patterns AFTER trying option matching
    # This prevents "plain bagel" from being misinterpreted as negation
    # just because "plain" is a skip pattern - we want to match it as a valid bread type
    # Only check negation if the ENTIRE value is a negation pattern (not just first word)
    negation_patterns = _get_negation_patterns()
    if value_clean in negation_patterns:
        return None

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
