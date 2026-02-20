"""
Modifier Field Removal Operations.

Handles removing modifiers from items, including both attribute_values
entries and direct field access on item objects.
"""

import logging
from typing import Any

from .models import ItemTask, MenuItemTask
from .normalization import format_slug_for_display
from .modifier_operations import ModifierField, ModifierMatch, ModifierRemovalResult, _get_list_item_slug

logger = logging.getLogger(__name__)


def _remove_from_attribute_list(
    item: MenuItemTask,
    match: ModifierMatch,
    quantity: int | None,
) -> ModifierRemovalResult:
    """Remove a value from a list-type attribute_values entry."""
    field = match.field
    if match.matched_value:
        removed = item.remove_selection(
            match.attribute_key,
            match.matched_value,
            decrement_by=quantity,
        )
        if removed:
            remaining_qty = None
            if quantity is not None:
                for sel in item.selections:
                    if (sel.get("category") == match.attribute_key and
                        sel.get("slug") == match.matched_value):
                        remaining_qty = sel.get("quantity", 1)
                        break

            display_name = format_slug_for_display(match.matched_value)
            if remaining_qty is not None and remaining_qty > 0:
                logger.info(
                    "Decremented '%s' by %d in attribute_values['%s'] for %s (now %d)",
                    match.matched_value, quantity, match.attribute_key,
                    type(item).__name__, remaining_qty
                )
                return ModifierRemovalResult(
                    success=True,
                    removed_value=match.matched_value,
                    message=f"OK, I've removed {quantity} {display_name} ({remaining_qty} remaining)."
                )
            else:
                logger.info(
                    "Removed '%s' from attribute_values['%s'] for %s",
                    match.matched_value, match.attribute_key, type(item).__name__
                )
                return ModifierRemovalResult(
                    success=True,
                    removed_value=match.matched_value,
                    message=f"OK, I've removed the {display_name}."
                )
        else:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"I couldn't find {match.matched_value} to remove."
            )
    else:
        # Remove all
        attr_value = item.attribute_values.get(match.attribute_key, [])
        removed = attr_value.copy() if attr_value else []
        item.remove_selection(match.attribute_key)
        return ModifierRemovalResult(
            success=True,
            removed_value=", ".join(str(v) for v in removed),
            message=f"OK, I've removed all {field.display_name}."
        )


def _remove_from_attribute_single(
    item: MenuItemTask,
    match: ModifierMatch,
) -> ModifierRemovalResult:
    """Remove a single-value attribute_values entry."""
    attr_value = item.attribute_values.get(match.attribute_key)
    removed_value = str(attr_value)
    item.remove_selection(match.attribute_key)
    logger.info(
        "Removed '%s' from attribute_values['%s'] for %s",
        removed_value, match.attribute_key, type(item).__name__
    )
    display_name = format_slug_for_display(removed_value)
    return ModifierRemovalResult(
        success=True,
        removed_value=removed_value,
        message=f"OK, I've removed the {display_name}."
    )


def _remove_from_field_list(
    item: ItemTask,
    field: ModifierField,
    match: ModifierMatch,
    current_value: list,
    quantity: int | None,
) -> ModifierRemovalResult:
    """Remove a value from a list-type modifier field."""
    if not isinstance(current_value, list) or len(current_value) == 0:
        return ModifierRemovalResult(
            success=False,
            removed_value=None,
            message=f"There's no {field.display_name} to remove."
        )

    if match.matched_value:
        new_list = []
        removed = None
        remaining_qty = None
        for list_item in current_value:
            item_value = _get_list_item_slug(list_item)

            if item_value.lower() == match.matched_value.lower():
                removed = item_value
                if quantity is not None and isinstance(list_item, dict):
                    current_qty = list_item.get("quantity", 1)
                    new_qty = current_qty - quantity
                    if new_qty > 0:
                        list_item["quantity"] = new_qty
                        remaining_qty = new_qty
                        new_list.append(list_item)
                        continue
            else:
                new_list.append(list_item)

        if removed:
            setattr(item, field.field_name, new_list)
            display_name = format_slug_for_display(removed)
            if remaining_qty is not None and remaining_qty > 0:
                logger.info(
                    "Decremented %s '%s' by %d from %s (now %d)",
                    field.display_name, removed, quantity, type(item).__name__, remaining_qty
                )
                return ModifierRemovalResult(
                    success=True,
                    removed_value=removed,
                    message=f"OK, I've removed {quantity} {display_name} ({remaining_qty} remaining)."
                )
            else:
                logger.info("Removed %s '%s' from %s", field.display_name, removed, type(item).__name__)
                return ModifierRemovalResult(
                    success=True,
                    removed_value=removed,
                    message=f"OK, I've removed the {display_name}."
                )
        else:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"I couldn't find {match.matched_value} to remove."
            )
    else:
        # Remove all items from list
        removed_items = []
        for list_item in current_value:
            removed_items.append(_get_list_item_slug(list_item))

        setattr(item, field.field_name, [])
        logger.info("Removed all %s from %s: %s", field.display_name, type(item).__name__, removed_items)

        if len(removed_items) == 1:
            display_name = format_slug_for_display(removed_items[0])
            return ModifierRemovalResult(
                success=True,
                removed_value=removed_items[0],
                message=f"OK, I've removed the {display_name}."
            )
        else:
            return ModifierRemovalResult(
                success=True,
                removed_value=", ".join(removed_items),
                message=f"OK, I've removed the {field.display_name}."
            )


def _remove_from_field_single(
    item: ItemTask,
    field: ModifierField,
    current_value: Any,
) -> ModifierRemovalResult:
    """Remove a single-value modifier field."""
    removed_value = str(current_value)
    setattr(item, field.field_name, None)
    logger.info("Removed %s '%s' from %s", field.display_name, removed_value, type(item).__name__)
    display_name = format_slug_for_display(removed_value)
    return ModifierRemovalResult(
        success=True,
        removed_value=removed_value,
        message=f"OK, I've removed the {display_name}."
    )


def remove_modifier_from_item(
    item: ItemTask,
    match: ModifierMatch,
    quantity: int | None = None,
) -> ModifierRemovalResult:
    """
    Remove a modifier from an item.

    Args:
        item: The item to modify
        match: The modifier match result from find_modifier_match
        quantity: If provided, decrement by this amount instead of removing entirely.
                  If None, removes all of the matched modifier (existing behavior).

    Returns:
        ModifierRemovalResult with success status and message
    """
    field = match.field

    # Path 1: MenuItemTask attribute_values
    if match.attribute_key and isinstance(item, MenuItemTask):
        attribute_values = item.attribute_values
        if not attribute_values or match.attribute_key not in attribute_values:
            return ModifierRemovalResult(
                success=False,
                removed_value=None,
                message=f"There's no {field.display_name} to remove."
            )
        attr_value = attribute_values[match.attribute_key]
        if isinstance(attr_value, list):
            return _remove_from_attribute_list(item, match, quantity)
        return _remove_from_attribute_single(item, match)

    # Path 2: Direct field access
    current_value = getattr(item, field.field_name, None)
    if current_value is None:
        return ModifierRemovalResult(
            success=False,
            removed_value=None,
            message=f"There's no {field.display_name} to remove."
        )
    if field.is_list:
        return _remove_from_field_list(item, field, match, current_value, quantity)
    return _remove_from_field_single(item, field, current_value)
