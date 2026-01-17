"""
Checkout flow messages - single source of truth.

This module contains all the standard messages used during the checkout flow.
Import from here instead of hardcoding strings in handlers.
"""


class CheckoutMessages:
    """Standard messages for the checkout flow."""

    # Phase-based questions
    ANYTHING_ELSE = "Anything else?"
    PICKUP_OR_DELIVERY = "Is this for pickup or delivery?"
    NAME = "Can I get a name for the order?"
    CONFIRM = "Does that look right?"
    PAYMENT_METHOD = "Can I get a phone number or email to send the order confirmation?"
    PHONE = "What's the best phone number to reach you?"
    EMAIL = "What's your email address?"

    # Retry/follow-up messages
    PHONE_FOR_TEXT = "What phone number should I text the confirmation to?"
    EMAIL_FOR_SEND = "What email address should I send it to?"
    PHONE_RETRY = "What's the best phone number to text the order confirmation to?"
    EMAIL_RETRY = "What's the best email address to send the order confirmation to?"
