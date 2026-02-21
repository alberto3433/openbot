"""
Square Order Payload Builder
=================================

Translates our internal order state dict into the JSON payload required by
the Square CreateOrder API (POST /v2/orders).

Uses ad-hoc line items (item name + price inline, no catalog IDs). This is
the simplest integration path — no Square Catalog sync required.

Square order structure:
    Order → line_items, taxes, fulfillments
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..config import SQUARE_LOCATION_ID

logger = logging.getLogger(__name__)


def build_square_order(
    db: Session,
    order_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a Square API CreateOrder payload from our internal order state.

    Args:
        db: Database session (for store lookups)
        order_state: Internal order state dict with items, customer, etc.

    Returns:
        Square CreateOrder payload dict, or None if build fails.
    """
    db_order_id = order_state.get("db_order_id")
    if not db_order_id:
        logger.warning("Cannot build Square order: no db_order_id")
        return None

    # Resolve Square location ID (store-level override, then env fallback)
    location_id = _resolve_location_id(db, order_state.get("store_id"))
    if not location_id:
        logger.warning(
            "No Square location ID for order #%s (store: %s)",
            db_order_id, order_state.get("store_id"),
        )
        return None

    # Build line items
    line_items = _build_line_items(order_state)
    if not line_items:
        logger.warning("No line items for Square order #%s", db_order_id)
        return None

    # Build taxes
    taxes = _build_taxes(db, order_state.get("store_id"))

    # Build fulfillment
    fulfillment = _build_fulfillment(order_state)

    order_body: dict[str, Any] = {
        "location_id": location_id,
        "reference_id": str(db_order_id),
        "source": {"name": "Orderbot"},
        "line_items": line_items,
    }

    if taxes:
        order_body["taxes"] = taxes
        # Apply taxes to all line items
        tax_uids = [t["uid"] for t in taxes]
        for item in line_items:
            item["applied_taxes"] = [{"tax_uid": uid} for uid in tax_uids]

    if fulfillment:
        order_body["fulfillments"] = [fulfillment]

    return {
        "idempotency_key": f"orderbot-{db_order_id}",
        "order": order_body,
    }


def _resolve_location_id(db: Session, store_id: str | None) -> str | None:
    """Resolve Square location ID from store model or env fallback.

    Args:
        db: Database session
        store_id: Our internal store identifier

    Returns:
        Square location ID string, or None if not found.
    """
    if store_id:
        try:
            from ..db.models.company import Store
            store = db.query(Store).filter(Store.store_id == store_id).first()
            if store and store.square_location_id:
                return store.square_location_id
        except (AttributeError, ImportError) as e:
            logger.debug("Could not look up store square_location_id: %s", e)

    # Fall back to environment variable
    return SQUARE_LOCATION_ID or None


def _build_line_items(order_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Build Square ad-hoc line items from order items.

    Returns:
        List of Square line item dicts.
    """
    line_items = []
    items = order_state.get("items", [])

    for item in items:
        display_name = (
            item.get("display_name")
            or item.get("menu_item_name")
            or "Item"
        )
        quantity = item.get("quantity", 1)
        unit_price = item.get("unit_price", 0)

        line_item: dict[str, Any] = {
            "name": display_name,
            "quantity": str(quantity),  # Square wants string
            "base_price_money": {
                "amount": round(unit_price * 100),  # int cents
                "currency": "USD",
            },
        }

        # Add special instructions as note
        special = item.get("special_instructions")
        if isinstance(special, list):
            note = "; ".join(str(s) for s in special if s)
            if note:
                line_item["note"] = note[:500]
        elif special:
            line_item["note"] = str(special)[:500]

        line_items.append(line_item)

    return line_items


def _build_taxes(db: Session, store_id: str | None) -> list[dict[str, Any]]:
    """Build Square tax entries from store tax rates.

    Returns:
        List of Square tax dicts (may be empty).
    """
    taxes = []

    if not store_id:
        return taxes

    try:
        from ..db.models.company import Store
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if not store:
            return taxes

        if store.city_tax_rate and store.city_tax_rate > 0:
            taxes.append({
                "uid": "city-tax",
                "name": "City Tax",
                "percentage": str(round(store.city_tax_rate * 100, 4)),
                "scope": "ORDER",
                "type": "ADDITIVE",
            })

        if store.state_tax_rate and store.state_tax_rate > 0:
            taxes.append({
                "uid": "state-tax",
                "name": "State Tax",
                "percentage": str(round(store.state_tax_rate * 100, 4)),
                "scope": "ORDER",
                "type": "ADDITIVE",
            })
    except (AttributeError, ImportError) as e:
        logger.debug("Could not look up store tax rates: %s", e)

    return taxes


def _build_fulfillment(order_state: dict[str, Any]) -> dict[str, Any] | None:
    """Build Square fulfillment entry from order state.

    Returns:
        Square fulfillment dict, or None if no customer info.
    """
    customer = order_state.get("customer", {})
    if not customer:
        return None

    name = customer.get("name", "")
    phone = customer.get("phone")
    email = customer.get("email")

    recipient: dict[str, Any] = {}
    if name:
        recipient["display_name"] = name
    if phone:
        recipient["phone_number"] = phone
    if email:
        recipient["email_address"] = email

    if not recipient:
        return None

    order_type = order_state.get("order_type", "pickup")
    special_instructions = order_state.get("special_instructions", "")

    if order_type == "delivery":
        delivery_address = order_state.get("delivery_address", "")
        if delivery_address:
            recipient["address"] = {
                "address_line_1": delivery_address,
                "country": "US",
            }
        fulfillment: dict[str, Any] = {
            "type": "DELIVERY",
            "state": "PROPOSED",
            "delivery_details": {
                "recipient": recipient,
                "schedule_type": "ASAP",
            },
        }
        if special_instructions:
            fulfillment["delivery_details"]["note"] = str(special_instructions)[:500]
        return fulfillment

    # Default: pickup
    fulfillment = {
        "type": "PICKUP",
        "state": "PROPOSED",
        "pickup_details": {
            "recipient": recipient,
            "schedule_type": "ASAP",
        },
    }
    if special_instructions:
        fulfillment["pickup_details"]["note"] = str(special_instructions)[:500]
    return fulfillment
