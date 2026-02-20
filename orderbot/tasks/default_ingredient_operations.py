"""
Default Ingredient Operations.

Handles matching and removal of default ingredients from menu items.
This is a self-contained subsystem for managing default ingredient
modifications on signature/menu items.
"""

import logging
from dataclasses import dataclass

from .models import ItemTask, MenuItemTask
from .utils.text import strip_leading_article
from .modifier_resolver import normalize_modifier_input
from orderbot.cache import menu_cache

logger = logging.getLogger(__name__)


@dataclass
class DefaultIngredientMatch:
    """Result of matching user input to a default ingredient."""
    ingredient_name: str  # The display name of the ingredient
    attribute_slug: str  # The attribute slug (e.g., "extra_protein")
    item: ItemTask  # The item this belongs to


@dataclass
class DefaultIngredientRemovalResult:
    """Result of removing a default ingredient."""
    success: bool
    removed_value: str | None
    message: str


def find_default_ingredient_match(
    item: ItemTask,
    user_input: str,
) -> DefaultIngredientMatch | None:
    """
    Find if user input matches a default ingredient of a menu item.

    This queries the menu_item_ingredients junction table to find
    ingredients that are part of the menu item's default configuration.

    Args:
        item: The item to check (must be MenuItemTask with menu_item_id)
        user_input: What the user said (e.g., "bacon", "the bacon")

    Returns:
        DefaultIngredientMatch if found, None otherwise
    """
    # Only MenuItemTask has menu_item_id
    if not isinstance(item, MenuItemTask):
        return None
    menu_item_id = item.menu_item_id
    if not menu_item_id:
        return None

    # Check if already in removed_ingredients (can't remove twice)
    removed_ingredients = item.removed_ingredients
    normalized_input = normalize_modifier_input(user_input, strip_articles=False)
    normalized_input = strip_leading_article(normalized_input)

    for removed in removed_ingredients:
        if normalized_input in removed.lower() or removed.lower() in normalized_input:
            logger.debug("Ingredient '%s' already removed from item", removed)
            return None

    # Look up default ingredients from cache
    defaults = menu_cache.get_menu_item_default_ingredients(menu_item_id)
    if not defaults:
        return None

    # Try to match user input against default ingredients
    for default in defaults:
        ingredient_name = default["ingredient_name"]
        name_lower = ingredient_name.lower()

        # Direct match
        if normalized_input == name_lower:
            return DefaultIngredientMatch(
                ingredient_name=ingredient_name,
                attribute_slug=default["ingredient_category"],
                item=item,
            )

        # Partial match (e.g., "bacon" matches "Applewood Smoked Bacon")
        if normalized_input in name_lower or name_lower in normalized_input:
            return DefaultIngredientMatch(
                ingredient_name=ingredient_name,
                attribute_slug=default["ingredient_category"],
                item=item,
            )

        # Check aliases for this ingredient
        all_aliases = menu_cache.get_ingredient_aliases()
        for alias, canonical in all_aliases.items():
            if canonical.lower() == name_lower:
                if normalized_input == alias or alias in normalized_input:
                    return DefaultIngredientMatch(
                        ingredient_name=ingredient_name,
                        attribute_slug=default["ingredient_category"],
                        item=item,
                    )

    return None


def remove_default_ingredient_from_item(
    item: ItemTask,
    match: DefaultIngredientMatch,
) -> DefaultIngredientRemovalResult:
    """
    Remove a default ingredient from an item.

    This adds the ingredient to the item's removed_ingredients list.
    The removal does NOT affect price (default ingredients are already included).

    Args:
        item: The item to modify
        match: The default ingredient match result

    Returns:
        DefaultIngredientRemovalResult with success status and message
    """
    # Get or create removed_ingredients list
    if not hasattr(item, 'removed_ingredients'):
        logger.warning("Item %s does not have removed_ingredients field", type(item).__name__)
        return DefaultIngredientRemovalResult(
            success=False,
            removed_value=None,
            message="This item type doesn't support ingredient removal."
        )

    # Check if already removed
    for removed in item.removed_ingredients:
        if removed.lower() == match.ingredient_name.lower():
            return DefaultIngredientRemovalResult(
                success=False,
                removed_value=None,
                message=f"{match.ingredient_name} has already been removed."
            )

    # Add to removed_ingredients
    item.removed_ingredients.append(match.ingredient_name)

    logger.info(
        "Removed default ingredient '%s' from %s (menu_item_id=%s)",
        match.ingredient_name,
        type(item).__name__,
        item.menu_item_id if isinstance(item, MenuItemTask) else None
    )

    return DefaultIngredientRemovalResult(
        success=True,
        removed_value=match.ingredient_name,
        message=f"OK, I've removed the {match.ingredient_name}."
    )


def find_default_ingredient_on_any_item(
    items: list[ItemTask],
    user_input: str,
    prefer_last: bool = True,
) -> DefaultIngredientMatch | None:
    """
    Find if user input matches a default ingredient on any item.

    Args:
        items: List of items to check
        user_input: What the user said
        prefer_last: If True, check items from last to first (default)

    Returns:
        DefaultIngredientMatch if found, None otherwise
    """
    search_order = reversed(items) if prefer_last else items

    for item in search_order:
        match = find_default_ingredient_match(item, user_input)
        if match:
            return match

    return None
