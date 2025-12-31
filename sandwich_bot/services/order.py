"""
Order Persistence Service for Sandwich Bot
===========================================

This module contains functions for persisting orders to the database.
These are called when orders are confirmed or when payment links are
requested during the checkout flow.

Key Functions:
--------------
- persist_pending_order: Save order before payment confirmation
- persist_confirmed_order: Save/update order after confirmation

Order Lifecycle:
----------------
1. Customer builds order in session (not persisted)
2. When payment link requested -> persist_pending_order (status: pending_payment)
3. When order confirmed -> persist_confirmed_order (status: confirmed)

Tax Calculation:
----------------
Both functions calculate taxes based on store configuration:
- city_tax = subtotal * city_tax_rate
- state_tax = subtotal * state_tax_rate
- delivery_fee added for delivery orders
- total = subtotal + city_tax + state_tax + delivery_fee

Idempotency:
------------
persist_confirmed_order is idempotent:
- If order_state has db_order_id and order exists, updates it
- Otherwise creates new order and stores id in order_state

Item Mapping:
-------------
Order items are mapped from the session format to database format,
handling various item types (sandwiches, bagels, coffees) with their
specific configurations.
"""

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from ..models import Order, OrderItem, Store


logger = logging.getLogger(__name__)


def persist_pending_order(
    db: Session,
    order_state: Dict[str, Any],
    slots: Optional[Dict[str, Any]] = None,
    store_id: Optional[str] = None,
) -> Optional[Order]:
    """
    Persist an order in pending_payment status (before confirmation).

    Used when a payment link is requested so we have an order ID for the email.
    If an order already exists (db_order_id set), returns that order.

    Args:
        db: Database session
        order_state: Current order state dict
        slots: Optional slots from the LLM action
        store_id: Optional store identifier

    Returns:
        The created or existing Order object
    """
    # If order already persisted, just return it
    existing_id = order_state.get("db_order_id")
    if existing_id:
        order = db.get(Order, existing_id)
        if order:
            return order

    slots = slots or {}
    items = order_state.get("items") or []
    customer_block = order_state.get("customer") or {}

    def first_non_empty(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    customer_name = first_non_empty(
        customer_block.get("name"),
        order_state.get("customer_name"),
        order_state.get("name"),
        slots.get("customer_name"),
        slots.get("name"),
    )

    phone = first_non_empty(
        customer_block.get("phone"),
        order_state.get("phone"),
        slots.get("phone"),
        slots.get("phone_number"),
    )

    customer_email = first_non_empty(
        customer_block.get("email"),
        order_state.get("customer_email"),
        slots.get("customer_email"),
        slots.get("email"),
    )

    # Calculate subtotal from line items
    subtotal = sum((it.get("line_total") or 0.0) for it in items)

    # Get tax rates from store
    city_tax_rate = 0.0
    state_tax_rate = 0.0
    delivery_fee = 2.99  # Default delivery fee

    if store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            city_tax_rate = store.city_tax_rate or 0.0
            state_tax_rate = store.state_tax_rate or 0.0

    # Calculate taxes
    city_tax = subtotal * city_tax_rate
    state_tax = subtotal * state_tax_rate

    order_type = order_state.get("order_type", "pickup")
    delivery_address = order_state.get("delivery_address")

    # Add delivery fee if delivery order
    actual_delivery_fee = delivery_fee if order_type == "delivery" else 0.0

    # Total price = subtotal + taxes + delivery fee
    total_price = subtotal + city_tax + state_tax + actual_delivery_fee

    # Store tax breakdown in order state for reference
    order_state["checkout_state"] = order_state.get("checkout_state", {})
    order_state["checkout_state"]["subtotal"] = subtotal
    order_state["checkout_state"]["city_tax"] = city_tax
    order_state["checkout_state"]["state_tax"] = state_tax
    order_state["checkout_state"]["delivery_fee"] = actual_delivery_fee
    order_state["checkout_state"]["total"] = total_price

    # Create order with pending_payment status
    order = Order(
        status="pending_payment",
        customer_name=customer_name,
        phone=phone,
        customer_email=customer_email,
        subtotal=subtotal,
        city_tax=city_tax,
        state_tax=state_tax,
        delivery_fee=actual_delivery_fee,
        total_price=total_price,
        store_id=store_id,
        order_type=order_type,
        delivery_address=delivery_address,
        payment_status="pending",
        payment_method=order_state.get("payment_method"),
    )
    db.add(order)
    db.flush()
    order_state["db_order_id"] = order.id

    # Add order items
    _add_order_items(db, order, items)

    db.commit()
    logger.info("Pending order #%d created for payment link", order.id)
    return order


def persist_confirmed_order(
    db: Session,
    order_state: Dict[str, Any],
    slots: Optional[Dict[str, Any]] = None,
    store_id: Optional[str] = None,
) -> Optional[Order]:
    """
    Persist a confirmed order + its items to the database.

    Idempotent:
      - If order_state has a db_order_id and that row exists, we UPDATE it.
      - Otherwise, we CREATE a new Order and store its id back into order_state.

    Args:
        db: Database session
        order_state: Current order state dict
        slots: Optional slots from the LLM action
        store_id: Optional store identifier

    Returns:
        The created or updated Order object, or None if order not confirmed
    """
    if order_state.get("status") != "confirmed":
        return None  # nothing to persist

    slots = slots or {}
    items = order_state.get("items") or []
    customer_block = order_state.get("customer") or {}

    def first_non_empty(*vals):
        for v in vals:
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    customer_name = first_non_empty(
        customer_block.get("name"),
        order_state.get("customer_name"),
        order_state.get("name"),
        slots.get("customer_name"),
        slots.get("name"),
    )

    phone = first_non_empty(
        customer_block.get("phone"),
        order_state.get("phone"),
        slots.get("phone"),
        slots.get("phone_number"),
    )

    customer_email = first_non_empty(
        customer_block.get("email"),
        order_state.get("customer_email"),
        slots.get("customer_email"),
        slots.get("email"),
    )

    pickup_time = first_non_empty(
        customer_block.get("pickup_time"),
        order_state.get("pickup_time"),
        slots.get("pickup_time"),
        slots.get("pickup_time_str"),
    )

    # Calculate subtotal from line items
    subtotal = sum((it.get("line_total") or 0.0) for it in items)

    # Get tax rates from store
    city_tax_rate = 0.0
    state_tax_rate = 0.0
    delivery_fee = 2.99  # Default delivery fee

    if store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            city_tax_rate = store.city_tax_rate or 0.0
            state_tax_rate = store.state_tax_rate or 0.0

    # Calculate taxes
    city_tax = subtotal * city_tax_rate
    state_tax = subtotal * state_tax_rate

    # Add delivery fee if delivery order
    order_type = order_state.get("order_type", "pickup")
    actual_delivery_fee = delivery_fee if order_type == "delivery" else 0.0

    # Total price = subtotal + taxes + delivery fee
    total_price = subtotal + city_tax + state_tax + actual_delivery_fee

    # Store tax breakdown in order state for reference
    order_state["checkout_state"] = order_state.get("checkout_state", {})
    order_state["checkout_state"]["subtotal"] = subtotal
    order_state["checkout_state"]["city_tax"] = city_tax
    order_state["checkout_state"]["state_tax"] = state_tax
    order_state["checkout_state"]["delivery_fee"] = actual_delivery_fee
    order_state["checkout_state"]["total"] = total_price

    logger.info(
        "Order total: subtotal=$%.2f, city_tax=$%.2f (%.3f%%), state_tax=$%.2f (%.3f%%), delivery=$%.2f, total=$%.2f",
        subtotal, city_tax, city_tax_rate * 100, state_tax, state_tax_rate * 100, actual_delivery_fee, total_price
    )

    # Create or update Order row
    existing_id = order_state.get("db_order_id")
    order: Optional[Order] = None

    if existing_id:
        order = db.get(Order, existing_id)
        if order is None:
            existing_id = None

    if order:
        # Update existing order
        order.status = "confirmed"
        order.customer_name = customer_name
        order.phone = phone
        order.customer_email = customer_email
        order.pickup_time = pickup_time
        order.subtotal = subtotal
        order.city_tax = city_tax
        order.state_tax = state_tax
        order.delivery_fee = actual_delivery_fee
        order.total_price = total_price
        order.store_id = store_id
        order.order_type = order_type
        order.delivery_address = order_state.get("delivery_address")
        order.payment_method = order_state.get("payment_method")
    else:
        # Create new order
        order = Order(
            status="confirmed",
            customer_name=customer_name,
            phone=phone,
            customer_email=customer_email,
            pickup_time=pickup_time,
            subtotal=subtotal,
            city_tax=city_tax,
            state_tax=state_tax,
            delivery_fee=actual_delivery_fee,
            total_price=total_price,
            store_id=store_id,
            order_type=order_type,
            delivery_address=order_state.get("delivery_address"),
            payment_method=order_state.get("payment_method"),
        )
        db.add(order)
        db.flush()
        order_state["db_order_id"] = order.id

        # Add order items for new orders
        _add_order_items(db, order, items)

    db.commit()
    logger.info("Order #%d persisted (status: confirmed)", order.id)
    return order


def _add_order_items(db: Session, order: Order, items: list) -> None:
    """Add order items to an order.

    All item-specific configuration (bread, protein, toasted, etc.) is stored
    in the item_config JSON column. Only common fields are stored as direct columns.
    """
    for it in items:
        # Prefer display_name which includes all item details (bagel choice, toasted, etc.)
        # Fall back to menu_item_name for compatibility
        menu_item_name = (
            it.get("display_name")
            or it.get("menu_item_name")
            or it.get("name")
            or it.get("item_type")
            or "Unknown item"
        )

        # Include side choice in display name (for items without display_name)
        if not it.get("display_name"):
            side_choice = it.get("side_choice")
            bagel_choice = it.get("bagel_choice")
            if side_choice == "bagel" and bagel_choice:
                menu_item_name = f"{menu_item_name} with {bagel_choice} bagel"
            elif side_choice == "fruit_salad":
                menu_item_name = f"{menu_item_name} with fruit salad"

        item_type = it.get("item_type")
        quantity = it.get("quantity", 1)
        line_total = it.get("line_total", 0.0)
        unit_price = line_total / quantity if quantity > 0 else line_total

        # Get item_config - all item-specific details are stored here
        item_config = it.get("item_config") or {}

        # Ensure item_type is in item_config for reads that merge it
        item_config["item_type"] = item_type

        order_item = OrderItem(
            order_id=order.id,
            menu_item_name=menu_item_name,
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
            item_config=item_config,  # SQLAlchemy JSON column handles serialization
            notes=it.get("notes"),
        )
        db.add(order_item)
