"""
Stripe Webhook Route for Orderbot
=====================================

Handles Stripe webhook events, primarily for payment confirmation.
Verifies webhook signatures to prevent spoofing.

Events handled:
- checkout.session.completed: Payment succeeded, update order to paid
- checkout.session.expired: Session expired without payment

Configuration:
- STRIPE_WEBHOOK_SECRET: Must be set for signature verification
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import STRIPE_WEBHOOK_SECRET
from ..db import get_db
from ..db.models import Order

logger = logging.getLogger(__name__)

stripe_webhook_router = APIRouter(tags=["Webhooks"])


@stripe_webhook_router.post("/webhooks/stripe")
async def handle_stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Handle incoming Stripe webhook events.

    Verifies the webhook signature using the signing secret, then processes
    the event. Currently handles checkout.session.completed and
    checkout.session.expired events.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not configured; cannot verify webhook")
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    # Verify signature and construct event
    try:
        import stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        logger.warning("Invalid webhook payload")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception as e:
        logger.warning("Webhook signature verification failed: %s", e)
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    logger.info("Stripe webhook received: %s", event_type)

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(event["data"]["object"], db)
    elif event_type == "checkout.session.expired":
        _handle_checkout_expired(event["data"]["object"], db)
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"status": "ok"}


def _handle_checkout_completed(session_data: dict, db: Session) -> None:
    """Handle a completed checkout session (payment succeeded)."""
    session_id = session_data.get("id")
    payment_intent = session_data.get("payment_intent")
    order_id_str = (session_data.get("metadata") or {}).get("order_id")

    if not order_id_str:
        logger.warning("checkout.session.completed missing order_id in metadata: %s", session_id)
        return

    try:
        order_id = int(order_id_str)
    except (ValueError, TypeError):
        logger.warning("Invalid order_id in metadata: %s", order_id_str)
        return

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        logger.warning("Order #%d not found for checkout session %s", order_id, session_id)
        return

    # Update payment status
    order.payment_status = "paid"
    order.stripe_payment_intent_id = payment_intent
    order.paid_at = datetime.now(timezone.utc)

    # If order was pending_payment, move to confirmed now that payment is received
    if order.status == "pending_payment":
        order.status = "confirmed"

    db.commit()
    logger.info(
        "Order #%d payment confirmed (session: %s, intent: %s)",
        order_id, session_id, payment_intent,
    )

    # Send payment confirmation notification
    try:
        from ..notification_service import notify_payment_received
        from ..db.models import Company

        company = db.query(Company).first()
        store_name = company.name if company else "OrderBot"
        notify_payment_received(db, order, store_name)
    except Exception as e:
        logger.error("Failed to send payment notification for order #%d: %s", order_id, e)


def _handle_checkout_expired(session_data: dict, db: Session) -> None:
    """Handle an expired checkout session (customer didn't pay in time)."""
    session_id = session_data.get("id")
    order_id_str = (session_data.get("metadata") or {}).get("order_id")

    if not order_id_str:
        logger.debug("checkout.session.expired missing order_id in metadata: %s", session_id)
        return

    try:
        order_id = int(order_id_str)
    except (ValueError, TypeError):
        return

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        return

    # Only revert if still in pending_payment state (don't affect already-confirmed orders)
    if order.status == "pending_payment" and order.payment_status != "paid":
        order.payment_status = "expired"
        db.commit()
        logger.info("Order #%d checkout session expired: %s", order_id, session_id)
