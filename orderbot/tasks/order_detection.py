"""
Order Attempt Detection Module.

Provides utilities for detecting order attempt patterns and generating
dynamic help text from database item types.

Extracted from taking_items_handler.py for better separation of concerns.
"""

import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from .utils.text import format_english_list, normalize_text

if TYPE_CHECKING:
    pass

__all__ = [
    "ORDER_ATTEMPT_PATTERNS",
    "extract_order_item_name",
    "looks_like_order_attempt",
    "looks_like_availability_question",
    "extract_availability_item_name",
    "get_dynamic_help_text",
]


# Patterns that indicate user is trying to order something
ORDER_ATTEMPT_PATTERNS = [
    re.compile(r"^(?:i(?:'?d| would)?\s+(?:like|want|love)|(?:can|could)\s+i\s+(?:have|get)|"
               r"(?:give|get)\s+me|i(?:'?ll)?\s+(?:have|take|get)|"
               r"(?:let\s+me\s+(?:have|get)))\s+(.+)", re.IGNORECASE),
    re.compile(r"^(?:(?:one|two|three|a|an|some)\s+)?(.+?)(?:\s+please)?$", re.IGNORECASE),
]


def extract_order_item_name(text: str) -> str | None:
    """Extract the item name from an ordering phrase.

    Args:
        text: User input like "I want home fries" or "can I have a croissant"

    Returns:
        The item name (e.g., "home fries", "croissant") or None if not an order.
    """
    text = text.strip()

    # Try explicit order patterns first
    for pattern in ORDER_ATTEMPT_PATTERNS[:-1]:  # Skip the fallback pattern
        match = pattern.match(text)
        if match:
            item = match.group(1).strip()
            # Clean up common suffixes
            item = re.sub(r"\s+please\s*$", "", item, flags=re.IGNORECASE)
            item = re.sub(r"\s+thanks?\s*$", "", item, flags=re.IGNORECASE)
            if item and len(item) > 1:
                return item

    return None


def looks_like_order_attempt(text: str) -> bool:
    """Check if text looks like user is trying to order something.

    Args:
        text: User input

    Returns:
        True if the input looks like an order attempt.
    """
    text_lower = normalize_text(text)

    # Check for common order phrases
    order_indicators = [
        "i want", "i'd like", "i would like", "i'll have", "i'll take",
        "can i have", "can i get", "could i have", "could i get",
        "give me", "get me", "let me have", "let me get",
        "i need", "i'll get", "i'll order",
    ]
    return any(indicator in text_lower for indicator in order_indicators)


# Pattern for availability questions like "do you sell X?", "do sell X?" (typo)
_AVAILABILITY_PATTERN = re.compile(
    r"do\s+(?:you\s+)?(?:sell|carry|offer)\s+(?:any\s+)?(.+?)(?:\?|$)",
    re.IGNORECASE,
)


def looks_like_availability_question(text: str) -> bool:
    """Check if text looks like a product availability question.

    Catches well-formed ("do you sell X?") and typo ("do sell X?") variants.

    Args:
        text: User input

    Returns:
        True if the input looks like an availability question.
    """
    return bool(_AVAILABILITY_PATTERN.search(text.strip()))


def extract_availability_item_name(text: str) -> str | None:
    """Extract the item name from an availability question.

    Args:
        text: User input like "do you sell pepsi?" or "do sell liquor?"

    Returns:
        The item name (e.g., "pepsi", "liquor") or None.
    """
    match = _AVAILABILITY_PATTERN.search(text.strip())
    if match:
        item = match.group(1).strip().rstrip('?!.')
        if item and len(item) > 1:
            return item
    return None


def get_dynamic_help_text() -> str:
    """Generate help text dynamically from database item types.

    Returns a help message listing available item categories from the database
    instead of hardcoding specific items like 'bagels, coffee, sandwiches'.
    """
    try:
        item_types = menu_cache.get_all_item_type_slugs()
        # Get plural display names for user-friendly output
        display_names = []
        for slug in sorted(item_types):
            name = menu_cache.get_item_type_display_name(slug, plural=True)
            if name and name != slug:  # Only include if we have a proper display name
                display_names.append(name)

        if display_names:
            # Take first few for a concise message
            if len(display_names) > 3:
                items_text = ", ".join(display_names[:3]) + ", and more"
            else:
                items_text = format_english_list(display_names)
            return f"I can help you order {items_text} from our menu. Just tell me what you'd like!"
        else:
            return "I can help you order from our menu. Just tell me what you'd like!"
    except (ValueError, KeyError, TypeError, AttributeError):
        # Fallback if cache not loaded
        return "I can help you order from our menu. Just tell me what you'd like!"
