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
    DELIVERY_ADDRESS = "What's the delivery address?"

    # Retry/follow-up messages
    PHONE_FOR_TEXT = "What phone number should I text the confirmation to?"
    EMAIL_FOR_SEND = "What email address should I send it to?"
    PHONE_RETRY = "What's the best phone number to text the order confirmation to?"
    EMAIL_RETRY = "What's the best email address to send the order confirmation to?"

    # Recovery prompts
    WHAT_TO_ORDER = "What would you like to order?"


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


def item_added_anything_else(count: int, item_name: str) -> str:
    """Generate 'I've added X more Y. Anything else?' response.

    Used when duplicating items in the cart.

    Args:
        count: Number of items added
        item_name: Name/summary of the item

    Returns:
        Formatted response string
    """
    if count == 1:
        return f"I've added another {item_name}. {CheckoutMessages.ANYTHING_ELSE}"
    return f"I've added {count} more {item_name}. {CheckoutMessages.ANYTHING_ELSE}"


# =============================================================================
# Error Recovery Messages
# =============================================================================

class ErrorMessages:
    """Standard error recovery messages."""

    # Generic recovery prompts for when something goes wrong
    WHAT_TO_ORDER = "Something went wrong. What would you like to order?"
    WHAT_CAN_I_GET = "Something went wrong. What can I get for you?"
    WHAT_ELSE = "Something went wrong. What else can I help with?"

    # Empty cart message
    NO_ITEMS_YET = "There's nothing in your order yet. What can I get for you?"


# =============================================================================
# "Not Found" Messages
# =============================================================================

def item_not_found_in_order(item_desc: str) -> str:
    """Generate "I couldn't find X in your order" message.

    Args:
        item_desc: Description of what wasn't found (e.g., "a bagel", "the latte")

    Returns:
        Formatted message with recovery prompt
    """
    return f"I couldn't find {item_desc} in your order. What would you like to do?"


def item_not_found_would_you_like_to_add(item_desc: str) -> str:
    """Generate "I couldn't find X. Would you like to add one?" message.

    Used when user tries to modify an item not in their order.

    Args:
        item_desc: Description of what wasn't found

    Returns:
        Formatted message offering to add the item
    """
    return f"I couldn't find a {item_desc} in your order. Would you like to add one?"
