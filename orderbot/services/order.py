"""
Order Persistence Service for Orderbot
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

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Order, OrderItem
from ..schemas.enums import OrderStatus, PaymentStatus
from .store_service import build_store_info


logger = logging.getLogger(__name__)

__all__ = [
    "persist_pending_order",
    "persist_confirmed_order",
    "update_order_stripe_session",
    "transition_order_status",
    "InvalidStatusTransition",
    "update_order_toast_status",
]


# =============================================================================
# Helper Data Structures
# =============================================================================

@dataclass
class CustomerInfo:
    """Extracted customer information."""
    name: str | None
    phone: str | None
    email: str | None
    pickup_time: str | None = None


@dataclass
class TaxInfo:
    """Store tax rates and fees."""
    city_tax_rate: float
    state_tax_rate: float
    delivery_fee: float


@dataclass
class OrderTotals:
    """Calculated order totals."""
    subtotal: float
    city_tax: float
    state_tax: float
    delivery_fee: float
    total: float


# =============================================================================
# Helper Functions
# =============================================================================

def _first_non_empty(*vals: Any) -> str | None:
    """Return the first non-empty string value from the arguments."""
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_customer_info(
    order_state: dict[str, Any],
    slots: dict[str, Any],
    include_pickup_time: bool = False,
) -> CustomerInfo:
    """Extract customer information from order state and slots.

    Args:
        order_state: Current order state dict
        slots: Slots from the LLM action
        include_pickup_time: Whether to extract pickup_time

    Returns:
        CustomerInfo with extracted values
    """
    customer_block = order_state.get("customer") or {}

    name = _first_non_empty(
        customer_block.get("name"),
        order_state.get("customer_name"),
        order_state.get("name"),
        slots.get("customer_name"),
        slots.get("name"),
    )

    phone = _first_non_empty(
        customer_block.get("phone"),
        order_state.get("phone"),
        slots.get("phone"),
        slots.get("phone_number"),
    )

    email = _first_non_empty(
        customer_block.get("email"),
        order_state.get("customer_email"),
        slots.get("customer_email"),
        slots.get("email"),
    )

    pickup_time = None
    if include_pickup_time:
        pickup_time = _first_non_empty(
            customer_block.get("pickup_time"),
            order_state.get("pickup_time"),
            slots.get("pickup_time"),
            slots.get("pickup_time_str"),
        )

    return CustomerInfo(name=name, phone=phone, email=email, pickup_time=pickup_time)


def _get_store_tax_info(db: Session, store_id: str | None) -> TaxInfo:
    """Get tax rates and delivery fee from store.

    Args:
        db: Database session
        store_id: Store identifier

    Returns:
        TaxInfo with rates and fees (defaults to 0 if store not found)
    """
    store_info = build_store_info(db, store_id)
    return TaxInfo(
        city_tax_rate=store_info["city_tax_rate"],
        state_tax_rate=store_info["state_tax_rate"],
        delivery_fee=store_info.get("delivery_fee", 0.0),
    )


def _calculate_order_totals(
    subtotal: float,
    tax_info: TaxInfo,
    is_delivery: bool,
) -> OrderTotals:
    """Calculate order totals including taxes and delivery fee.

    Delegates to tax_utils.calculate_order_total for consistent rounding.

    Args:
        subtotal: Order subtotal
        tax_info: Tax rates and delivery fee from store
        is_delivery: Whether this is a delivery order

    Returns:
        OrderTotals with calculated values
    """
    from .tax_utils import calculate_order_total

    store_info = {
        "city_tax_rate": tax_info.city_tax_rate,
        "state_tax_rate": tax_info.state_tax_rate,
        "delivery_fee": tax_info.delivery_fee,
    }
    result = calculate_order_total(subtotal, store_info, is_delivery=is_delivery)

    return OrderTotals(
        subtotal=result["subtotal"],
        city_tax=result["city_tax"],
        state_tax=result["state_tax"],
        delivery_fee=result["delivery_fee"],
        total=result["total"],
    )


def _update_checkout_state(order_state: dict[str, Any], totals: OrderTotals) -> None:
    """Update checkout_state in order_state with calculated totals.

    Args:
        order_state: Order state dict to update (mutated in place)
        totals: Calculated order totals
    """
    order_state["checkout_state"] = order_state.get("checkout_state", {})
    order_state["checkout_state"]["subtotal"] = totals.subtotal
    order_state["checkout_state"]["city_tax"] = totals.city_tax
    order_state["checkout_state"]["state_tax"] = totals.state_tax
    order_state["checkout_state"]["delivery_fee"] = totals.delivery_fee
    order_state["checkout_state"]["total"] = totals.total


def persist_pending_order(
    db: Session,
    order_state: dict[str, Any],
    slots: dict[str, Any] | None = None,
    store_id: str | None = None,
) -> Order | None:
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

    # Extract customer info and calculate totals using helpers
    customer = _extract_customer_info(order_state, slots)
    subtotal = sum((it.get("line_total") or 0.0) for it in items)
    tax_info = _get_store_tax_info(db, store_id)
    order_type = order_state.get("order_type", "pickup")
    is_delivery = order_type == "delivery"
    totals = _calculate_order_totals(subtotal, tax_info, is_delivery)

    # Store tax breakdown in order state for reference
    _update_checkout_state(order_state, totals)

    # Create order with pending_payment status
    order = Order(
        status=OrderStatus.PENDING_PAYMENT,
        customer_name=customer.name,
        phone=customer.phone,
        customer_email=customer.email,
        subtotal=totals.subtotal,
        city_tax=totals.city_tax,
        state_tax=totals.state_tax,
        delivery_fee=totals.delivery_fee,
        total_price=totals.total,
        store_id=store_id,
        order_type=order_type,
        delivery_address=order_state.get("delivery_address"),
        payment_status="pending",
        payment_method=order_state.get("payment_method"),
        special_instructions=order_state.get("special_instructions"),
    )
    db.add(order)
    db.flush()
    order_state["db_order_id"] = order.id

    # Add order items
    _add_order_items(db, order, items)

    db.commit()
    logger.info("Pending order #%d created for payment link", order.id)
    return order


def build_email_kwargs_from_order(db: Session, order: Order) -> dict:
    """Build common email kwargs from an Order and its items.

    Extracts the data needed by ``send_receipt_email`` /
    ``send_expired_link_email`` from a persisted ``Order`` row.
    """
    from .store_service import get_company
    from ..db.models import Store

    # Prefer specific Store.name (e.g., "Zucker's - East Brunswick")
    # over Company.name (e.g., "Zucker's Bagels")
    store_name = None
    if order.store_id:
        store = db.query(Store).filter(Store.store_id == order.store_id).first()
        if store:
            store_name = store.name
    if not store_name:
        company = get_company(db)
        store_name = company.name if company else "OrderBot"

    items_list = []
    for oi in order.items:
        config = oi.item_config or {}
        items_list.append({
            "display_name": oi.menu_item_name,
            "menu_item_name": oi.menu_item_name,
            "quantity": oi.quantity,
            "line_total": oi.line_total,
            "unit_price": oi.unit_price,
            "base_price": oi.unit_price,
            "modifiers": config.get("modifiers", []),
            "free_details": config.get("free_details", []),
        })

    return dict(
        to_email=order.customer_email,
        order_id=order.id,
        amount=order.total_price or 0.0,
        store_name=store_name,
        customer_name=order.customer_name,
        customer_phone=order.phone,
        order_type=order.order_type,
        items=items_list,
        subtotal=order.subtotal,
        city_tax=order.city_tax or 0,
        state_tax=order.state_tax or 0,
        delivery_fee=order.delivery_fee or 0,
    )


def persist_confirmed_order(
    db: Session,
    order_state: dict[str, Any],
    slots: dict[str, Any] | None = None,
    store_id: str | None = None,
) -> Order | None:
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
    if order_state.get("status") != OrderStatus.CONFIRMED:
        return None  # nothing to persist

    slots = slots or {}
    items = order_state.get("items") or []

    # Extract customer info and calculate totals using helpers
    customer = _extract_customer_info(order_state, slots, include_pickup_time=True)
    subtotal = sum((it.get("line_total") or 0.0) for it in items)
    tax_info = _get_store_tax_info(db, store_id)
    order_type = order_state.get("order_type", "pickup")
    is_delivery = order_type == "delivery"
    totals = _calculate_order_totals(subtotal, tax_info, is_delivery)

    # Store tax breakdown in order state for reference
    _update_checkout_state(order_state, totals)

    logger.info(
        "Order total: subtotal=$%.2f, city_tax=$%.2f (%.3f%%), state_tax=$%.2f (%.3f%%), delivery=$%.2f, total=$%.2f",
        totals.subtotal, totals.city_tax, tax_info.city_tax_rate * 100,
        totals.state_tax, tax_info.state_tax_rate * 100, totals.delivery_fee, totals.total
    )

    order = _upsert_order_record(
        db, order_state, customer, totals, order_type, store_id, items,
    )
    _link_customer_record(db, order, customer, order_state, store_id=store_id)

    db.commit()
    logger.info("Order #%d persisted (status: confirmed)", order.id)
    return order


def _upsert_order_record(
    db: Session,
    order_state: dict[str, Any],
    customer: CustomerInfo,
    totals: OrderTotals,
    order_type: str,
    store_id: str | None,
    items: list[dict],
) -> Order:
    """Create or update the Order row and its items."""
    existing_id = order_state.get("db_order_id")
    order: Order | None = None

    if existing_id:
        order = db.get(Order, existing_id)

    estimated_ready_at = None
    if customer.pickup_time:
        try:
            estimated_ready_at = datetime.fromisoformat(customer.pickup_time)
        except (ValueError, TypeError):
            logger.warning("Could not parse pickup_time '%s' as ISO datetime", customer.pickup_time)

    common_fields = dict(
        status=OrderStatus.CONFIRMED,
        customer_name=customer.name,
        phone=customer.phone,
        customer_email=customer.email,
        pickup_time=customer.pickup_time,
        estimated_ready_at=estimated_ready_at,
        subtotal=totals.subtotal,
        city_tax=totals.city_tax,
        state_tax=totals.state_tax,
        delivery_fee=totals.delivery_fee,
        total_price=totals.total,
        store_id=store_id,
        order_type=order_type,
        delivery_address=order_state.get("delivery_address"),
        payment_method=order_state.get("payment_method"),
        special_instructions=order_state.get("special_instructions"),
    )

    if order:
        for key, value in common_fields.items():
            setattr(order, key, value)
    else:
        order = Order(**common_fields)
        db.add(order)
        db.flush()
        order_state["db_order_id"] = order.id
        _add_order_items(db, order, items)

    return order


def _link_customer_record(
    db: Session,
    order: Order,
    customer: CustomerInfo,
    order_state: dict[str, Any],
    store_id: str | None = None,
) -> None:
    """Find or create a Customer record and link it to the order."""
    try:
        from .customer_service import find_or_create_customer

        customer_record = find_or_create_customer(
            db, name=customer.name, phone=customer.phone, email=customer.email,
        )
        if customer_record:
            order.customer_id = customer_record.id
            order_state["customer_id"] = customer_record.id
            # Set preferred store on first order (don't overwrite explicit choice)
            if store_id and not customer_record.preferred_store_id:
                customer_record.preferred_store_id = store_id
                logger.info(
                    "Set preferred_store_id=%s for customer #%d",
                    store_id, customer_record.id,
                )
    except (ValueError, TypeError) as e:
        logger.warning("Failed to link customer to order #%d: %s", order.id, e)


def update_order_stripe_session(
    db: Session,
    order_id: int,
    stripe_session_id: str,
) -> bool:
    """Store the Stripe checkout session ID on an order.

    Called after creating a Stripe Checkout Session so the webhook can
    correlate the payment back to the order.

    Args:
        db: Database session
        order_id: The order ID to update
        stripe_session_id: Stripe checkout session ID (cs_...)

    Returns:
        True if updated, False if order not found
    """
    order = db.get(Order, order_id)
    if not order:
        logger.warning("Cannot set Stripe session: order #%d not found", order_id)
        return False

    order.stripe_checkout_session_id = stripe_session_id
    order.payment_status = PaymentStatus.PENDING_PAYMENT
    db.commit()
    logger.info("Order #%d linked to Stripe session %s", order_id, stripe_session_id)
    return True


# Re-exports for backward compatibility (moved to order_lifecycle.py)
from .order_lifecycle import (
    InvalidStatusTransition,
    transition_order_status,
    update_order_toast_status,
)


def _add_order_items(db: Session, order: Order, items: list) -> None:
    """Add order items to an order.

    All item-specific configuration (bread, protein, toasted, etc.) is stored
    in the item_config JSON column. Only common fields are stored as direct columns.
    """
    for it in items:
        # Prefer display_name which includes all item details (bagel choice, toasted, etc.)
        menu_item_name = (
            it.get("display_name")
            or it.get("menu_item_name")
            or it.get("name")
            or it.get("item_type")
            or "Unknown item"
        )

        # Include side choice in display name (for items without display_name)
        # Note: With child item model, the side (e.g., bagel) is a separate item
        # that gets its own display name. This just shows the side type on parent.
        if not it.get("display_name"):
            side_choice = it.get("side_choice")
            if side_choice:
                side_display = side_choice.replace("_", " ")
                menu_item_name = f"{menu_item_name} with {side_display}"

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
        )
        db.add(order_item)
