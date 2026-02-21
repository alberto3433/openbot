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

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.tasks.parsers.constants import ARTICLES
from orderbot.tasks.utils.text import normalize_text, word_boundary_match

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

__all__ = [
    "match_pattern_in_input",
    "match_any_pattern_in_input",
    "normalize_modifier_input",
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
    return word_boundary_match(pattern, input_lower)


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


# ============================================================================
# Text Normalization
# ============================================================================

# ARTICLES imported from parsers.constants (single source of truth)

# Common trailing filler words (ordered longest-first for greedy matching)
TRAILING_FILLERS = (
    " if you don't mind",
    " if that's alright",
    " when you get a chance",
    " if that's okay",
    " if that's ok",
    " if you would",
    " if you could",
    " if possible",
    " if you can",
    " thank you",
    " thanks",
    " please",
    " pls",
    " thx",
)


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
    result = normalize_text(value)

    if strip_articles:
        for article in ARTICLES:
            prefix = article + " "
            if result.startswith(prefix):
                result = result[len(prefix):]
                break

    if strip_trailing_fillers:
        for filler in TRAILING_FILLERS:
            if result.endswith(filler):
                result = result[:-len(filler)]
                break

    if normalize_whitespace:
        result = ' '.join(result.split())

    return result.strip()


# ============================================================================
# Category/Ingredient Resolution
# ============================================================================

def _resolve_ingredient_category(slug_or_name: str) -> str | None:
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
    value = normalize_text(slug_or_name)

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
        category = _resolve_ingredient_category(slug)
        if category == target_category:
            return True

    return False
