"""
Email service for sending payment links.

Sends real emails via AWS SES when configured, falls back to logging in mock mode.

Environment variables:
- AWS_ACCESS_KEY_ID: AWS IAM access key
- AWS_SECRET_ACCESS_KEY: AWS IAM secret key
- AWS_REGION: AWS region (default: us-east-1)
- AWS_SES_FROM_EMAIL: Verified sender email address
"""

import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from ..config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_SES_FROM_EMAIL
from ..email_templates import (
    build_payment_link_email,
    build_receipt_email,
    build_payment_expired_email,
    build_report_email,
)

logger = logging.getLogger(__name__)

# Lazy-initialize SES client
_ses_client = None


def _get_ses_client():
    """Lazy-load and configure the AWS SES client."""
    global _ses_client
    if _ses_client is None:
        try:
            import boto3
            _ses_client = boto3.client(
                "ses",
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                region_name=AWS_REGION,
            )
        except ImportError:
            logger.warning("boto3 package not installed; email features disabled")
            return None
    return _ses_client


def is_email_configured() -> bool:
    """Check if AWS SES email is properly configured."""
    return bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_SES_FROM_EMAIL)


def _send_email(to_email: str, subject: str, body_text: str, body_html: str, context: str) -> dict:
    """Send an email via AWS SES, or log in mock mode.

    Args:
        to_email: Recipient email address.
        subject: Email subject line.
        body_text: Plain text body.
        body_html: HTML body.
        context: Short description for log messages (e.g. "payment link", "receipt").

    Returns:
        dict with status and details.
    """
    if not is_email_configured():
        logger.info(
            "MOCK EMAIL to %s: Subject: %s | Body: %s",
            to_email, subject, body_text[:200] + "...",
        )
        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "mock": True,
            "message": f"{context.title()} email logged (AWS SES not configured)",
        }

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = AWS_SES_FROM_EMAIL
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        client = _get_ses_client()
        if client is None:
            return {
                "status": "error",
                "to_email": to_email,
                "error": "boto3 not installed",
                "mock": False,
                "message": f"Failed to send {context} email: boto3 not installed",
            }

        client.send_raw_email(
            Source=AWS_SES_FROM_EMAIL,
            Destinations=[to_email],
            RawMessage={"Data": msg.as_string()},
        )

        logger.info("%s email sent successfully to %s", context.title(), to_email)

        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "mock": False,
            "message": f"{context.title()} email sent successfully",
        }

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
        logger.error("Failed to send %s email to %s: %s", context, to_email, str(e))
        return {
            "status": "error",
            "to_email": to_email,
            "error": str(e),
            "mock": False,
            "message": f"Failed to send {context} email: {str(e)}",
        }


def send_payment_link_email(
    to_email: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
    payment_url: str | None = None,
) -> dict:
    """Send an email with a payment link to the customer.

    Args:
        to_email: Customer's email address
        order_id: The order ID for reference
        amount: The amount to charge (total)
        store_name: Name of the store for the message
        customer_name: Optional customer name for personalization
        customer_phone: Optional customer phone number
        order_type: Optional order type (pickup/delivery)
        items: Optional list of order items
        subtotal: Optional subtotal before tax
        city_tax: Optional city tax amount (only shown if > 0)
        state_tax: Optional state tax amount (only shown if > 0)
        delivery_fee: Optional delivery fee (only shown if > 0)
        payment_url: Optional Stripe checkout URL. Falls back to mock URL if not provided.

    Returns:
        dict with status and details
    """
    if not payment_url:
        payment_url = f"https://pay.example.com/order/{order_id}"

    subject, body_text, body_html = build_payment_link_email(
        order_id=order_id, amount=amount, store_name=store_name,
        payment_url=payment_url, customer_name=customer_name,
        customer_phone=customer_phone, order_type=order_type,
        items=items, subtotal=subtotal, city_tax=city_tax,
        state_tax=state_tax, delivery_fee=delivery_fee,
    )

    result = _send_email(to_email, subject, body_text, body_html, "payment link")
    if result.get("status") == "sent":
        result["payment_url"] = payment_url
    return result


def send_receipt_email(
    to_email: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
) -> dict:
    """Send a receipt email confirming payment was received.

    Args:
        to_email: Customer's email address
        order_id: The order ID for reference
        amount: The total amount paid
        store_name: Name of the store
        customer_name: Optional customer name for personalization
        customer_phone: Optional customer phone number
        order_type: Optional order type (pickup/delivery)
        items: Optional list of order items
        subtotal: Optional subtotal before tax
        city_tax: Optional city tax amount
        state_tax: Optional state tax amount
        delivery_fee: Optional delivery fee

    Returns:
        dict with status and details
    """
    subject, body_text, body_html = build_receipt_email(
        order_id=order_id, amount=amount, store_name=store_name,
        customer_name=customer_name, customer_phone=customer_phone,
        order_type=order_type, items=items, subtotal=subtotal,
        city_tax=city_tax, state_tax=state_tax, delivery_fee=delivery_fee,
    )

    return _send_email(to_email, subject, body_text, body_html, "receipt")


def send_payment_expired_email(
    to_email: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    order_type: str | None = None,
    items: list | None = None,
    subtotal: float | None = None,
    city_tax: float | None = None,
    state_tax: float | None = None,
    delivery_fee: float | None = None,
    payment_url: str | None = None,
) -> dict:
    """Send email notifying customer their payment link has expired with a new link.

    Args:
        to_email: Customer's email address
        order_id: The order ID for reference
        amount: The total amount due
        store_name: Name of the store
        customer_name: Optional customer name for personalization
        customer_phone: Optional customer phone number
        order_type: Optional order type (pickup/delivery)
        items: Optional list of order items
        subtotal: Optional subtotal before tax
        city_tax: Optional city tax amount
        state_tax: Optional state tax amount
        delivery_fee: Optional delivery fee
        payment_url: New Stripe checkout URL

    Returns:
        dict with status and details
    """
    if not payment_url:
        payment_url = f"https://pay.example.com/order/{order_id}"

    subject, body_text, body_html = build_payment_expired_email(
        order_id=order_id, amount=amount, store_name=store_name,
        payment_url=payment_url, customer_name=customer_name,
        customer_phone=customer_phone, order_type=order_type,
        items=items, subtotal=subtotal, city_tax=city_tax,
        state_tax=state_tax, delivery_fee=delivery_fee,
    )

    result = _send_email(to_email, subject, body_text, body_html, "expired payment")
    if result.get("status") == "sent":
        result["payment_url"] = payment_url
    return result


def send_report_email(
    session_id: str,
    store_id: str | None = None,
    caller_id: str | None = None,
    customer_name: str | None = None,
    customer_phone: str | None = None,
    recent_messages: list[dict] | None = None,
    order_status: str | None = None,
    item_count: int = 0,
    items: list[dict] | None = None,
) -> dict:
    """Send a conversation report email to the review team.

    Args:
        session_id: UUID of the session being reported
        store_id: Store identifier
        caller_id: Caller ID / phone number used to start the session
        customer_name: Customer's name if available
        customer_phone: Customer's phone number if available
        recent_messages: Last N messages from conversation history
        order_status: Current order status
        item_count: Number of items in cart
        items: Cart items (adapter dict format)

    Returns:
        dict with status and details
    """
    to_email = "info@zervio.ai"

    subject, body_text, body_html = build_report_email(
        session_id=session_id, store_id=store_id, caller_id=caller_id,
        customer_name=customer_name, customer_phone=customer_phone,
        recent_messages=recent_messages, order_status=order_status,
        item_count=item_count, items=items,
    )

    return _send_email(to_email, subject, body_text, body_html, "report")
