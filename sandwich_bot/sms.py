"""
Mock SMS service for payment links.

In production, this would integrate with Twilio or another SMS provider.
For now, it logs the SMS to the console and stores it in the database for testing.
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def send_payment_link_sms(
    phone: str,
    order_id: int,
    amount: float,
    store_name: str,
    db: Optional[Session] = None,
) -> dict:
    """
    Send an SMS with a payment link to the customer.

    In production, this would:
    1. Create a Stripe Checkout session
    2. Send the checkout URL via Twilio SMS

    For now, we mock it by logging and returning a mock response.

    Args:
        phone: Customer's phone number
        order_id: The order ID for reference
        amount: The amount to charge
        store_name: Name of the store for the message
        db: Optional database session for logging

    Returns:
        dict with status and mock payment URL
    """
    # Generate mock payment URL
    mock_payment_url = f"https://pay.example.com/order/{order_id}"

    # Compose the message
    message = (
        f"Thanks for your order at {store_name}! "
        f"Complete your payment of ${amount:.2f} here: {mock_payment_url}"
    )

    # Log the SMS (in production, this would be sent via Twilio)
    logger.info(
        "MOCK SMS to %s: %s",
        phone,
        message
    )

    # In production, this would be the actual Twilio API call:
    # from twilio.rest import Client
    # client = Client(account_sid, auth_token)
    # message = client.messages.create(
    #     body=message,
    #     from_=twilio_phone_number,
    #     to=phone
    # )

    return {
        "status": "sent",
        "phone": phone,
        "message": message,
        "payment_url": mock_payment_url,
        "mock": True,  # Indicates this is a mock response
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

    message = (
        f"Your order #{order_id} from {store_name} is confirmed! "
        f"It will {action}{time_msg}."
    )

    logger.info(
        "MOCK SMS to %s: %s",
        phone,
        message
    )

    return {
        "status": "sent",
        "phone": phone,
        "message": message,
        "mock": True,
    }
