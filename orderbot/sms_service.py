"""
SMS Service for Orderbot (Twilio)
====================================

Sends SMS messages to customers via Twilio. When Twilio is not configured
(no TWILIO_ACCOUNT_SID), all functions return None for graceful degradation.

Environment variables:
- TWILIO_ACCOUNT_SID: Twilio account SID
- TWILIO_AUTH_TOKEN: Twilio auth token
- TWILIO_FROM_NUMBER: Twilio phone number to send from (e.g., +15551234567)
"""

import logging
from typing import Optional

from .config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER

logger = logging.getLogger(__name__)

# Lazy-initialize Twilio client
_client = None


def _get_client():
    """Lazy-load and configure the Twilio client."""
    global _client
    if _client is None:
        try:
            from twilio.rest import Client
            _client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        except ImportError:
            logger.warning("twilio package not installed; SMS features disabled")
            return None
    return _client


def is_sms_configured() -> bool:
    """Check if Twilio SMS is properly configured."""
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


def send_sms(to_number: str, body: str) -> Optional[str]:
    """Send an SMS message via Twilio.

    Args:
        to_number: Recipient phone number (E.164 format, e.g., +15551234567)
        body: Message text (max 1600 chars for Twilio)

    Returns:
        Twilio message SID on success, None on failure or if not configured.
    """
    if not is_sms_configured():
        logger.info("SMS not configured; would send to %s: %s", to_number, body[:100])
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        message = client.messages.create(
            to=to_number,
            from_=TWILIO_FROM_NUMBER,
            body=body,
        )
        logger.info("SMS sent to %s (SID: %s)", to_number, message.sid)
        return message.sid
    except Exception as e:
        logger.error("Failed to send SMS to %s: %s", to_number, e)
        return None
