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
from ..db.models import Order, Company
from ..schemas.enums import OrderStatus, PaymentStatus

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
    order.payment_status = PaymentStatus.PAID
    order.stripe_payment_intent_id = payment_intent
    order.paid_at = datetime.now(timezone.utc)

    # If order was pending_payment, move to confirmed now that payment is received
    if order.status == OrderStatus.PENDING_PAYMENT:
        order.status = OrderStatus.CONFIRMED

    # Backfill email from Stripe session if missing on order
    if not order.customer_email:
        stripe_email = (
            (session_data.get("customer_details") or {}).get("email")
            or session_data.get("customer_email")
        )
        if stripe_email:
            order.customer_email = stripe_email
            logger.info("Backfilled email on order #%d from Stripe: %s", order_id, stripe_email)

    db.commit()
    logger.info(
        "Order #%d payment confirmed (session: %s, intent: %s)",
        order_id, session_id, payment_intent,
    )

    # Send receipt email
    _send_receipt_for_order(db, order)


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
    if order.status == OrderStatus.PENDING_PAYMENT and order.payment_status != PaymentStatus.PAID:
        order.payment_status = PaymentStatus.EXPIRED
        db.commit()
        logger.info("Order #%d checkout session expired: %s", order_id, session_id)

        # Send expired email with a new payment link
        _send_expired_link_for_order(db, order)


def _build_email_kwargs(db: Session, order: Order) -> dict:
    """Build common email kwargs from an Order and its items."""
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


def _send_receipt_for_order(db: Session, order: Order) -> None:
    """Send a receipt email for a paid order."""
    if not order.customer_email:
        logger.debug("No email on order #%d; skipping receipt email", order.id)
        return

    try:
        from ..email_service import send_receipt_email

        kwargs = _build_email_kwargs(db, order)
        send_receipt_email(**kwargs)
        logger.info("Receipt email sent for order #%d", order.id)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.error("Failed to send receipt email for order #%d: %s", order.id, e)


def _send_expired_link_for_order(db: Session, order: Order) -> None:
    """Send an expired-payment email with a fresh Stripe checkout link."""
    if not order.customer_email:
        logger.debug("No email on order #%d; skipping expired payment email", order.id)
        return

    try:
        from ..email_service import send_payment_expired_email
        from ..stripe_service import create_checkout_session, is_stripe_configured
        from ..services.order import update_order_stripe_session

        # Create a fresh Stripe checkout session
        payment_url = None
        if is_stripe_configured():
            items_for_stripe = []
            for oi in order.items:
                amount_cents = round(oi.unit_price * 100) if oi.unit_price else 0
                items_for_stripe.append({
                    "name": oi.menu_item_name,
                    "quantity": oi.quantity,
                    "amount_cents": amount_cents,
                })

            # Add tax as separate line item if applicable
            item_total_cents = sum(i["amount_cents"] * i["quantity"] for i in items_for_stripe)
            order_total_cents = round((order.total_price or 0) * 100)
            tax_cents = order_total_cents - item_total_cents
            if tax_cents > 0:
                items_for_stripe.append({
                    "name": "Tax & Fees",
                    "quantity": 1,
                    "amount_cents": tax_cents,
                })

            result = create_checkout_session(
                order_id=order.id,
                line_items=items_for_stripe,
                customer_email=order.customer_email,
            )
            if result:
                payment_url = result["url"]
                update_order_stripe_session(db, order.id, result["session_id"])
                # Reset payment status to pending for the new session
                order.payment_status = PaymentStatus.PENDING_PAYMENT
                db.commit()

        if not payment_url:
            from ..config import BASE_URL
            payment_url = f"{BASE_URL}/pay/{order.id}"

        kwargs = _build_email_kwargs(db, order)
        kwargs["payment_url"] = payment_url
        send_payment_expired_email(**kwargs)
        logger.info("Expired payment email sent for order #%d", order.id)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.error("Failed to send expired payment email for order #%d: %s", order.id, e)
