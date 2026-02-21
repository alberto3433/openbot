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

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .db.models import NotificationLog, Order
from .email_service import send_payment_link_email, is_email_configured
from .schemas.enums import NotificationStatus
from .sms_service import send_sms, is_sms_configured

logger = logging.getLogger(__name__)


def _log_notification(
    db: Session,
    order_id: int | None,
    notification_type: str,
    event: str,
    recipient: str,
    status: str,
    provider_message_id: str | None = None,
    error_message: str | None = None,
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
        sent_at=datetime.now(timezone.utc) if status == NotificationStatus.SENT else None,
    )
    db.add(entry)
    try:
        db.commit()
    except SQLAlchemyError as e:
        logger.error("Failed to log notification: %s", e)
        db.rollback()


def _send_sms_logged(db: Session, order: Order, event: str, body: str) -> None:
    """Send an SMS and log the result to the notification_log table.

    Skips silently if the order has no phone number or SMS is not configured.

    Args:
        db: Database session for logging.
        order: The order (must have .phone and .id).
        event: Event name for the log entry (e.g., "payment_received").
        body: SMS message body.
    """
    if not (order.phone and is_sms_configured()):
        return
    sid = send_sms(order.phone, body)
    _log_notification(
        db, order.id, "sms", event, order.phone,
        status=NotificationStatus.SENT if sid else NotificationStatus.FAILED,
        provider_message_id=sid,
    )


def notify_payment_received(
    db: Session,
    order: Order,
    store_name: str,
) -> None:
    """Send payment received notifications."""
    _send_sms_logged(
        db, order, "payment_received",
        f"Payment received for order #{order.id} at {store_name}! "
        f"Total: ${order.total_price:.2f}. We'll let you know when it's ready.",
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
    _send_sms_logged(
        db, order, "order_ready",
        f"Your order #{order.id} at {store_name} is ready for pickup!",
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

    _send_sms_logged(
        db, order, "order_cancelled",
        f"Your order #{order.id} at {store_name} has been cancelled.{reason}",
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
    """Send a simple text email via AWS SES and log the result."""
    from email.mime.text import MIMEText
    from .config import AWS_SES_FROM_EMAIL
    from .email_service import _get_ses_client

    client = _get_ses_client()
    if client is None:
        logger.info("AWS SES not configured; skipping %s email for order #%d", event, order.id)
        return

    try:
        msg = MIMEText(body_text, "plain")
        msg["Subject"] = subject
        msg["From"] = AWS_SES_FROM_EMAIL
        msg["To"] = order.customer_email

        client.send_raw_email(
            Source=AWS_SES_FROM_EMAIL,
            Destinations=[order.customer_email],
            RawMessage={"Data": msg.as_string()},
        )

        _log_notification(
            db, order.id, "email", event, order.customer_email,
            status=NotificationStatus.SENT,
        )
        logger.info("%s email sent to %s for order #%d", event, order.customer_email, order.id)

    except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
        _log_notification(
            db, order.id, "email", event, order.customer_email,
            status=NotificationStatus.FAILED, error_message=str(e),
        )
        logger.error("Failed to send %s email for order #%d: %s", event, order.id, e)
