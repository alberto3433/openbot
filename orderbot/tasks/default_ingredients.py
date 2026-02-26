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
) -> None:
    """Load default ingredients for a menu item and populate as selections.

    Loads from menu_item_ingredients junction table and adds each ingredient
    as a selection with is_default=True. Default ingredients are included in
    the base price (price=0.0) and won't trigger upsell questions.

    Args:
        item: The MenuItemTask to populate with default ingredients.
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
) -> tuple[list["Selection"], list[dict]]:
    """Filter out selections that are redundant with default ingredients.

    When parsing "egg sandwich with eggs over easy", the parser extracts both
    "egg" and "eggs" as protein modifiers. But The Classic already has eggs
    as a default ingredient, so these are redundant.

    This filters out selections where:
    - The slug (or its singular form) matches a default ingredient slug
    - AND quantity == 1 (explicit "extra eggs" or "2 eggs" should still add)

    Flagged defaults are selections that match a default with quantity==1.
    These are candidates for "Would you like extra?" clarification.

    Args:
        item: The MenuItemTask with default ingredients already populated
        selections: List of extracted selections to filter

    Returns:
        Tuple of (filtered_selections, flagged_defaults) where flagged_defaults
        is a list of dicts with slug, display_name, and category.
    """
    if not selections:
        return selections, []

    # Build lookup: slug -> default modifier dict
    default_mods: dict[str, dict] = {}
    for mod in item.selections:
        if mod.get("is_default"):
            default_mods[mod.get("slug", "").lower()] = mod

    if not default_mods:
        return selections, []

    filtered = []
    flagged_defaults: list[dict] = []
    for sel in selections:
        slug_lower = sel.slug.lower()
        singular_slug = singularize(slug_lower)

        # Check if this selection matches a default (exact or singular form)
        matched_slug = None
        if slug_lower in default_mods:
            matched_slug = slug_lower
        elif singular_slug in default_mods:
            matched_slug = singular_slug

        # Keep selection if it doesn't match defaults OR has explicit quantity > 1
        if not matched_slug or sel.quantity > 1:
            filtered.append(sel)
        else:
            # Flag this default for "would you like extra?" clarification
            default_mod = default_mods[matched_slug]
            flagged_defaults.append({
                "slug": default_mod.get("slug", matched_slug),
                "display_name": default_mod.get("display_name", sel.slug),
                "category": default_mod.get("ingredient_category", sel.category or ""),
            })
            logger.debug(
                "Flagged redundant selection '%s' for extra clarification",
                sel.slug
            )

    return filtered, flagged_defaults
