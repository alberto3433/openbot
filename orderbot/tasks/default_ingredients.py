"""
Default Ingredients Handler.

Handles populating and filtering default ingredients for menu items.
Default ingredients are items that come with a menu item by default (e.g.,
cheddar cheese on The Classic BEC) and are stored in the menu_item_ingredients
junction table.

This module provides two main functions:
- populate_default_ingredients(): Load and apply defaults from the database
- filter_redundant_default_selections(): Remove user selections that duplicate defaults
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

if TYPE_CHECKING:
    from .models import MenuItemTask
    from .schemas import Selection

logger = logging.getLogger(__name__)


def populate_default_ingredients(
    item: "MenuItemTask",
    exclude_slugs: set[str] | None = None,
) -> None:
    """Load default ingredients for a menu item and populate as selections.

    Loads from menu_item_ingredients junction table and adds each ingredient
    as a selection with is_default=True. Default ingredients are included in
    the base price (price=0.0) and won't trigger upsell questions.

    Args:
        item: The MenuItemTask to populate with default ingredients.
        exclude_slugs: Optional set of ingredient slugs (lowercase) to skip.
            Used to prevent adding unrecognized ingredients as defaults.
    """
    if not item.menu_item_id or not item.menu_item_type:
        return

    defaults = menu_cache.get_menu_item_default_ingredients(item.menu_item_id)
    if not defaults:
        logger.debug(
            "No default ingredients found for menu item: %s (id=%s)",
            item.menu_item_name, item.menu_item_id
        )
        return

    logger.info(
        "Populating %d default ingredients for menu item: %s",
        len(defaults), item.menu_item_name
    )

    for default in defaults:
        # Skip excluded ingredients (e.g., unrecognized ones)
        if exclude_slugs and default["ingredient_slug"].lower() in exclude_slugs:
            logger.info(
                "Skipping excluded default ingredient: %s",
                default["ingredient_name"],
            )
            continue

        # Map ingredient category to attribute slug
        attr_slug = menu_cache.get_attribute_for_ingredient_category(
            item.menu_item_type,
            default["ingredient_category"]
        )
        if not attr_slug:
            logger.warning(
                "No attribute mapping for ingredient category '%s' on item type '%s'",
                default["ingredient_category"], item.menu_item_type
            )
            continue

        # Add as selection with is_default=True
        # Price is 0.0 because defaults are included in base price
        item.add_selection(
            slug=default["ingredient_slug"],
            category=attr_slug,
            quantity=default.get("quantity", 1),
            price=0.0,
            display_name=default["ingredient_name"],
            ingredient_category=default["ingredient_category"],
            is_default=True,
        )

        logger.debug(
            "  Added default: %s (%s) -> attr=%s",
            default["ingredient_name"], default["ingredient_slug"], attr_slug
        )


def filter_redundant_default_selections(
    item: "MenuItemTask",
    selections: list["Selection"],
) -> list["Selection"]:
    """Filter out selections that are redundant with default ingredients.

    When parsing "egg sandwich with eggs over easy", the parser extracts both
    "egg" and "eggs" as protein modifiers. But The Classic already has eggs
    as a default ingredient, so these are redundant.

    This filters out selections where:
    - The slug (or its singular form) matches a default ingredient slug
    - AND quantity == 1 (explicit "extra eggs" or "2 eggs" should still add)

    Args:
        item: The MenuItemTask with default ingredients already populated
        selections: List of extracted selections to filter

    Returns:
        Filtered list of selections with redundant defaults removed
    """
    if not selections:
        return selections

    # Get default ingredient slugs from item's modifiers
    default_slugs = set()
    for mod in item.selections:
        if mod.get("is_default"):
            default_slugs.add(mod.get("slug", "").lower())

    if not default_slugs:
        return selections

    filtered = []
    for sel in selections:
        slug_lower = sel.slug.lower()
        singular_slug = singularize(slug_lower)

        # Check if this selection matches a default (exact or singular form)
        matches_default = (
            slug_lower in default_slugs or
            singular_slug in default_slugs
        )

        # Keep selection if it doesn't match defaults OR has explicit quantity > 1
        if not matches_default or sel.quantity > 1:
            filtered.append(sel)
        else:
            logger.debug(
                "Filtered redundant selection '%s' - matches default ingredient",
                sel.slug
            )

    return filtered
