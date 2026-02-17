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

from ..db.models import Order, OrderItem, OrderStatusHistory, Store
from ..schemas.enums import OrderStatus


logger = logging.getLogger(__name__)


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
    city_tax_rate = 0.0
    state_tax_rate = 0.0
    delivery_fee = 0.0

    if store_id:
        store = db.query(Store).filter(Store.store_id == store_id).first()
        if store:
            city_tax_rate = store.city_tax_rate or 0.0
            state_tax_rate = store.state_tax_rate or 0.0
            delivery_fee = store.delivery_fee if store.delivery_fee is not None else 0.0

    return TaxInfo(
        city_tax_rate=city_tax_rate,
        state_tax_rate=state_tax_rate,
        delivery_fee=delivery_fee,
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

    # Create or update Order row
    existing_id = order_state.get("db_order_id")
    order: Order | None = None

    if existing_id:
        order = db.get(Order, existing_id)
        if order is None:
            existing_id = None

    if order:
        # Update existing order
        order.status = OrderStatus.CONFIRMED
        order.customer_name = customer.name
        order.phone = customer.phone
        order.customer_email = customer.email
        order.pickup_time = customer.pickup_time
        order.subtotal = totals.subtotal
        order.city_tax = totals.city_tax
        order.state_tax = totals.state_tax
        order.delivery_fee = totals.delivery_fee
        order.total_price = totals.total
        order.store_id = store_id
        order.order_type = order_type
        order.delivery_address = order_state.get("delivery_address")
        order.payment_method = order_state.get("payment_method")
        order.special_instructions = order_state.get("special_instructions")
    else:
        # Create new order
        order = Order(
            status=OrderStatus.CONFIRMED,
            customer_name=customer.name,
            phone=customer.phone,
            customer_email=customer.email,
            pickup_time=customer.pickup_time,
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
        db.add(order)
        db.flush()
        order_state["db_order_id"] = order.id

        # Add order items for new orders
        _add_order_items(db, order, items)

    db.commit()
    logger.info("Order #%d persisted (status: confirmed)", order.id)
    return order


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
    order.payment_status = "pending_payment"
    db.commit()
    logger.info("Order #%d linked to Stripe session %s", order_id, stripe_session_id)
    return True


# =============================================================================
# Order Status Transitions (Fulfillment)
# =============================================================================

# Valid forward transitions: status -> set of allowed next statuses
VALID_TRANSITIONS: dict[str, set] = {
    OrderStatus.PENDING: {OrderStatus.PENDING_PAYMENT, OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.PENDING_PAYMENT: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY, OrderStatus.CANCELLED},
    OrderStatus.READY: {OrderStatus.COMPLETED, OrderStatus.CANCELLED},
    OrderStatus.COMPLETED: set(),  # Terminal state
    OrderStatus.CANCELLED: set(),  # Terminal state
}


class InvalidStatusTransition(Exception):
    """Raised when an order status transition is not allowed."""
    pass


def transition_order_status(
    db: Session,
    order_id: int,
    new_status: str,
    changed_by: str | None = None,
    note: str | None = None,
    cancellation_reason: str | None = None,
) -> Order:
    """Transition an order to a new status with validation.

    Records the transition in order_status_history and updates timestamp
    columns (ready_at, completed_at, cancelled_at) as appropriate.

    Args:
        db: Database session
        order_id: The order to transition
        new_status: Target status
        changed_by: Username or "system" for audit trail
        note: Optional note for the history entry
        cancellation_reason: Reason if cancelling (stored on order)

    Returns:
        The updated Order

    Raises:
        ValueError: If order not found
        InvalidStatusTransition: If the transition is not allowed
    """
    order = db.get(Order, order_id)
    if not order:
        raise ValueError(f"Order #{order_id} not found")

    old_status = order.status
    allowed = VALID_TRANSITIONS.get(old_status, set())

    if new_status not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition order #{order_id} from '{old_status}' to '{new_status}'. "
            f"Allowed: {allowed or 'none (terminal state)'}"
        )

    now = datetime.now(timezone.utc)

    # Update the order status
    order.status = new_status

    # Set timestamp columns based on new status
    if new_status == OrderStatus.READY:
        order.ready_at = now
    elif new_status == OrderStatus.COMPLETED:
        order.completed_at = now
    elif new_status == OrderStatus.CANCELLED:
        order.cancelled_at = now
        if cancellation_reason:
            order.cancellation_reason = cancellation_reason

    # Record in history
    history_entry = OrderStatusHistory(
        order_id=order_id,
        from_status=old_status,
        to_status=new_status,
        changed_by=changed_by,
        note=note or cancellation_reason,
    )
    db.add(history_entry)
    db.commit()

    logger.info(
        "Order #%d transitioned: %s -> %s (by %s)",
        order_id, old_status, new_status, changed_by or "unknown",
    )

    # Send notifications for key transitions
    _send_transition_notifications(db, order, new_status)

    return order


def _send_transition_notifications(db: Session, order: Order, new_status: str) -> None:
    """Send customer notifications on key status transitions.

    Best-effort: failures are logged but don't block the transition.
    """
    try:
        from ..notification_service import notify_order_ready, notify_order_cancelled
        from ..db.models import Company

        company = db.query(Company).first()
        store_name = company.name if company else "OrderBot"

        if new_status == OrderStatus.READY:
            notify_order_ready(db, order, store_name)
        elif new_status == OrderStatus.CANCELLED:
            notify_order_cancelled(db, order, store_name)
    except Exception as e:
        logger.error("Failed to send transition notification for order #%d: %s", order.id, e)


def update_order_toast_status(
    db: Session,
    order_id: int,
    toast_status: str,
    toast_guid: str | None = None,
) -> bool:
    """Update Toast POS tracking fields on an order.

    Args:
        db: Database session
        order_id: The order ID to update
        toast_status: Toast sync status (pending_sync, submitted, failed, synced)
        toast_guid: Optional Toast order GUID

    Returns:
        True if updated, False if order not found
    """
    order = db.get(Order, order_id)
    if not order:
        logger.warning("Cannot set Toast status: order #%d not found", order_id)
        return False

    order.toast_order_status = toast_status
    if toast_guid:
        order.toast_order_guid = toast_guid
    if toast_status == "submitted":
        order.toast_submitted_at = datetime.now(timezone.utc)

    db.commit()
    logger.info("Order #%d Toast status updated to '%s'", order_id, toast_status)
    return True


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
