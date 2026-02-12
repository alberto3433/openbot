"""
Notification Service for Orderbot
=====================================

Unified dispatcher for customer notifications (SMS + email). Logs all
notification attempts to the notification_log table for audit/debugging.

Each notify_* function determines the appropriate channels (SMS, email, or both)
based on available contact info and sends the notification.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from .db.models import NotificationLog, Order
from .email_service import send_payment_link_email, is_email_configured
from .sms_service import send_sms, is_sms_configured

logger = logging.getLogger(__name__)


def _log_notification(
    db: Session,
    order_id: Optional[int],
    notification_type: str,
    event: str,
    recipient: str,
    status: str,
    provider_message_id: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """Record a notification attempt in the database."""
    entry = NotificationLog(
        order_id=order_id,
        notification_type=notification_type,
        event=event,
        recipient=recipient,
        status=status,
        provider_message_id=provider_message_id,
        error_message=error_message,
        sent_at=datetime.now(timezone.utc) if status == "sent" else None,
    )
    db.add(entry)
    try:
        db.commit()
    except Exception as e:
        logger.error("Failed to log notification: %s", e)
        db.rollback()


def notify_order_confirmed(
    db: Session,
    order: Order,
    store_name: str,
    payment_url: Optional[str] = None,
) -> None:
    """Send order confirmation notifications (SMS + email with payment link).

    Args:
        db: Database session for logging
        order: The confirmed order
        store_name: Display name of the store
        payment_url: Stripe checkout URL (or mock URL)
    """
    items_summary = f"{len(order.items)} item(s)" if order.items else "your order"
    total_str = f"${order.total_price:.2f}" if order.total_price else ""

    # SMS confirmation
    if order.phone and is_sms_configured():
        sms_body = (
            f"Thanks for your order at {store_name}! "
            f"Order #{order.id}: {items_summary}, total {total_str}."
        )
        if payment_url:
            sms_body += f"\nPay here: {payment_url}"

        sid = send_sms(order.phone, sms_body)
        _log_notification(
            db, order.id, "sms", "order_confirmed", order.phone,
            status="sent" if sid else "failed",
            provider_message_id=sid,
        )

    # Email is handled separately by the existing email service flow in message_processor


def notify_payment_received(
    db: Session,
    order: Order,
    store_name: str,
) -> None:
    """Send payment received notifications."""
    # SMS
    if order.phone and is_sms_configured():
        sms_body = (
            f"Payment received for order #{order.id} at {store_name}! "
            f"Total: ${order.total_price:.2f}. We'll let you know when it's ready."
        )
        sid = send_sms(order.phone, sms_body)
        _log_notification(
            db, order.id, "sms", "payment_received", order.phone,
            status="sent" if sid else "failed",
            provider_message_id=sid,
        )

    # Email - brief confirmation
    if order.customer_email and is_email_configured():
        _send_simple_email(
            db, order,
            subject=f"Payment Received - {store_name} Order #{order.id}",
            body_text=(
                f"Hi{' ' + order.customer_name if order.customer_name else ''},\n\n"
                f"We've received your payment of ${order.total_price:.2f} for order #{order.id}.\n"
                f"We'll notify you when your order is ready!\n\n"
                f"Thanks,\n{store_name}"
            ),
            event="payment_received",
        )


def notify_order_ready(
    db: Session,
    order: Order,
    store_name: str,
) -> None:
    """Send 'order is ready' notifications."""
    # SMS
    if order.phone and is_sms_configured():
        sms_body = f"Your order #{order.id} at {store_name} is ready for pickup!"
        sid = send_sms(order.phone, sms_body)
        _log_notification(
            db, order.id, "sms", "order_ready", order.phone,
            status="sent" if sid else "failed",
            provider_message_id=sid,
        )

    # Email
    if order.customer_email and is_email_configured():
        _send_simple_email(
            db, order,
            subject=f"Your {store_name} Order #{order.id} is Ready!",
            body_text=(
                f"Hi{' ' + order.customer_name if order.customer_name else ''},\n\n"
                f"Your order #{order.id} is ready for pickup at {store_name}!\n\n"
                f"Thanks,\n{store_name}"
            ),
            event="order_ready",
        )


def notify_order_cancelled(
    db: Session,
    order: Order,
    store_name: str,
) -> None:
    """Send order cancellation notifications."""
    reason = f" Reason: {order.cancellation_reason}" if order.cancellation_reason else ""

    # SMS
    if order.phone and is_sms_configured():
        sms_body = f"Your order #{order.id} at {store_name} has been cancelled.{reason}"
        sid = send_sms(order.phone, sms_body)
        _log_notification(
            db, order.id, "sms", "order_cancelled", order.phone,
            status="sent" if sid else "failed",
            provider_message_id=sid,
        )

    # Email
    if order.customer_email and is_email_configured():
        _send_simple_email(
            db, order,
            subject=f"{store_name} Order #{order.id} Cancelled",
            body_text=(
                f"Hi{' ' + order.customer_name if order.customer_name else ''},\n\n"
                f"Your order #{order.id} at {store_name} has been cancelled.{reason}\n\n"
                f"If you have any questions, please contact us.\n\n"
                f"Thanks,\n{store_name}"
            ),
            event="order_cancelled",
        )


def _send_simple_email(
    db: Session,
    order: Order,
    subject: str,
    body_text: str,
    event: str,
) -> None:
    """Send a simple text email and log the result."""
    import smtplib
    import ssl
    from email.mime.text import MIMEText
    from .email_service import SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL

    if not all([SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL]):
        logger.info("SMTP not configured; skipping %s email for order #%d", event, order.id)
        return

    try:
        msg = MIMEText(body_text, "plain")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = order.customer_email

        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, order.customer_email, msg.as_string())

        _log_notification(
            db, order.id, "email", event, order.customer_email, status="sent",
        )
        logger.info("%s email sent to %s for order #%d", event, order.customer_email, order.id)

    except Exception as e:
        _log_notification(
            db, order.id, "email", event, order.customer_email,
            status="failed", error_message=str(e),
        )
        logger.error("Failed to send %s email for order #%d: %s", event, order.id, e)
