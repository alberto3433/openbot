"""
Unified Modifier Operations.

This module provides a generic system for handling modifier operations
(add, remove, update) across all item types (bagels, coffee, menu items, etc.).

The key insight is that modifiers are just fields on item objects, and we can
handle them generically by defining which fields are "modifiers" for each item type.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from .models import (
    ItemTask,
    BagelItemTask,
    CoffeeItemTask,
    MenuItemTask,
    SignatureItemTask,
)

logger = logging.getLogger(__name__)


@dataclass
class ModifierField:
    """Definition of a modifier field on an item."""
    field_name: str  # The actual attribute name on the item (e.g., "spread")
    display_name: str  # Human-readable name (e.g., "cream cheese")
    aliases: list[str]  # Alternative names users might say (e.g., ["cc", "schmear"])
    is_list: bool = False  # True if field is a list (e.g., extras, sweeteners)
    price_field: str | None = None  # Associated price field to clear (e.g., "spread_price")
    related_fields: list[str] | None = None  # Other fields to clear together (e.g., spread_type)


@dataclass
class ModifierMatch:
    """Result of matching user input to a modifier."""
    field: ModifierField
    matched_value: str | None  # The specific value matched (for lists)
    item: ItemTask


@dataclass
class ModifierRemovalResult:
    """Result of removing a modifier."""
    success: bool
    removed_value: str | None
    message: str


# Define modifier fields for each item type
# This is the single source of truth for what modifiers each item type has

BAGEL_MODIFIER_FIELDS = [
    ModifierField(
        field_name="spread",
        display_name="spread",
        aliases=["cream cheese", "cc", "schmear", "butter"],
        related_fields=["spread_type", "spread_price"],
    ),
    ModifierField(
        field_name="sandwich_protein",
        display_name="protein",
        aliases=["bacon", "ham", "sausage", "turkey", "salami", "pastrami",
                 "corned beef", "nova", "lox", "salmon", "whitefish", "sable"],
    ),
    ModifierField(
        field_name="extras",
        display_name="extras",
        aliases=["tomato", "onion", "lettuce", "pickle", "jalapeno", "avocado",
                 "capers", "egg", "cheese", "american cheese", "swiss", "cheddar",
                 "muenster", "pepper jack"],
        is_list=True,
    ),
]

COFFEE_MODIFIER_FIELDS = [
    ModifierField(
        field_name="milk",
        display_name="milk",
        aliases=["milk", "whole milk", "oat milk", "almond milk", "coconut milk",
                 "skim milk", "soy milk", "2% milk", "half and half", "cream",
                 "oat", "almond", "coconut", "skim", "soy"],
        price_field="milk_upcharge",
    ),
    ModifierField(
        field_name="sweeteners",
        display_name="sweetener",
        aliases=["sugar", "sweetener", "honey", "splenda", "stevia", "raw sugar",
                 "equal", "sweet n low"],
        is_list=True,
    ),
    ModifierField(
        field_name="flavor_syrups",
        display_name="syrup",
        aliases=["syrup", "vanilla", "vanilla syrup", "caramel", "caramel syrup",
                 "hazelnut", "hazelnut syrup", "mocha", "mocha syrup", "lavender",
                 "pumpkin spice"],
        is_list=True,
    ),
]

MENU_ITEM_MODIFIER_FIELDS = [
    ModifierField(
        field_name="spread",
        display_name="spread",
        aliases=["cream cheese", "cc", "schmear", "butter", "spread"],
        price_field="spread_price",
    ),
    ModifierField(
        field_name="modifications",
        display_name="modification",
        aliases=[],  # Dynamic - matches against actual modification values
        is_list=True,
    ),
]

SIGNATURE_ITEM_MODIFIER_FIELDS = [
    ModifierField(
        field_name="modifications",
        display_name="modification",
        aliases=[],
        is_list=True,
    ),
]


def get_modifier_fields(item: ItemTask) -> list[ModifierField]:
    """Get the modifier field definitions for an item type."""
    if isinstance(item, BagelItemTask):
        return BAGEL_MODIFIER_FIELDS
    elif isinstance(item, CoffeeItemTask):
        return COFFEE_MODIFIER_FIELDS
    elif isinstance(item, MenuItemTask):
        return MENU_ITEM_MODIFIER_FIELDS
    elif isinstance(item, SignatureItemTask):
        return SIGNATURE_ITEM_MODIFIER_FIELDS
    else:
        return []


def get_item_modifiers(item: ItemTask) -> list[tuple[str, Any, ModifierField]]:
    """
    Get all current modifiers on an item.

    Returns:
        List of (display_name, current_value, field_definition) tuples
    """
    modifiers = []
    fields = get_modifier_fields(item)

    for field in fields:
        value = getattr(item, field.field_name, None)
        if value is not None:
            if field.is_list and isinstance(value, list) and len(value) > 0:
                modifiers.append((field.display_name, value, field))
            elif not field.is_list and value:
                modifiers.append((field.display_name, value, field))

    return modifiers


def _normalize_modifier_name(name: str) -> str:
    """Normalize a modifier name for matching."""
    return ' '.join(name.lower().strip().split())


def _extract_cream_cheese_flavor(user_input: str) -> str | None:
    """Extract cream cheese flavor from user input like 'kalamata olive cream cheese'."""
    input_lower = user_input.lower()
    # Match patterns like "X cream cheese" or "X cc"
    cc_pattern = re.compile(r'^(.+?)\s+(?:cream\s*cheese|cc)$', re.IGNORECASE)
    match = cc_pattern.match(input_lower.strip())
    if match:
        return match.group(1).strip()
    return None


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

    for field in fields:
        value = getattr(item, field.field_name, None)
        if value is None:
            continue

        # Check if user input matches the field's aliases
        for alias in field.aliases:
            if normalized_input == alias or alias in normalized_input:
                if field.is_list:
                    # For lists, find the specific matching item
                    if isinstance(value, list):
                        for list_item in value:
                            # Handle dict items (like sweeteners: [{type: "sugar"}])
                            if isinstance(list_item, dict):
                                item_value = list_item.get("type") or list_item.get("flavor") or str(list_item)
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

            # Special handling for cream cheese with flavor
            # e.g., spread="kalamata olive cream cheese", user says "cream cheese"
            if "cream cheese" in normalized_input or "cc" in normalized_input:
                if "cream cheese" in value_str or field.field_name == "spread":
                    return ModifierMatch(field=field, matched_value=None, item=item)

        # For list fields, check if any item matches the input directly
        if field.is_list and isinstance(value, list):
            for list_item in value:
                if isinstance(list_item, dict):
                    item_value = list_item.get("type") or list_item.get("flavor") or ""
                else:
                    item_value = str(list_item)
                if normalized_input in item_value.lower() or item_value.lower() in normalized_input:
                    return ModifierMatch(field=field, matched_value=item_value, item=item)

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
                    item_value = list_item.get("type") or list_item.get("flavor") or str(list_item)
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
                    item_value = list_item.get("type") or list_item.get("flavor") or str(list_item)
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

        # Clear related fields
        if field.related_fields:
            for related in field.related_fields:
                if hasattr(item, related):
                    setattr(item, related, None)

        # Clear price field
        if field.price_field and hasattr(item, field.price_field):
            setattr(item, field.price_field, None)

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
