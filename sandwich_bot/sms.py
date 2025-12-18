"""
SMS service for payment links and order confirmations.

Sends real SMS via Twilio when configured, falls back to logging in mock mode.

Environment variables:
- TWILIO_ACCOUNT_SID: Twilio Account SID (starts with AC)
- TWILIO_AUTH_TOKEN: Twilio Auth Token
- TWILIO_PHONE_NUMBER: Twilio phone number to send from (e.g., +18555141417)
"""

import logging
import os
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Twilio configuration from environment
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")


def is_twilio_configured() -> bool:
    """Check if Twilio is properly configured."""
    return all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER])


def normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number to E.164 format for Twilio.

    Examples:
        "732-555-0101" -> "+17325550101"
        "(732) 555-0101" -> "+17325550101"
        "+1 732 555 0101" -> "+17325550101"
    """
    # Remove all non-digit characters
    digits = ''.join(c for c in phone if c.isdigit())

    # Add US country code if not present
    if len(digits) == 10:
        digits = '1' + digits

    return '+' + digits


def send_payment_link_sms(
    phone: str,
    order_id: int,
    amount: float,
    store_name: str,
    customer_name: Optional[str] = None,
    db: Optional[Session] = None,
) -> dict:
    """
    Send an SMS with a payment link to the customer.

    Args:
        phone: Customer's phone number
        order_id: The order ID for reference
        amount: The amount to charge
        store_name: Name of the store for the message
        customer_name: Optional customer name for personalization
        db: Optional database session for logging

    Returns:
        dict with status and payment URL
    """
    # Generate mock payment URL (in production, this would be a real Stripe checkout URL)
    payment_url = f"https://pay.example.com/order/{order_id}"

    # Compose the message (friendly style)
    if customer_name:
        message_body = (
            f"Hi {customer_name}! Your {store_name} order is ${amount:.2f}. "
            f"Tap to pay securely: {payment_url} - Thanks for ordering!"
        )
    else:
        message_body = (
            f"Your {store_name} order is ${amount:.2f}. "
            f"Tap to pay securely: {payment_url} - Thanks for ordering!"
        )

    if not is_twilio_configured():
        # Mock mode - just log the SMS
        logger.info(
            "MOCK SMS to %s: %s",
            phone,
            message_body
        )
        return {
            "status": "sent",
            "phone": phone,
            "message": message_body,
            "payment_url": payment_url,
            "mock": True,
            "message_text": "SMS logged (Twilio not configured)",
        }

    # Send real SMS via Twilio
    try:
        from twilio.rest import Client

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        normalized_phone = normalize_phone_number(phone)

        message = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=normalized_phone
        )

        logger.info(
            "SMS sent successfully to %s for order %d (SID: %s)",
            normalized_phone, order_id, message.sid
        )

        return {
            "status": "sent",
            "phone": normalized_phone,
            "message": message_body,
            "payment_url": payment_url,
            "mock": False,
            "message_sid": message.sid,
            "message_text": "SMS sent successfully",
        }

    except Exception as e:
        logger.error("Failed to send SMS to %s: %s", phone, str(e))
        return {
            "status": "error",
            "phone": phone,
            "error": str(e),
            "mock": False,
            "message_text": f"Failed to send SMS: {str(e)}",
        }


def send_order_confirmation_sms(
    phone: str,
    order_id: int,
    store_name: str,
    order_type: str,
    estimated_time: Optional[str] = None,
) -> dict:
    """
    Send an SMS confirming the order.

    Args:
        phone: Customer's phone number
        order_id: The order ID
        store_name: Name of the store
        order_type: "pickup" or "delivery"
        estimated_time: Optional estimated ready/delivery time

    Returns:
        dict with status
    """
    if order_type == "delivery":
        action = "be delivered"
    else:
        action = "be ready for pickup"

    time_msg = f" in about {estimated_time}" if estimated_time else " soon"

    message_body = (
        f"Your order #{order_id} from {store_name} is confirmed! "
        f"It will {action}{time_msg}."
    )

    if not is_twilio_configured():
        logger.info(
            "MOCK SMS to %s: %s",
            phone,
            message_body
        )
        return {
            "status": "sent",
            "phone": phone,
            "message": message_body,
            "mock": True,
        }

    # Send real SMS via Twilio
    try:
        from twilio.rest import Client

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        normalized_phone = normalize_phone_number(phone)

        message = client.messages.create(
            body=message_body,
            from_=TWILIO_PHONE_NUMBER,
            to=normalized_phone
        )

        logger.info(
            "Confirmation SMS sent to %s for order %d (SID: %s)",
            normalized_phone, order_id, message.sid
        )

        return {
            "status": "sent",
            "phone": normalized_phone,
            "message": message_body,
            "mock": False,
            "message_sid": message.sid,
        }

    except Exception as e:
        logger.error("Failed to send confirmation SMS to %s: %s", phone, str(e))
        return {
            "status": "error",
            "phone": phone,
            "error": str(e),
            "mock": False,
        }
