"""
Toast Order Payload Builder
================================

Translates our internal order state dict into the JSON payload required by
the Toast Orders API v2 (POST /orders/v2/orders).

Toast order structure:
    Order → Check(s) → Selection(s) → Modifier(s)

Each entity needs a Toast GUID (looked up via GuidResolver) and a unique
externalId for idempotency.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .guid_resolver import GuidResolver

logger = logging.getLogger(__name__)


def _generate_external_id(prefix: str = "") -> str:
    """Generate a unique external ID for a Toast entity."""
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def build_toast_order(
    db: Session,
    order_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build a Toast API order payload from our internal order state.

    Args:
        db: Database session (for GUID lookups)
        order_state: Internal order state dict with items, customer, etc.

    Returns:
        Toast order payload dict, or None if no items could be mapped.
    """
    store_id = order_state.get("store_id")
    resolver = GuidResolver(db, store_id=store_id)

    # Build selections (line items)
    selections = _build_selections(order_state, resolver)
    if not selections:
        unmapped = resolver.get_unmapped_items(order_state)
        logger.warning(
            "No Toast-mappable items in order #%s. Unmapped: %s",
            order_state.get("db_order_id"),
            unmapped,
        )
        return None

    # Build dining option
    dining_option = _build_dining_option(order_state, resolver)

    # Build customer info
    customer = _build_customer(order_state)

    # Build the check
    check = {
        "entityType": "Check",
        "externalId": _generate_external_id("chk-"),
        "selections": selections,
        "customer": customer,
    }

    if dining_option:
        check["appliedDiscounts"] = []

    # Build the order
    order_payload: Dict[str, Any] = {
        "entityType": "Order",
        "externalId": _generate_external_id("ord-"),
        "checks": [check],
    }

    if dining_option:
        order_payload["diningOption"] = dining_option

    return order_payload


def _build_selections(
    order_state: Dict[str, Any],
    resolver: GuidResolver,
) -> List[Dict[str, Any]]:
    """Build Toast selections (line items) from order items.

    Items without a Toast GUID mapping are skipped with a warning.

    Returns:
        List of Toast selection dicts.
    """
    selections = []
    items = order_state.get("items", [])

    for item in items:
        selection = _build_single_selection(item, resolver)
        if selection:
            selections.append(selection)

    return selections


def _build_single_selection(
    item: Dict[str, Any],
    resolver: GuidResolver,
) -> Optional[Dict[str, Any]]:
    """Build a single Toast selection from an order item.

    Returns:
        Toast selection dict, or None if the item can't be mapped.
    """
    menu_item_id = item.get("menu_item_id")
    if not menu_item_id:
        logger.debug("Skipping item without menu_item_id: %s", item.get("menu_item_name"))
        return None

    toast_guid = resolver.resolve_menu_item(menu_item_id)
    if not toast_guid:
        logger.warning(
            "No Toast GUID for menu item #%d (%s); skipping",
            menu_item_id,
            item.get("menu_item_name"),
        )
        return None

    quantity = item.get("quantity", 1)

    selection: Dict[str, Any] = {
        "entityType": "MenuItemSelection",
        "externalId": _generate_external_id("sel-"),
        "itemGroup": {"guid": toast_guid},
        "item": {"guid": toast_guid},
        "quantity": quantity,
        "modifiers": _build_modifiers(item, resolver),
    }

    # Add special instructions if present
    special = item.get("special_instructions") or item.get("notes")
    if special:
        selection["specialRequest"] = str(special)[:255]

    return selection


def _build_modifiers(
    item: Dict[str, Any],
    resolver: GuidResolver,
) -> List[Dict[str, Any]]:
    """Build Toast modifier selections from item modifiers/ingredients.

    Looks at item_config.modifiers for structured modifier data.

    Returns:
        List of Toast modifier dicts.
    """
    modifiers = []

    # Extract modifier entries from item_config
    item_config = item.get("item_config", {})
    modifier_entries = item_config.get("modifiers", [])

    for mod in modifier_entries:
        if not isinstance(mod, dict):
            continue

        ingredient_id = mod.get("ingredient_id")
        if not ingredient_id:
            continue

        toast_guid = resolver.resolve_ingredient(ingredient_id)
        if not toast_guid:
            logger.debug(
                "No Toast GUID for ingredient #%d (%s); skipping modifier",
                ingredient_id,
                mod.get("display_name", mod.get("slug", "unknown")),
            )
            continue

        modifier_entry = {
            "entityType": "MenuItemSelection",
            "externalId": _generate_external_id("mod-"),
            "itemGroup": {"guid": toast_guid},
            "item": {"guid": toast_guid},
            "quantity": mod.get("quantity", 1),
        }
        modifiers.append(modifier_entry)

    return modifiers


def _build_dining_option(
    order_state: Dict[str, Any],
    resolver: GuidResolver,
) -> Optional[Dict[str, str]]:
    """Map our order_type (pickup/delivery) to a Toast dining option GUID.

    Uses a convention-based lookup: dining_option entity type with
    local_id 1 for pickup, 2 for delivery.

    Returns:
        Toast dining option reference dict, or None if not mapped.
    """
    order_type = order_state.get("order_type", "pickup")

    # Convention: local_id 1 = pickup, 2 = delivery
    local_id = 1 if order_type == "pickup" else 2
    toast_guid = resolver.resolve_dining_option(local_id)

    if toast_guid:
        return {"guid": toast_guid}

    logger.debug("No Toast dining option GUID for order_type=%s", order_type)
    return None


def _build_customer(order_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build Toast customer info from our order state.

    Returns:
        Toast customer dict, or None if no customer info available.
    """
    customer_data = order_state.get("customer", {})
    if not customer_data:
        return None

    name = customer_data.get("name", "")
    phone = customer_data.get("phone")
    email = customer_data.get("email")

    # Toast expects firstName / lastName
    name_parts = name.split(maxsplit=1) if name else [""]
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    customer: Dict[str, Any] = {}

    if first_name:
        customer["firstName"] = first_name
    if last_name:
        customer["lastName"] = last_name
    if phone:
        customer["phone"] = phone
    if email:
        customer["email"] = email

    return customer if customer else None
