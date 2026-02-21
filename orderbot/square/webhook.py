"""
Square POS Webhook Handler
==============================

Receives fulfillment status update callbacks from Square and maps them to
internal order status transitions. Mounted at /webhooks/square (root level,
same pattern as Toast and Stripe).

Square sends webhooks for order fulfillment updates:
- PROPOSED → confirmed
- RESERVED → confirmed
- PREPARED → ready
- COMPLETED → completed
- CANCELED → cancelled
- FAILED → cancelled
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import SQUARE_WEBHOOK_SIGNATURE_KEY
from ..db import get_db
from ..db.models import Order, Company
from ..schemas.enums import PaymentStatus, SquareOrderStatus
from ..services.order import InvalidStatusTransition

logger = logging.getLogger(__name__)

square_webhook_router = APIRouter(tags=["Webhooks"])

# Map Square fulfillment states to our internal statuses
SQUARE_STATUS_MAP = {
    "PROPOSED": "confirmed",
    "RESERVED": "confirmed",
    "PREPARED": "ready",
    "COMPLETED": "completed",
    "CANCELED": "cancelled",
    "FAILED": "cancelled",
}


@square_webhook_router.post("/webhooks/square")
async def handle_square_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Handle incoming Square POS webhook events.

    Verifies the webhook signature (if secret configured), then processes
    order fulfillment status updates by mapping Square states to internal
    transitions.
    """
    payload = await request.body()

    # Verify signature if webhook secret is configured
    if SQUARE_WEBHOOK_SIGNATURE_KEY:
        signature = request.headers.get("x-square-hmacsha256-signature")
        if not signature:
            raise HTTPException(status_code=400, detail="Missing Square signature header")

        # Square HMAC uses the full notification URL + body
        notification_url = str(request.url)
        sign_body = notification_url.encode() + payload

        expected = hmac.new(
            SQUARE_WEBHOOK_SIGNATURE_KEY.encode(),
            sign_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            logger.warning("Square webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        import json
        event = json.loads(payload)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("type", "")
    logger.info("Square webhook received: %s", event_type)

    # Handle order fulfillment updates
    if event_type == "order.fulfillment.updated":
        _handle_fulfillment_update(event, db)
    elif event_type == "payment.completed":
        _handle_payment_completed(event, db)

    # Always return 200 to acknowledge receipt (even for unhandled events)
    return {"status": "ok"}


def _handle_fulfillment_update(event: dict, db: Session) -> None:
    """Process a Square order fulfillment update event."""
    data = event.get("data", {}).get("object", {})
    fulfillment_update = data.get("order_fulfillment_updated", {})

    square_order_id = fulfillment_update.get("order_id")
    if not square_order_id:
        logger.debug("Square webhook missing order_id: %s", event.get("event_id"))
        return

    # Look up order by Square order ID
    order = (
        db.query(Order)
        .filter(Order.square_order_id == square_order_id)
        .first()
    )

    if not order:
        logger.info(
            "Square order ID %s not found in local DB; ignoring", square_order_id
        )
        return

    # Get the latest fulfillment state from the update
    updates = fulfillment_update.get("fulfillment_update", [])
    if not updates:
        logger.debug("No fulfillment updates in Square event for order #%d", order.id)
        return

    # Use the most recent update
    latest = updates[-1]
    new_square_state = latest.get("new_state", "")
    new_status = SQUARE_STATUS_MAP.get(new_square_state)

    if not new_status:
        logger.debug(
            "Unmapped Square state '%s' for order #%d; ignoring",
            new_square_state, order.id,
        )
        order.square_order_status = f"square:{new_square_state}"
        db.commit()
        return

    # Attempt the status transition
    try:
        from ..services.order import transition_order_status
        transition_order_status(
            db=db,
            order_id=order.id,
            new_status=new_status,
            changed_by="square_webhook",
            note=f"Square state: {new_square_state}",
        )
        order.square_order_status = SquareOrderStatus.SYNCED
        db.commit()
        logger.info(
            "Order #%d transitioned to '%s' via Square webhook (Square state: %s)",
            order.id, new_status, new_square_state,
        )
    except (ValueError, RuntimeError, InvalidStatusTransition) as e:
        logger.warning(
            "Failed to transition order #%d to '%s' from Square: %s",
            order.id, new_status, e,
        )


def _handle_payment_completed(event: dict, db: Session) -> None:
    """Process a Square payment.completed event.

    When a customer completes payment via a Square Payment Link, Square
    sends this event. We look up the local order by the Square order ID
    embedded in the payment, mark it as paid, and send a receipt email.
    """
    from datetime import datetime, timezone

    data = event.get("data", {}).get("object", {})
    payment = data.get("payment", {})

    square_order_id = payment.get("order_id")
    if not square_order_id:
        logger.debug("Square payment.completed missing order_id: %s", event.get("event_id"))
        return

    # Look up order by Square order ID
    order = (
        db.query(Order)
        .filter(Order.square_order_id == square_order_id)
        .first()
    )

    if not order:
        logger.info(
            "Square order ID %s not found in local DB for payment.completed; ignoring",
            square_order_id,
        )
        return

    # Already paid — skip duplicate processing
    if order.payment_status == PaymentStatus.PAID:
        logger.debug("Order #%d already marked as paid; ignoring duplicate", order.id)
        return

    # Update payment status
    order.payment_status = PaymentStatus.PAID
    order.paid_at = datetime.now(timezone.utc)
    order.square_order_status = SquareOrderStatus.SYNCED
    db.commit()

    logger.info(
        "Order #%d payment confirmed via Square (square_order_id: %s)",
        order.id, square_order_id,
    )

    # Send receipt email
    _send_receipt_for_order(db, order)


def _send_receipt_for_order(db: Session, order: Order) -> None:
    """Send a receipt email for a paid order (reuses Stripe webhook pattern)."""
    if not order.customer_email:
        logger.debug("No email on order #%d; skipping receipt email", order.id)
        return

    try:
        from ..email_service import send_receipt_email, is_email_configured
        if not is_email_configured():
            return

        company = db.query(Company).first()
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

        send_receipt_email(
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
        logger.info("Receipt email sent for order #%d (via Square payment)", order.id)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.error("Failed to send receipt email for order #%d: %s", order.id, e)
