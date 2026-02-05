"""
Modifier Removal Handler Module.

Handles detection and execution of modifier removal patterns like
"no milk", "without syrup", "remove the sweetener", "hold the cheese".

All removal patterns are data-driven from the database - no hardcoded modifiers.

Extracted from modifier_input_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from .modifier_resolver import match_pattern_in_input, belongs_to_category

if TYPE_CHECKING:
    from .models import MenuItemTask

logger = logging.getLogger(__name__)

__all__ = [
    "REMOVAL_TEMPLATES",
    "match_category_removal_pattern",
    "remove_modifiers_by_category",
]


# =============================================================================
# Templatized Removal Pattern Matching (Data-Driven)
# =============================================================================
# These templates generate removal patterns dynamically from ingredient categories.
# No hardcoded patterns like "no milk", "without sugar" - all driven by database.

REMOVAL_TEMPLATES = [
    "no {}",
    "without {}",
    "remove {}",
    "remove the {}",
    "hold the {}",
]


def match_category_removal_pattern(input_lower: str, item_type_slug: str) -> str | None:
    """Check if input matches a removal pattern for a modifier CATEGORY.

    Uses templatized patterns ("no {}", "without {}", etc.) with category names.
    Also maps ingredient names to their category for patterns WITHOUT "the"
    (e.g., "without sugar" → sweetener category).

    Patterns WITH "the" (like "remove the bacon") only match category names,
    not ingredients. This prevents "remove the bacon" from removing all proteins.
    Specific ingredient removal is handled by ItemCancellationHandler._try_modifier_removal.

    Args:
        input_lower: Lowercase user input to check
        item_type_slug: The item type to get modifier categories for

    Returns:
        Category slug if a removal pattern matches, None otherwise.

    Examples:
        >>> match_category_removal_pattern("no milk", "sized_beverage")
        "milk"
        >>> match_category_removal_pattern("without sugar", "sized_beverage")
        "sweetener"  # sugar maps to sweetener category
        >>> match_category_removal_pattern("no protein", "bagel")
        "protein"
        >>> match_category_removal_pattern("remove the bacon", "bagel")
        None  # "the" means specific ingredient - handled elsewhere
    """
    # Templates that use "the" should only match category names, not ingredients
    # "remove the bacon" should not remove all proteins
    TEMPLATES_WITHOUT_THE = ["no {}", "without {}", "remove {}"]
    TEMPLATES_WITH_THE = ["remove the {}", "hold the {}"]

    # Get scannable modifier categories for this item type (data-driven)
    categories = menu_cache.get_scannable_modifier_categories(item_type_slug)

    for category in categories:
        # Get category display name and slug
        display_name = menu_cache.get_ingredient_category_display_name(category)
        category_names = {category.lower(), display_name.lower()}

        # Also check singular forms if display name is plural
        if display_name.endswith("s") and len(display_name) > 2:
            category_names.add(display_name[:-1].lower())

        # Get ingredient names for this category (for templates without "the")
        ingredient_names = set()
        ingredients = menu_cache.get_ingredients(category)
        for ingredient in ingredients:
            ingredient_names.add(ingredient.lower())

        # Check templates WITH "the" - only match category names
        for template in TEMPLATES_WITH_THE:
            for name in category_names:
                pattern = template.format(name)
                if match_pattern_in_input(pattern, input_lower):
                    return category

        # Check templates WITHOUT "the" - match category names AND ingredient names
        all_names = category_names | ingredient_names
        for template in TEMPLATES_WITHOUT_THE:
            for name in all_names:
                pattern = template.format(name)
                if match_pattern_in_input(pattern, input_lower):
                    return category

    return None


def remove_modifiers_by_category(
    item: "MenuItemTask",
    category: str,
) -> bool:
    """Remove all modifiers of a specific category from an item.

    Uses the unified selections list. Works for any item type and category.

    Args:
        item: The MenuItemTask to modify
        category: The category of modifiers to remove (e.g., "milk", "syrup")

    Returns:
        True if any modifiers were removed, False otherwise.
    """
    current_selections = item.selections or []
    if not current_selections:
        return False

    # Filter out selections of the specified category
    # Uses belongs_to_category from modifier_resolver for unified category lookup
    new_selections = [m for m in current_selections if not belongs_to_category(m, category)]

    if len(new_selections) < len(current_selections):
        item.selections = new_selections
        logger.info(
            "Removed %d %s modifier(s) from %s",
            len(current_selections) - len(new_selections),
            category,
            item.menu_item_name or item.menu_item_type
        )
        return True

    return False
