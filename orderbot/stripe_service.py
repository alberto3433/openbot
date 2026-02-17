"""
Stripe Payment Service for Orderbot
========================================

Creates Stripe Checkout Sessions for customer payments and retrieves session
details. When Stripe is not configured (no STRIPE_SECRET_KEY), all functions
return None so the system degrades gracefully to mock payment URLs.

Environment variables:
- STRIPE_SECRET_KEY: Stripe secret API key (sk_test_... or sk_live_...)
- BASE_URL: Application base URL for success/cancel redirects
"""

import logging
from typing import Any

from .config import STRIPE_SECRET_KEY, BASE_URL

logger = logging.getLogger(__name__)

# Lazy-initialize Stripe to avoid import errors when not installed in dev
_stripe = None


def _get_stripe():
    """Lazy-load and configure the stripe module."""
    global _stripe
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = STRIPE_SECRET_KEY
            _stripe = stripe
        except ImportError:
            logger.warning("stripe package not installed; payment features disabled")
            return None
    return _stripe


def is_stripe_configured() -> bool:
    """Check if Stripe is properly configured with an API key."""
    return bool(STRIPE_SECRET_KEY)


def create_checkout_session(
    order_id: int,
    line_items: list[dict[str, Any]],
    customer_email: str | None = None,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, Any] | None:
    """
    Create a Stripe Checkout Session for an order.

    Args:
        order_id: The database order ID (used in metadata and URLs).
        line_items: List of items for the checkout, each with:
            - name: Display name
            - quantity: Item quantity
            - amount_cents: Price in cents (integer)
        customer_email: Pre-fill customer email on checkout page.
        success_url: URL to redirect after successful payment.
        cancel_url: URL to redirect if customer cancels.

    Returns:
        Dict with 'session_id' and 'url' keys, or None if Stripe is not configured.
    """
    if not is_stripe_configured():
        logger.info("Stripe not configured; skipping checkout session for order #%d", order_id)
        return None

    stripe = _get_stripe()
    if stripe is None:
        return None

    if not success_url:
        success_url = f"{BASE_URL}/static/order_confirmed.html?order_id={order_id}&session_id={{CHECKOUT_SESSION_ID}}"
    if not cancel_url:
        cancel_url = f"{BASE_URL}/static/index.html?order_id={order_id}&payment=cancelled"

    # Build Stripe line_items format
    stripe_line_items = []
    for item in line_items:
        stripe_line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": item["name"],
                },
                "unit_amount": item["amount_cents"],
            },
            "quantity": item["quantity"],
        })

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=stripe_line_items,
            customer_email=customer_email,
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"order_id": str(order_id)},
            expires_after={"seconds": 1800},  # 30 minutes
        )

        logger.info(
            "Stripe checkout session created: %s for order #%d",
            session.id, order_id,
        )

        return {
            "session_id": session.id,
            "url": session.url,
        }

    except Exception as e:
        logger.error("Failed to create Stripe checkout session for order #%d: %s", order_id, e)
        return None


def get_checkout_session(session_id: str) -> dict[str, Any] | None:
    """
    Retrieve a Stripe Checkout Session by ID.

    Args:
        session_id: The Stripe checkout session ID (cs_...).

    Returns:
        Dict with session details, or None if not found or Stripe not configured.
    """
    if not is_stripe_configured():
        return None

    stripe = _get_stripe()
    if stripe is None:
        return None

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        return {
            "session_id": session.id,
            "payment_status": session.payment_status,
            "payment_intent": session.payment_intent,
            "customer_email": session.customer_email,
            "amount_total": session.amount_total,
            "metadata": dict(session.metadata) if session.metadata else {},
            "status": session.status,
        }
    except Exception as e:
        logger.error("Failed to retrieve Stripe session %s: %s", session_id, e)
        return None
