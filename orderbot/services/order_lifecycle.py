"""
Order Lifecycle Service for Orderbot
========================================

Order status transitions and lifecycle management, extracted from order.py.
Handles status validation, transition recording, and notifications.

Functions:
----------
- transition_order_status: Validate and execute order status transitions
- update_order_toast_status: Update Toast POS tracking fields

Exceptions:
-----------
- InvalidStatusTransition: Raised when a status transition is not allowed

Constants:
----------
- VALID_TRANSITIONS: Map of allowed status transitions
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..db.models import Order, OrderStatusHistory
from ..exceptions import NOTIFICATION_ERRORS
from ..schemas.enums import OrderStatus, ToastOrderStatus


logger = logging.getLogger(__name__)


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
    except NOTIFICATION_ERRORS as e:
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
    if toast_status == ToastOrderStatus.SUBMITTED:
        order.toast_submitted_at = datetime.now(timezone.utc)

    db.commit()
    logger.info("Order #%d Toast status updated to '%s'", order_id, toast_status)
    return True
