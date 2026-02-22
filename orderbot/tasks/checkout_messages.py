"""
Checkout flow messages - single source of truth.

This module contains all the standard messages used during the checkout flow.
Import from here instead of hardcoding strings in handlers.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import MenuItemTask

CONFIRM_QUICK_REPLIES = [{"label": "right", "value": "yes"}]


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


def sure_added_to_anything_else(item_summary: str) -> str:
    """Generate "Sure, I've added that to your X. Anything else?" response.

    Used when adding modifiers to an existing item.

    Args:
        item_summary: Summary of the item with the addition

    Returns:
        Formatted response string
    """
    return f"Sure, I've added that to your {item_summary}. {CheckoutMessages.ANYTHING_ELSE}"


def sure_removed_anything_else(removed_name: str, item_summary: str | None = None) -> str:
    """Generate "Sure, I've removed the X. Anything else?" response.

    Used when removing modifiers or ingredients.

    Args:
        removed_name: Name of what was removed (e.g., "milk", "bacon")
        item_summary: Optional updated item summary to include

    Returns:
        Formatted response string
    """
    if item_summary:
        return f"Sure, I've removed the {removed_name}. Your order is now {item_summary}. {CheckoutMessages.ANYTHING_ELSE}"
    return f"Sure, I've removed the {removed_name}. {CheckoutMessages.ANYTHING_ELSE}"


def sure_changed_anything_else(
    attr_name: str,
    new_value: str,
    item_summary: str | None = None,
) -> str:
    """Generate "Sure, I've changed the X to Y. Anything else?" response.

    Used when changing a modifier or attribute value.

    Args:
        attr_name: Name of what was changed (e.g., "spread", "milk")
        new_value: The new value
        item_summary: Optional updated item summary

    Returns:
        Formatted response string
    """
    if item_summary:
        return f"Sure, I've changed the {attr_name} to {new_value}. Your order is now {item_summary}. {CheckoutMessages.ANYTHING_ELSE}"
    return f"Sure, I've changed the {attr_name} to {new_value}. {CheckoutMessages.ANYTHING_ELSE}"


def thats_n_total_anything_else(qty: int) -> str:
    """Generate "Sure, that's N total. Anything else?" response.

    Used after quantity changes (make-it-N).

    Args:
        qty: The new total quantity

    Returns:
        Formatted response string
    """
    return f"Sure, that's {qty} total. {CheckoutMessages.ANYTHING_ELSE}"


def already_have_n_anything_else(count: int, item_name: str) -> str:
    """Generate "You already have N X. Anything else?" response.

    Used when user requests a quantity they already have.

    Args:
        count: Current quantity
        item_name: Name/description of the item

    Returns:
        Formatted response string
    """
    return f"You already have {count} {item_name}. {CheckoutMessages.ANYTHING_ELSE}"


def duplicated_order_anything_else() -> str:
    """Generate "I've duplicated all items in your order. Anything else?" response."""
    return f"I've duplicated all items in your order. {CheckoutMessages.ANYTHING_ELSE}"


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


# =============================================================================
# Modifier Validation Messages
# =============================================================================

def item_not_customizable(item_name: str) -> str:
    """Message when user tries to customize a non-configurable item.

    Args:
        item_name: Name of the item that can't be customized

    Returns:
        Formatted rejection message
    """
    return f"Sorry, the {item_name} can't be customized. Anything else?"


def modifier_not_available_for_item(modifier_name: str, item_name: str) -> str:
    """Message when modifier isn't valid for an item type.

    Args:
        modifier_name: Name of the modifier that isn't available
        item_name: Name of the item

    Returns:
        Formatted rejection message
    """
    return f"Sorry, {modifier_name} isn't available for the {item_name}. Anything else?"


def build_inapplicable_note(item: "MenuItemTask") -> str | None:
    """Build a note for inapplicable attribute words (e.g., "large" on a non-sized item).

    Pops the first entry from the item's inapplicable_attributes list and returns
    a note like "Just a heads up, Coca-Cola only comes in one size."

    This mirrors question_builder.handle_inapplicable_attributes() but is usable
    outside the config flow (e.g., for non-configurable items).

    Args:
        item: The MenuItemTask to check.

    Returns:
        A note string to prepend to the response, or None if nothing to report.
    """
    if not item.inapplicable_attributes:
        return None

    from orderbot.cache import menu_cache

    entry = item.inapplicable_attributes.pop(0)
    attr_slug = entry.get("attribute_slug", "")
    item_name = item.get_display_name()

    attr_display = menu_cache.get_attribute_display_name(attr_slug)

    if attr_slug == "size":
        return f"Just a heads up, {item_name} only comes in one size."
    else:
        return f"Just a heads up, {item_name} doesn't have {attr_display.lower()} options."
