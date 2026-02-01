"""
Unified Modifier Operations.

This module provides a generic system for handling modifier operations
(add, remove, update) across all item types (bagels, coffee, menu items, etc.).

The key insight is that modifiers are just fields on item objects, and we can
handle them generically by defining which fields are "modifiers" for each item type.

All modifier field definitions are loaded from the database. There are no
hardcoded fallbacks - if the database doesn't have modifier fields configured,
an exception is raised to fail fast and make the configuration problem visible.
"""

import logging
from dataclasses import dataclass

from .models import (
    ItemTask,
    MenuItemTask,
)
from orderbot.exceptions import MenuDataNotLoadedError
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants
from .utils.constants import is_price_metadata_key

logger = logging.getLogger(__name__)


@dataclass
class ModifierField:
    """Definition of a modifier field on an item."""
    field_name: str  # The actual attribute name on the item (e.g., "spread")
    display_name: str  # Human-readable name (e.g., "cream cheese")
    aliases: list[str]  # Alternative names users might say (e.g., ["cc", "schmear"])
    is_list: bool = False  # True if field is a list (e.g., extras, sweeteners)


@dataclass
class ModifierMatch:
    """Result of matching user input to a modifier."""
    field: ModifierField
    matched_value: str | None  # The specific value matched (for lists)
    item: ItemTask
    attribute_key: str | None = None  # For MenuItemTask attribute_values (e.g., "condiments")


@dataclass
class ModifierRemovalResult:
    """Result of removing a modifier."""
    success: bool
    removed_value: str | None
    message: str


def _load_modifier_fields_from_db(item_type_slug: str) -> list[ModifierField]:
    """Load modifier fields from database for an item type.

    Returns a list of ModifierField objects. Returns empty list if no modifier
    fields are defined for this item type (this is valid - not all item types
    have modifier fields via item_type_ingredients).
    """
    field_configs = menu_cache.get_modifier_fields_for_item_type(item_type_slug)
    if not field_configs:
        return []  # No modifier fields defined for this item type

    result = []
    for config in field_configs:
        result.append(ModifierField(
            field_name=config["field_name"],
            display_name=config["display_name"],
            aliases=config["aliases"],
            is_list=config["is_list"],
        ))

    logger.debug(
        "Loaded %d modifier fields from DB for %s: %s",
        len(result), item_type_slug,
        [(f.field_name, len(f.aliases)) for f in result]
    )
    return result


def get_modifier_fields(item: ItemTask) -> list[ModifierField]:
    """Get the modifier field definitions for an item type.

    Loads modifier fields from database. Fails fast if item type not set.

    Raises:
        MenuDataNotLoadedError: If item has no menu_item_type or no modifier fields in database
    """
    if isinstance(item, MenuItemTask):
        item_type = getattr(item, 'menu_item_type', None)
        if not item_type:
            raise MenuDataNotLoadedError(
                f"MenuItemTask '{item.menu_item_name}' has no menu_item_type set. "
                f"Ensure menu_item_type is populated when creating items."
            )
        return _load_modifier_fields_from_db(item_type)
    else:
        return []


def _normalize_modifier_name(name: str) -> str:
    """Normalize a modifier name for matching."""
    return ' '.join(name.lower().strip().split())


def find_modifier_match(item: ItemTask, user_input: str) -> ModifierMatch | None:
    """
    Find if user input matches any modifier on the item.

    Args:
        item: The item to check
        user_input: What the user said (e.g., "cream cheese", "the bacon")

    Returns:
        ModifierMatch if found, None otherwise
    """
    normalized_input = _normalize_modifier_name(user_input)

    # Remove leading "the " if present
    if normalized_input.startswith("the "):
        normalized_input = normalized_input[4:]

    fields = get_modifier_fields(item)

    logger.debug(
        "find_modifier_match: searching for '%s' in %d fields on %s",
        normalized_input, len(fields), getattr(item, 'menu_item_name', 'unknown')
    )

    for field in fields:
        value = getattr(item, field.field_name, None)
        logger.debug(
            "find_modifier_match: field=%s, value=%r, num_aliases=%d",
            field.field_name, value, len(field.aliases)
        )
        if value is None:
            continue

        # Check if user input matches the field's aliases
        # Check for early matches
        matching_aliases = [a for a in field.aliases if normalized_input == a or a in normalized_input]
        if matching_aliases:
            logger.debug(
                "find_modifier_match: field=%s matched aliases=%s for input='%s'",
                field.field_name, matching_aliases[:5], normalized_input
            )
        for alias in field.aliases:
            if normalized_input == alias or alias in normalized_input:
                if field.is_list:
                    # For lists, find the specific matching item
                    if isinstance(value, list):
                        # Skip empty lists - nothing to match against
                        if not value:
                            continue
                        for list_item in value:
                            # Handle dict items (like sweeteners: [{slug: "sugar"}])
                            if isinstance(list_item, dict):
                                item_value = list_item.get("slug", "") or ""
                            else:
                                item_value = str(list_item)
                            if alias in item_value.lower() or normalized_input in item_value.lower():
                                return ModifierMatch(field=field, matched_value=item_value, item=item)
                        # If alias matched but no specific list item, still return match
                        # This handles "remove syrup" removing all syrups
                        return ModifierMatch(field=field, matched_value=None, item=item)
                else:
                    return ModifierMatch(field=field, matched_value=None, item=item)

        # For non-list fields, also check if the actual value matches
        if not field.is_list and value:
            value_str = str(value).lower()
            # Check if user input contains the value or vice versa
            if normalized_input in value_str or value_str in normalized_input:
                return ModifierMatch(field=field, matched_value=None, item=item)

            # Special handling for abbreviated/short modifier names that match longer values
            # e.g., spread="kalamata olive cream cheese", user says "cream cheese" or "cc"
            # Use database normalization to expand abbreviations
            canonical_input = menu_cache.normalize_modifier(normalized_input)
            if canonical_input:
                canonical_lower = canonical_input.lower()
                if canonical_lower in value_str:
                    return ModifierMatch(field=field, matched_value=None, item=item)

        # For list fields, check if any item matches the input directly
        if field.is_list and isinstance(value, list):
            for list_item in value:
                if isinstance(list_item, dict):
                    item_value = list_item.get("slug", "") or ""
                else:
                    item_value = str(list_item)
                if normalized_input in item_value.lower() or item_value.lower() in normalized_input:
                    return ModifierMatch(field=field, matched_value=item_value, item=item)

    # For MenuItemTask, also check attribute_values dictionary
    if isinstance(item, MenuItemTask):
        attribute_values = getattr(item, 'attribute_values', None)
        if attribute_values and isinstance(attribute_values, dict):
            # Get singular/plural variants for matching (e.g., "eggs" -> ["eggs", "egg"])
            input_variants = get_singular_plural_variants(normalized_input)

            for attr_key, attr_value in attribute_values.items():
                # Skip metadata fields
                if is_price_metadata_key(attr_key):
                    continue

                if isinstance(attr_value, list):
                    for list_item in attr_value:
                        item_value = str(list_item).lower()
                        # Normalize underscores to spaces for comparison
                        # (stored: "blueberry_cream_cheese" vs input: "blueberry cream cheese")
                        item_value_normalized = item_value.replace("_", " ")
                        for variant in input_variants:
                            if variant in item_value_normalized or item_value_normalized in variant:
                                synthetic_field = ModifierField(
                                    field_name="attribute_values",
                                    display_name=attr_key.replace("_", " "),
                                    aliases=[],
                                    is_list=True,
                                )
                                return ModifierMatch(
                                    field=synthetic_field,
                                    matched_value=str(list_item),
                                    item=item,
                                    attribute_key=attr_key,
                                )
                elif attr_value:
                    value_str = str(attr_value).lower()
                    # Normalize underscores to spaces for comparison
                    value_str_normalized = value_str.replace("_", " ")
                    for variant in input_variants:
                        if variant in value_str_normalized or value_str_normalized in variant:
                            synthetic_field = ModifierField(
                                field_name="attribute_values",
                                display_name=attr_key.replace("_", " "),
                                aliases=[],
                                is_list=False,
                            )
                            return ModifierMatch(
                                field=synthetic_field,
                                matched_value=str(attr_value),
                                item=item,
                                attribute_key=attr_key,
                            )

    return None


def remove_modifier_from_item(
    item: ItemTask,
    match: ModifierMatch,
) -> ModifierRemovalResult:
    """
    Remove a modifier from an item.

    Args:
        item: The item to modify
        match: The modifier match result from find_modifier_match

    Returns:
        ModifierRemovalResult with success status and message
    """
    field = match.field

    # Special handling for MenuItemTask attribute_values
    if match.attribute_key and isinstance(item, MenuItemTask):
        attribute_values = getattr(item, 'attribute_values', None)
        if not attribute_values:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"There's no {field.display_name} to remove."
            )

        if match.attribute_key not in attribute_values:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"There's no {field.display_name} to remove."
            )

        attr_value = attribute_values[match.attribute_key]

        if isinstance(attr_value, list):
            # Remove specific item from list
            if match.matched_value:
                # Use remove_selection to properly update the underlying modifiers list
                # (attribute_values is a computed property - modifying the returned dict doesn't persist)
                removed = item.remove_selection(match.attribute_key, match.matched_value)
                if removed:
                    logger.info(
                        "Removed '%s' from attribute_values['%s'] for %s",
                        match.matched_value, match.attribute_key, type(item).__name__
                    )
                    return ModifierRemovalResult(
                        success=True,
                        removed_value=match.matched_value,
                        message=f"OK, I've removed the {match.matched_value}."
                    )
                else:
                    return ModifierRemovalResult(
                        success=False,
                        removed_value=None,
                        message=f"I couldn't find {match.matched_value} to remove."
                    )
            else:
                # Remove all - shouldn't normally happen but handle it
                removed = attr_value.copy() if attr_value else []
                # Use remove_selection to properly update the underlying modifiers list
                item.remove_selection(match.attribute_key)
                return ModifierRemovalResult(
                    success=True,
                    removed_value=", ".join(str(v) for v in removed),
                    message=f"OK, I've removed all {field.display_name}."
                )
        else:
            # Single value - remove it
            removed_value = str(attr_value)
            # Use remove_selection to properly update the underlying modifiers list
            # (attribute_values is a computed property - modifying the returned dict doesn't persist)
            item.remove_selection(match.attribute_key)
            # Note: remove_selection handles clearing both the value and any associated _price
            logger.info(
                "Removed '%s' from attribute_values['%s'] for %s",
                removed_value, match.attribute_key, type(item).__name__
            )
            return ModifierRemovalResult(
                success=True,
                removed_value=removed_value,
                message=f"OK, I've removed the {removed_value}."
            )

    current_value = getattr(item, field.field_name, None)

    if current_value is None:
        return ModifierRemovalResult(
            success=False,
            removed_value=None,
            message=f"There's no {field.display_name} to remove."
        )

    if field.is_list:
        if not isinstance(current_value, list) or len(current_value) == 0:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"There's no {field.display_name} to remove."
            )

        if match.matched_value:
            # Remove specific item from list
            new_list = []
            removed = None
            for list_item in current_value:
                if isinstance(list_item, dict):
                    item_value = list_item.get("slug", "") or ""
                else:
                    item_value = str(list_item)

                if item_value.lower() == match.matched_value.lower():
                    removed = item_value
                else:
                    new_list.append(list_item)

            if removed:
                setattr(item, field.field_name, new_list)
                logger.info("Removed %s '%s' from %s", field.display_name, removed, type(item).__name__)
                return ModifierRemovalResult(
                    success=True,
                    removed_value=removed,
                    message=f"OK, I've removed the {removed}."
                )
            else:
                return ModifierRemovalResult(
                    success=False,
                    removed_value=None,
                    message=f"I couldn't find {match.matched_value} to remove."
                )
        else:
            # Remove all items from list (e.g., "remove syrup" removes all syrups)
            removed_items = []
            for list_item in current_value:
                if isinstance(list_item, dict):
                    item_value = list_item.get("slug", "") or ""
                else:
                    item_value = str(list_item)
                removed_items.append(item_value)

            setattr(item, field.field_name, [])
            logger.info("Removed all %s from %s: %s", field.display_name, type(item).__name__, removed_items)

            if len(removed_items) == 1:
                return ModifierRemovalResult(
                    success=True,
                    removed_value=removed_items[0],
                    message=f"OK, I've removed the {removed_items[0]}."
                )
            else:
                return ModifierRemovalResult(
                    success=True,
                    removed_value=", ".join(removed_items),
                    message=f"OK, I've removed the {field.display_name}."
                )
    else:
        # Single value field - clear it
        removed_value = str(current_value)
        setattr(item, field.field_name, None)

        logger.info("Removed %s '%s' from %s", field.display_name, removed_value, type(item).__name__)
        return ModifierRemovalResult(
            success=True,
            removed_value=removed_value,
            message=f"OK, I've removed the {removed_value}."
        )


def find_modifier_on_any_item(
    items: list[ItemTask],
    user_input: str,
    prefer_last: bool = True,
) -> ModifierMatch | None:
    """
    Find if user input matches a modifier on any item in the list.

    Args:
        items: List of items to check
        user_input: What the user said
        prefer_last: If True, check items from last to first (default)

    Returns:
        ModifierMatch if found, None otherwise
    """
    search_order = reversed(items) if prefer_last else items

    for item in search_order:
        match = find_modifier_match(item, user_input)
        if match:
            return match

    return None


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
    menu_item_id = getattr(item, 'menu_item_id', None)
    if not menu_item_id:
        return None

    # Check if already in removed_ingredients (can't remove twice)
    removed_ingredients = getattr(item, 'removed_ingredients', [])
    normalized_input = _normalize_modifier_name(user_input)
    if normalized_input.startswith("the "):
        normalized_input = normalized_input[4:]

    for removed in removed_ingredients:
        if normalized_input in removed.lower() or removed.lower() in normalized_input:
            logger.debug("Ingredient '%s' already removed from item", removed)
            return None

    # Look up default ingredients from cache
    from ..cache import menu_cache

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
        getattr(item, 'menu_item_id', None)
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
