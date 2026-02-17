"""
Toast POS Webhook Handler
=============================

Receives status update callbacks from Toast POS and maps them to internal
order status transitions. Mounted at /webhooks/toast (root level, like Stripe).

Toast sends webhooks for fulfillment status changes:
- RECEIVED → confirmed
- IN_PREPARATION → preparing
- READY_FOR_PICKUP → ready
- CLOSED → completed
- VOIDED → cancelled
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import TOAST_WEBHOOK_SECRET
from ..db import get_db
from ..db.models import Order
from ..schemas.enums import ToastOrderStatus
from ..services.order import InvalidStatusTransition

logger = logging.getLogger(__name__)

toast_webhook_router = APIRouter(tags=["Webhooks"])

# Map Toast fulfillment statuses to our internal statuses
TOAST_STATUS_MAP = {
    "RECEIVED": "confirmed",
    "IN_PREPARATION": "preparing",
    "READY_FOR_PICKUP": "ready",
    "READY_FOR_DELIVERY": "ready",
    "CLOSED": "completed",
    "VOIDED": "cancelled",
}


@toast_webhook_router.post("/webhooks/toast")
async def handle_toast_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Handle incoming Toast POS webhook events.

    Verifies the webhook signature (if secret configured), then processes
    order status updates by mapping Toast statuses to internal transitions.
    """
    payload = await request.body()

    # Verify signature if webhook secret is configured
    if TOAST_WEBHOOK_SECRET:
        signature = request.headers.get("Toast-Signature") or request.headers.get("X-Toast-Signature")
        if not signature:
            raise HTTPException(status_code=400, detail="Missing Toast signature header")

        expected = hmac.new(
            TOAST_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected):
            logger.warning("Toast webhook signature verification failed")
            raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        import json
        event = json.loads(payload)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("eventType") or event.get("type", "")
    logger.info("Toast webhook received: %s", event_type)

    # Handle order status updates
    if "order" in event_type.lower() or "status" in event_type.lower():
        _handle_order_status(event, db)

    # Always return 200 to acknowledge receipt (even for unhandled events)
    return {"status": "ok"}


def _handle_order_status(event: dict, db: Session) -> None:
    """Process a Toast order status change event."""
    # Extract order GUID from the event payload
    order_data = event.get("data", {}).get("order", event.get("data", {}))
    toast_order_guid = order_data.get("guid") or event.get("orderGuid")

    if not toast_order_guid:
        logger.debug("Toast webhook missing order GUID: %s", event.get("eventType"))
        return

    # Look up order by Toast GUID
    order = (
        db.query(Order)
        .filter(Order.toast_order_guid == toast_order_guid)
        .first()
    )

    if not order:
        logger.info(
            "Toast order GUID %s not found in local DB; ignoring", toast_order_guid
        )
        return

    # Map Toast status to internal status
    toast_status = (
        order_data.get("fulfillmentStatus")
        or order_data.get("status")
        or event.get("status", "")
    )
    new_status = TOAST_STATUS_MAP.get(toast_status)

    if not new_status:
        logger.debug(
            "Unmapped Toast status '%s' for order #%d; ignoring",
            toast_status, order.id,
        )
        # Update toast_order_status to track the raw Toast status
        order.toast_order_status = f"toast:{toast_status}"
        db.commit()
        return

    # Attempt the status transition
    try:
        from ..services.order import transition_order_status
        transition_order_status(
            db=db,
            order_id=order.id,
            new_status=new_status,
            changed_by="toast_webhook",
            note=f"Toast status: {toast_status}",
        )
        order.toast_order_status = ToastOrderStatus.SYNCED
        db.commit()
        logger.info(
            "Order #%d transitioned to '%s' via Toast webhook (Toast status: %s)",
            order.id, new_status, toast_status,
        )
    except (ValueError, RuntimeError, InvalidStatusTransition) as e:
        logger.warning(
            "Failed to transition order #%d to '%s' from Toast: %s",
            order.id, new_status, e,
        )
