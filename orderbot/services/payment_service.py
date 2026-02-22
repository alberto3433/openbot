"""
Payment Service for Orderbot
================================

Payment orchestration functions extracted from MessageProcessor.
Handles payment URL creation (Stripe/Square) and receipt sending.

Functions:
----------
- create_payment_url: Route to Square or Stripe based on company config
- create_square_payment_link: Create a Square Payment Link
- create_stripe_session: Create a Stripe Checkout Session
- get_stripe_customer_id: Look up Stripe Customer ID by email
- send_in_store_receipt: Send receipt email for pay-in-store orders
- get_order_state_checkout: Helper to get checkout state from items
"""

import logging
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .store_service import get_company


logger = logging.getLogger(__name__)


def create_payment_url(
    db: Session,
    order_state: dict[str, Any],
    customer_email: str | None,
) -> str | None:
    """Create a payment checkout URL using the configured provider.

    Routes to Square Payment Links or Stripe Checkout based on the
    company's payment_provider setting.

    Returns the checkout URL if configured, otherwise a fallback
    payment page URL so the button always appears for confirmed orders.

    Args:
        db: Database session
        order_state: Current order state dict
        customer_email: Customer email for Stripe

    Returns:
        Checkout URL string, or None on failure
    """
    try:
        db_order_id = order_state.get("db_order_id")
        if not db_order_id:
            return None

        # Check company payment provider setting
        company = get_company(db)
        provider = getattr(company, "payment_provider", "stripe") if company else "stripe"

        if provider == "square":
            url = create_square_payment_link(db, order_state)
            if url:
                return url
        else:
            items = order_state.get("items", [])
            checkout_state = order_state.get("checkout_state", {})
            order_total = (
                checkout_state.get("total")
                or order_state.get("total_price")
                or sum(item.get("line_total", 0) for item in items)
            )

            stripe_result = create_stripe_session(
                db, db_order_id, items, order_total, customer_email or "",
            )
            if stripe_result:
                return stripe_result["url"]

        # Fallback URL when neither provider is configured
        from ..config import BASE_URL
        return f"{BASE_URL}/pay/{db_order_id}"
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        logger.exception("Failed to create payment URL")
        return None


def create_square_payment_link(
    db: Session,
    order_state: dict[str, Any],
) -> str | None:
    """Create a Square Payment Link and return the checkout URL.

    Args:
        db: Database session
        order_state: Current order state dict

    Returns:
        Square checkout URL on success, None on failure
    """
    try:
        from ..square.service import create_payment_link, is_square_configured
        if not is_square_configured():
            return None

        result = create_payment_link(db, order_state)
        if result:
            logger.info(
                "Square payment link created for order #%s",
                order_state.get("db_order_id"),
            )
            return result["url"]
        return None
    except (ImportError, OSError, SQLAlchemyError):
        logger.exception(
            "Failed to create Square payment link for order #%s",
            order_state.get("db_order_id"),
        )
        return None
    except (ValueError, KeyError, TypeError, ConnectionError):
        logger.exception(
            "Unexpected error creating Square payment link for order #%s",
            order_state.get("db_order_id"),
        )
        return None


def create_stripe_session(
    db: Session,
    order_id: int,
    items: list[dict[str, Any]],
    order_total: float,
    customer_email: str,
) -> dict[str, Any] | None:
    """Create a Stripe Checkout Session and link it to the order.

    Args:
        db: Database session
        order_id: The order ID
        items: List of order item dicts
        order_total: Total order amount
        customer_email: Customer email for Stripe

    Returns:
        Dict with 'session_id' and 'url' on success, None if Stripe
        is not configured or creation fails.
    """
    try:
        from .stripe_service import create_checkout_session, is_stripe_configured
        if not is_stripe_configured():
            return None

        # Build line items for Stripe (one entry per order item)
        stripe_line_items = []
        for item in items:
            name = item.get("display_name") or item.get("menu_item_name") or "Item"
            quantity = item.get("quantity", 1)
            line_total = item.get("line_total", 0)
            amount_cents = round((line_total / quantity) * 100) if quantity > 0 else 0
            stripe_line_items.append({
                "name": name,
                "quantity": quantity,
                "amount_cents": amount_cents,
            })

        # Add tax as a separate line item if present
        tax_total = round(order_total * 100) - sum(
            item["amount_cents"] * item["quantity"] for item in stripe_line_items
        )
        if tax_total > 0:
            stripe_line_items.append({
                "name": "Tax & Fees",
                "quantity": 1,
                "amount_cents": tax_total,
            })

        # Look up Stripe Customer ID for saved payment methods
        stripe_customer_id = get_stripe_customer_id(db, customer_email)

        result = create_checkout_session(
            order_id=order_id,
            line_items=stripe_line_items,
            customer_email=customer_email,
            stripe_customer_id=stripe_customer_id,
        )

        if result:
            # Link Stripe session to order in DB
            from .order import update_order_stripe_session
            update_order_stripe_session(db, order_id, result["session_id"])

        return result
    except (ConnectionError, TimeoutError, ValueError, KeyError) as e:
        logger.exception("Failed to create Stripe session for order #%d", order_id)
        return None


def get_stripe_customer_id(db: Session, customer_email: str | None) -> str | None:
    """Look up Stripe Customer ID from Customer table by email.

    Args:
        db: Database session
        customer_email: Customer email to look up

    Returns:
        Stripe customer ID string, or None
    """
    if not customer_email:
        return None
    try:
        from ..db.models import Customer
        from sqlalchemy import func
        customer = (
            db.query(Customer)
            .filter(func.lower(Customer.email) == customer_email.lower())
            .first()
        )
        return customer.stripe_customer_id if customer else None
    except (ImportError, SQLAlchemyError, ValueError, TypeError):
        return None


def send_in_store_receipt(
    db: Session,
    order_state: dict[str, Any],
    customer_email: str,
) -> None:
    """Send a receipt email for pay-in-store orders.

    For online payments the Stripe webhook triggers the receipt. For
    in-store payments we send it here instead.

    Args:
        db: Database session
        order_state: Current order state dict
        customer_email: Customer email address
    """
    try:
        from .email_service import send_receipt_email, is_email_configured
        if not is_email_configured():
            return

        db_order_id = order_state.get("db_order_id")
        if not db_order_id:
            return

        company = get_company(db)
        store_name = company.name if company else "OrderBot"

        items = order_state.get("items", [])
        checkout_state = order_state.get("checkout_state", {})
        order_total = (
            checkout_state.get("total")
            or order_state.get("total_price")
            or sum(item.get("line_total", 0) for item in items)
        )

        send_receipt_email(
            to_email=customer_email,
            order_id=db_order_id,
            amount=order_total,
            store_name=store_name,
            customer_name=order_state.get("customer", {}).get("name"),
            customer_phone=order_state.get("customer", {}).get("phone"),
            order_type=order_state.get("order_type"),
            items=items,
            subtotal=checkout_state.get("subtotal"),
            city_tax=checkout_state.get("city_tax", 0),
            state_tax=checkout_state.get("state_tax", 0),
            delivery_fee=checkout_state.get("delivery_fee", 0),
        )
        logger.info("In-store receipt email sent for order #%s", db_order_id)
    except (OSError, ValueError, KeyError, TypeError):
        logger.exception("Failed to send in-store receipt email")


def get_order_state_checkout(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Helper to get checkout state from items."""
    return {}
