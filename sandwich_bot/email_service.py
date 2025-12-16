"""
Email service for sending payment links.

Sends real emails via SMTP when configured, falls back to logging in mock mode.

Environment variables:
- SMTP_HOST: SMTP server hostname (e.g., smtp.gmail.com)
- SMTP_PORT: SMTP server port (default: 587 for TLS)
- SMTP_USERNAME: SMTP authentication username
- SMTP_PASSWORD: SMTP authentication password (for Gmail, use App Password)
- SMTP_FROM_EMAIL: Sender email address
"""

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

logger = logging.getLogger(__name__)

# SMTP configuration from environment
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL")


def is_email_configured() -> bool:
    """Check if SMTP is properly configured."""
    return all([SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL])


def send_payment_link_email(
    to_email: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: Optional[str] = None,
) -> dict:
    """
    Send an email with a payment link to the customer.

    Args:
        to_email: Customer's email address
        order_id: The order ID for reference
        amount: The amount to charge
        store_name: Name of the store for the message
        customer_name: Optional customer name for personalization

    Returns:
        dict with status and details
    """
    # Generate mock payment URL (in production, this would be a real Stripe checkout URL)
    payment_url = f"https://pay.example.com/order/{order_id}"

    # Build the email content
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

    subject = f"Payment Link for Your {store_name} Order #{order_id}"

    body_text = f"""{greeting}

Thank you for your order at {store_name}!

Your order total is ${amount:.2f}.

Click here to complete your payment:
{payment_url}

If you have any questions, please call us.

Thanks,
{store_name}
"""

    body_html = f"""
<html>
<body>
<p>{greeting}</p>
<p>Thank you for your order at <strong>{store_name}</strong>!</p>
<p>Your order total is <strong>${amount:.2f}</strong>.</p>
<p><a href="{payment_url}" style="background-color: #4CAF50; color: white; padding: 14px 20px; text-decoration: none; display: inline-block; border-radius: 4px;">Complete Payment</a></p>
<p>Or copy this link: {payment_url}</p>
<p>If you have any questions, please call us.</p>
<p>Thanks,<br>{store_name}</p>
</body>
</html>
"""

    if not is_email_configured():
        # Mock mode - just log the email
        logger.info(
            "MOCK EMAIL to %s: Subject: %s | Body: %s",
            to_email,
            subject,
            body_text[:200] + "..."
        )
        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "payment_url": payment_url,
            "mock": True,
            "message": "Email logged (SMTP not configured)",
        }

    # Send real email via SMTP
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = to_email

        # Attach both plain text and HTML versions
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        # Connect and send
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        logger.info("Email sent successfully to %s for order %d", to_email, order_id)

        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "payment_url": payment_url,
            "mock": False,
            "message": "Email sent successfully",
        }

    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_email, str(e))
        return {
            "status": "error",
            "to_email": to_email,
            "error": str(e),
            "mock": False,
            "message": f"Failed to send email: {str(e)}",
        }


def send_order_confirmation_email(
    to_email: str,
    order_id: int,
    store_name: str,
    order_type: str,
    customer_name: Optional[str] = None,
    estimated_time: Optional[str] = None,
) -> dict:
    """
    Send an order confirmation email.

    Args:
        to_email: Customer's email address
        order_id: The order ID
        store_name: Name of the store
        order_type: "pickup" or "delivery"
        customer_name: Optional customer name
        estimated_time: Optional estimated ready/delivery time

    Returns:
        dict with status
    """
    greeting = f"Hi {customer_name}," if customer_name else "Hi,"

    if order_type == "delivery":
        action = "be delivered"
    else:
        action = "be ready for pickup"

    time_msg = f" in about {estimated_time}" if estimated_time else " soon"

    subject = f"Order Confirmed - {store_name} #{order_id}"

    body_text = f"""{greeting}

Your order #{order_id} from {store_name} is confirmed!

It will {action}{time_msg}.

Thanks,
{store_name}
"""

    if not is_email_configured():
        logger.info(
            "MOCK EMAIL to %s: Subject: %s",
            to_email,
            subject
        )
        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "mock": True,
        }

    try:
        msg = MIMEText(body_text, "plain")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM_EMAIL
        msg["To"] = to_email

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, to_email, msg.as_string())

        logger.info("Confirmation email sent to %s for order %d", to_email, order_id)

        return {
            "status": "sent",
            "to_email": to_email,
            "subject": subject,
            "mock": False,
        }

    except Exception as e:
        logger.error("Failed to send confirmation email to %s: %s", to_email, str(e))
        return {
            "status": "error",
            "to_email": to_email,
            "error": str(e),
        }
