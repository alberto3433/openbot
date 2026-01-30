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


def got_it_anything_else(item_description: str) -> str:
    """Generate a 'Got it, X. Anything else?' response.

    This is the most common response pattern used when acknowledging
    an item or action and prompting for more items.

    Args:
        item_description: Description of what was acknowledged (e.g., "Plain Bagel Toasted")

    Returns:
        Formatted response string like "Got it, Plain Bagel Toasted. Anything else?"
    """
    return f"Got it, {item_description}. {CheckoutMessages.ANYTHING_ELSE}"


def ok_removed_anything_else(item_name: str) -> str:
    """Generate an 'OK, I've removed X. Anything else?' response.

    Args:
        item_name: Name of what was removed

    Returns:
        Formatted response string
    """
    return f"OK, I've removed the {item_name}. {CheckoutMessages.ANYTHING_ELSE}"


def sure_updated_anything_else(item_summary: str) -> str:
    """Generate a 'Sure, I've updated your X. Anything else?' response.

    Args:
        item_summary: Summary of the updated item

    Returns:
        Formatted response string
    """
    return f"Sure, I've updated your {item_summary}. {CheckoutMessages.ANYTHING_ELSE}"


def changed_to_anything_else(item_summary: str) -> str:
    """Generate a 'Sure, I've changed that to X. Anything else?' response.

    Args:
        item_summary: Summary of what the item was changed to

    Returns:
        Formatted response string
    """
    return f"Sure, I've changed that to {item_summary}. {CheckoutMessages.ANYTHING_ELSE}"
