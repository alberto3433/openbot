"""
Utility functions for the models module.
"""

import logging

from orderbot.cache import menu_cache
from orderbot.exceptions import MenuDataNotLoadedError

# Import from shared_constants (a pure module with zero project dependencies).
# Previously this was a lazy import to avoid circular dependency through
# utils/__init__.py -> option_matcher -> parsers -> schemas -> models.
from orderbot.tasks.shared_constants import is_price_metadata_key as _is_price_metadata_key

logger = logging.getLogger(__name__)


def pluralize_display_name(display_name: str) -> str:
    """Pluralize a display name by pluralizing the last word.

    Uses the centralized pluralize function from cache/base.py which handles
    irregular plurals and edge cases correctly.

    Examples:
        "Vanilla Syrup" -> "Vanilla Syrups"
        "Extra Shot" -> "Extra Shots"
        "Chocolate Chips" -> "Chocolate Chips" (already plural)
    """
    from orderbot.cache.base import pluralize, singularize

    if not display_name:
        return display_name

    words = display_name.split()
    if not words:
        return display_name

    last_word = words[-1]

    # Check if already plural by seeing if singularize changes it
    singular = singularize(last_word)
    if singular != last_word.lower():
        # Already plural
        return display_name

    # Pluralize the last word
    words[-1] = pluralize(last_word)
    # Preserve original casing if word was capitalized
    if last_word[0].isupper():
        words[-1] = words[-1].capitalize()

    return ' '.join(words)


def is_name_forming_category(category: str, ingredient_slug: str | None = None) -> bool:
    """Check if a category is name-forming (data-driven).

    Name-forming categories have their ingredient display name replace
    the base menu item name. For example, "bread" category means
    "Garlic Bagel" instead of "Bagel, Garlic Bagel".

    Checks both the selection's category (attribute slug) and, if provided,
    the ingredient's actual category. This handles cases where the attribute
    slug differs from the ingredient category (e.g., "tea_flavor" vs "tea").
    """
    try:
        if menu_cache.is_name_forming_category(category):
            return True
        # Also check the ingredient's actual category if slug is provided
        if ingredient_slug:
            ing_cat = menu_cache.get_ingredient_category(ingredient_slug)
            if ing_cat and menu_cache.is_name_forming_category(ing_cat):
                return True
        return False
    except MenuDataNotLoadedError:
        # Cache not loaded - shouldn't happen in production
        logger.warning("Menu cache not loaded when checking name-forming category: %s", category)
        return False


def parse_pending_field(pending_field: str | None) -> tuple[str | None, str | None]:
    """Parse pending_field format 'item_type:attr_slug' into components.

    Args:
        pending_field: The pending field string (e.g., "bagel:toasted" or just "toasted")

    Returns:
        Tuple of (item_type, attr_slug). If no colon present, item_type is None.
        If pending_field is None or empty, returns (None, None).

    Examples:
        parse_pending_field("bagel:toasted") -> ("bagel", "toasted")
        parse_pending_field("toasted") -> (None, "toasted")
        parse_pending_field(None) -> (None, None)
    """
    if not pending_field:
        return None, None
    if ":" in pending_field:
        parts = pending_field.split(":", 1)
        return parts[0], parts[1]
    return None, pending_field
