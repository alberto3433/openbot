"""
Modifier Resolver - Unified modifier matching and resolution utilities.

This module consolidates common modifier operations that were previously
duplicated across modifier_input_handler.py, modifier_change_handler.py,
and modifier_operations.py.

Provides:
- Pattern matching (word-boundary regex)
- Text normalization (articles, quantity, pluralization)
- Category/ingredient resolution
- Modifier matching on items
"""

import re
import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize, get_singular_plural_variants

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

__all__ = [
    "match_pattern_in_input",
    "match_any_pattern_in_input",
    "normalize_modifier_input",
    "resolve_ingredient_category",
    "find_all_categories_for_value",
    "belongs_to_category",
]


# ============================================================================
# Pattern Matching
# ============================================================================

def match_pattern_in_input(pattern: str, input_lower: str) -> bool:
    """Check if pattern matches input with word boundaries.

    This is the core matching function used throughout the modifier system.
    Uses word-boundary regex to ensure "ham" matches "ham" but not "graham".

    Args:
        pattern: The pattern to search for (will be escaped)
        input_lower: Lowercased user input to search in

    Returns:
        True if pattern matches with word boundaries
    """
    return bool(re.search(rf'\b{re.escape(pattern)}\b', input_lower))


def match_any_pattern_in_input(
    patterns: list[str],
    input_lower: str,
) -> str | None:
    """Return first pattern that matches input with word boundaries.

    Args:
        patterns: List of patterns to try
        input_lower: Lowercased user input to search in

    Returns:
        First matching pattern, or None if no match
    """
    for pattern in patterns:
        if match_pattern_in_input(pattern, input_lower):
            return pattern
    return None


def find_matching_ingredient_pattern(
    input_lower: str,
    category: str | None = None,
) -> dict | None:
    """Find ingredient details matching the input.

    Searches through ingredient patterns and returns match info.

    Args:
        input_lower: Lowercased user input
        category: Optional category to filter (e.g., "syrup", "milk")

    Returns:
        Dict with slug, name, pattern if found, None otherwise
    """
    if category:
        categories = [category]
    else:
        # Search all categories
        categories = menu_cache.get_all_ingredient_categories()

    for cat in categories:
        details = menu_cache.get_ingredient_details(cat)
        for detail in details:
            for pattern in detail.get("patterns", []):
                if match_pattern_in_input(pattern, input_lower):
                    return {
                        "slug": detail["slug"],
                        "name": detail["name"],
                        "category": cat,
                        "pattern": pattern,
                    }
    return None


# ============================================================================
# Text Normalization
# ============================================================================

# Common articles to strip
ARTICLES = ("a ", "an ", "the ", "some ")

# Common trailing filler words
TRAILING_FILLERS = (" please", " thanks", " thank you", " pls")


def normalize_modifier_input(
    value: str,
    strip_articles: bool = True,
    strip_trailing_fillers: bool = False,
    normalize_whitespace: bool = True,
) -> str:
    """Unified modifier input normalization.

    Consolidates normalization logic from:
    - modifier_operations._normalize_modifier_name()
    - modifier_change_handler._clean_modifier_value()

    Args:
        value: Raw input value
        strip_articles: Remove leading articles (a, an, the, some)
        strip_trailing_fillers: Remove trailing filler words (please, thanks)
        normalize_whitespace: Collapse multiple spaces to single space

    Returns:
        Normalized string
    """
    result = value.lower().strip()

    if strip_articles:
        for article in ARTICLES:
            if result.startswith(article):
                result = result[len(article):]
                break

    if strip_trailing_fillers:
        for filler in TRAILING_FILLERS:
            if result.endswith(filler):
                result = result[:-len(filler)]
                break

    if normalize_whitespace:
        result = ' '.join(result.split())

    return result.strip()


def strip_quantity_prefix(value: str) -> tuple[int | None, str]:
    """Extract leading quantity from modifier value.

    Handles:
    - Numeric: "2 shots" -> (2, "shots")
    - Word: "double shot" -> (2, "shot")
    - None: "vanilla" -> (None, "vanilla")

    Args:
        value: Input string potentially starting with quantity

    Returns:
        Tuple of (quantity or None, remaining text)
    """
    from .parsers.quantity_utils import BASIC_WORD_TO_NUM, extract_leading_quantity

    value = value.strip()

    # Try numeric extraction first
    quantity, remaining = extract_leading_quantity(value)
    if quantity is not None:
        return quantity, remaining

    # Try word-based quantity
    value_lower = value.lower()
    for word, num in BASIC_WORD_TO_NUM.items():
        if value_lower.startswith(word + " "):
            remaining = value[len(word) + 1:].strip()
            # Handle pluralization (e.g., "double shots" -> "shot")
            if remaining.endswith("s") and len(remaining) > 1:
                singular = singularize(remaining)
                if singular:
                    remaining = singular
            return num, remaining

    return None, value


# ============================================================================
# Category/Ingredient Resolution
# ============================================================================

def resolve_ingredient_category(slug_or_name: str) -> str | None:
    """Unified ingredient category lookup with fallbacks.

    Consolidates category resolution from:
    - modifier_input_handler.belongs_to_category()
    - modifier_change_handler._analyze_modifier()
    - modifier_operations (alias lookups)

    Args:
        slug_or_name: Ingredient slug or name to look up

    Returns:
        Category slug if found, None otherwise
    """
    value = slug_or_name.lower().strip()

    # Try direct category lookup
    category = menu_cache.get_ingredient_category(value)
    if category:
        return category

    # Try with common suffixes (e.g., "oat" -> "oat milk")
    common_suffixes = [" milk", " syrup"]
    for suffix in common_suffixes:
        category = menu_cache.get_ingredient_category(value + suffix)
        if category:
            return category

    # Try alias resolution
    all_aliases = menu_cache.get_ingredient_aliases()
    for alias, canonical in all_aliases.items():
        if alias.lower() == value:
            category = menu_cache.get_ingredient_category(canonical)
            if category:
                return category

    return None


def find_all_categories_for_value(value: str) -> list[str]:
    """Find all categories a modifier value could belong to.

    Used for disambiguation when a value matches multiple categories.

    Args:
        value: Modifier value (e.g., "vanilla")

    Returns:
        List of matching category slugs
    """
    return menu_cache.find_all_categories_for_ingredient(value)


def belongs_to_category(modifier: dict, target_category: str) -> bool:
    """Check if a modifier belongs to a specific category.

    Consolidated from modifier_input_handler.belongs_to_category().

    Args:
        modifier: Modifier dict with slug and optional category
        target_category: Category to check against

    Returns:
        True if modifier belongs to target category
    """
    # Direct category match
    if modifier.get("category") == target_category:
        return True

    # Look up ingredient category from slug
    slug = modifier.get("slug", "")
    if slug:
        category = resolve_ingredient_category(slug)
        if category == target_category:
            return True

    return False


# ============================================================================
# Modifier Matching Utilities
# ============================================================================

def get_modifier_match_variants(value: str) -> list[str]:
    """Get all variants of a value for matching.

    Generates singular/plural and normalized variants.

    Args:
        value: Original value

    Returns:
        List of variant strings to try matching
    """
    variants = set()
    normalized = normalize_modifier_input(value)
    variants.add(normalized)

    # Add singular/plural variants
    for variant in get_singular_plural_variants(normalized):
        variants.add(variant)

    return list(variants)


def format_modifier_for_display(slug: str, display_name: str | None = None) -> str:
    """Format a modifier slug for user display.

    Args:
        slug: Modifier slug (e.g., "oat_milk")
        display_name: Optional display name override

    Returns:
        Formatted display string (e.g., "Oat Milk")
    """
    if display_name:
        return display_name

    # Convert slug to title case
    return slug.replace("_", " ").title()
