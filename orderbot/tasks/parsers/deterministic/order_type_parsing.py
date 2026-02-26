"""
Order Type (Pickup/Delivery) Parsing.

Contains functions for detecting and stripping pickup/delivery order type
phrases from user input.
"""

import re
import logging
from typing import Literal

from ...schemas import OpenInputResponse

from .meta_parsing import _is_only_filler

logger = logging.getLogger(__name__)


# Patterns for pickup/delivery detection
ORDER_TYPE_PATTERNS: dict[str, re.Pattern] = {
    "pickup": re.compile(
        r"(?:place\s+)?(?:a\s+)?(?:pick[\s-]?up)\s+order"
        r"|(?:for|is\s+for)\s+(?:pick[\s-]?up)"
        r"|i(?:'ll|\s+will)\s+pick\s+(?:it\s+)?up"
        r"|(?:^|\s)(?:pick[\s-]?up)(?:\s+please)?(?:$|\s)",
        re.IGNORECASE
    ),
    "delivery": re.compile(
        r"(?:place\s+)?(?:a\s+)?delivery\s+order"
        r"|(?:for|is\s+for)\s+delivery"
        r"|to\s+be\s+deliver(?:y|ed)"
        r"|can\s+you\s+deliver"
        r"|(?:^|\s)delivery(?:\s+please)?(?:$|\s)",
        re.IGNORECASE
    ),
}


def _extract_order_type(text: str) -> Literal["pickup", "delivery"] | None:
    """Extract pickup/delivery order type from text.

    Args:
        text: User input text

    Returns:
        "pickup", "delivery", or None if not detected
    """
    for order_type, pattern in ORDER_TYPE_PATTERNS.items():
        if pattern.search(text):
            return order_type  # type: ignore[return-value]
    return None


def _strip_order_type_phrase(text: str) -> str:
    """Remove order type phrases from text to continue parsing remaining content.

    Args:
        text: User input text

    Returns:
        Text with order type phrases removed
    """
    result = text
    # Remove common order type phrases
    result = re.sub(
        r"(?:i(?:'d| would) like to )?(?:do\s+|place\s+|make\s+|get\s+)?(?:a\s+)?(?:pick[\s-]?up|delivery)\s+order",
        "", result, flags=re.IGNORECASE
    )
    result = re.sub(r"(?:for|is\s+for)\s+(?:pick[\s-]?up|delivery)", "", result, flags=re.IGNORECASE)
    result = re.sub(r"i(?:'ll|\s+will)\s+pick\s+(?:it\s+)?up", "", result, flags=re.IGNORECASE)
    result = re.sub(r"to\s+be\s+deliver(?:y|ed)", "", result, flags=re.IGNORECASE)
    result = re.sub(r"can\s+you\s+deliver", "", result, flags=re.IGNORECASE)
    result = re.sub(r"(?:^|\s)(?:pick[\s-]?up|delivery)(?:\s+please)?(?:$|\s)", " ", result, flags=re.IGNORECASE)
    return result.strip()


# Patterns for unsupported dining options (to go / for here / dine in)
DINING_OPTION_PATTERNS: dict[str, re.Pattern] = {
    "to go": re.compile(r"(?<!good\s)\bto[\s-]go\b", re.IGNORECASE),
    "for here": re.compile(r"\bfor\s+here\b", re.IGNORECASE),
    "dine in": re.compile(r"\b(?:dine|eat)[\s-]?in\b", re.IGNORECASE),
}


def _extract_dining_option(text: str) -> str | None:
    """Extract unsupported dining option phrase from text.

    Args:
        text: User input text

    Returns:
        The matched phrase (e.g., "to go", "for here") or None
    """
    for label, pattern in DINING_OPTION_PATTERNS.items():
        if pattern.search(text):
            return label
    return None


def _strip_dining_option_phrase(text: str) -> str:
    """Remove dining option phrases from text to continue parsing remaining content.

    Args:
        text: User input text

    Returns:
        Text with dining option phrases removed
    """
    result = text
    for pattern in DINING_OPTION_PATTERNS.values():
        result = pattern.sub("", result)
    # Clean up leftover whitespace
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result


def _add_order_type_to_response(
    response: OpenInputResponse | None,
    order_type: Literal["pickup", "delivery"] | None
) -> OpenInputResponse | None:
    """Add order_type to a response if it has parsed_items.

    Args:
        response: The parser response (may be None)
        order_type: The detected order type (may be None)

    Returns:
        Response with order_type added if applicable, otherwise unchanged
    """
    if response is None or order_type is None:
        return response

    # Only add order_type if response has items
    if response.parsed_items:
        response.order_type = order_type

    return response
