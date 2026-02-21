"""
By-the-Pound Order Parsing.

Handles parsing of weight-based orders like "half a pound of whitefish salad",
"quarter pound of muenster", etc.

This parser MUST be called BEFORE menu item parsing to prevent items like
"whitefish salad" from being matched to "Whitefish Salad Sandwich".
"""

import re
import logging

from ...schemas import OpenInputResponse, ParsedItemEntry, Selection
from ..constants import find_item_by_unit_type
from orderbot.cache import menu_cache
from ...utils.text import normalize_text

logger = logging.getLogger(__name__)


# Pattern to match by-weight orders like "half a pound of whitefish salad"
# Captures: quantity phrase + item name
BY_POUND_PATTERN = re.compile(
    r"""
    (?:
        ((?:a\s+)?half\s+(?:a\s+)?(?:pound|lb))    # a half pound / half a pound / half pound / half lb
        |(\d+(?:\s*/\s*\d+)?)\s*(?:pound|lb)s?     # 1/4 pound, 2 pounds, 1 lb
        |(a\s+(?:pound|lb))                        # a pound / a lb
        |((?:a\s+)?quarter\s+(?:pound|lb))         # a quarter pound / quarter pound / quarter lb
    )
    \s+(?:of\s+)?
    (.+?)                                          # item name
    (?:\s+please)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)


def _find_by_weight_item(item_name: str) -> tuple[str, str] | None:
    """
    Find a by-weight item and its item type by name or alias.

    Uses the generic find_item_by_unit_type() to look up items sold by weight.
    The cache handles exact matches, partial matches, and aliases
    (e.g., "lox" -> "Nova Scotia Salmon").

    Args:
        item_name: The item name to look up (e.g., "whitefish salad", "muenster", "lox")

    Returns:
        Tuple of (canonical_name, item_type_slug) or None if not found.
    """
    return find_item_by_unit_type(item_name, "by_weight")


def _find_by_weight_items_partial(search_term: str) -> list[tuple[str, str]]:
    """Find all by-weight items matching a search term (for disambiguation).

    Args:
        search_term: The term to search for (e.g., "salmon")

    Returns:
        List of (canonical_name, item_type_slug) tuples for matching items.
    """
    return menu_cache.find_items_by_unit_type_partial(search_term, "by_weight")


def _parse_by_pound_order(text: str) -> OpenInputResponse | None:
    """
    Parse by-the-pound orders like "half a pound of whitefish salad".

    This MUST be called BEFORE menu item parsing to prevent items like
    "whitefish salad" from being matched to "Whitefish Salad Sandwich".

    Returns:
        OpenInputResponse with by_pound_items if matched, None otherwise.
    """
    text_lower = normalize_text(text)

    # Strip common action verb prefixes - these indicate intent, not item type
    # The quantity phrase ("quarter pound", "half pound") identifies by-the-pound orders
    action_prefixes = [
        "i'll have ", "i will have ", "i have ", "i'll take ", "i will take ", "i take ",
        "i'll get ", "i will get ", "i get ", "i want ", "i'd like ", "i would like ",
        "i like ", "i need ", "give me ", "can i have ", "can i get ", "let me get ",
        "let me have ", "may i have ", "could i get ", "could i have ",
    ]
    for prefix in action_prefixes:
        if text_lower.startswith(prefix):
            text_lower = text_lower[len(prefix):]
            break

    match = BY_POUND_PATTERN.match(text_lower)
    if not match:
        return None

    # Extract weight and convert to (size, quantity) pair
    # Available sizes in DB: "1/4 lb" and "1 lb"
    half_lb = match.group(1)
    numeric_lb = match.group(2)
    a_lb = match.group(3)
    quarter_lb = match.group(4)
    item_name = match.group(5).strip()

    # Convert weight phrases to (size, quantity) pairs
    # size is "1/4 lb" or "1 lb", quantity is how many of that size
    if quarter_lb:
        size = "1/4 lb"
        item_quantity = 1
    elif half_lb:
        size = "1/4 lb"
        item_quantity = 2
    elif numeric_lb:
        # Handle fractions like "1/4", "1/2", "3/4"
        if "/" in numeric_lb:
            num, denom = numeric_lb.replace(" ", "").split("/")
            fraction = float(num) / float(denom)
            if fraction <= 0.25:
                size = "1/4 lb"
                item_quantity = 1
            elif fraction <= 0.5:
                size = "1/4 lb"
                item_quantity = 2
            elif fraction <= 0.75:
                size = "1/4 lb"
                item_quantity = 3
            else:
                size = "1 lb"
                item_quantity = 1
        else:
            # Whole number of pounds
            num = int(numeric_lb)
            size = "1 lb"
            item_quantity = num
    elif a_lb:
        size = "1 lb"
        item_quantity = 1
    else:
        size = "1 lb"
        item_quantity = 1

    # Look up the item in database via find_item_by_unit_type
    result = _find_by_weight_item(item_name)
    if not result:
        # No exact match - try partial matching for disambiguation
        partial_matches = _find_by_weight_items_partial(item_name)
        if not partial_matches:
            logger.debug("By-weight pattern matched but item not found: '%s'", item_name)
            return None

        if len(partial_matches) == 1:
            # Single partial match - use it
            canonical_name, item_type_slug = partial_matches[0]
            logger.info(
                "BY-WEIGHT ORDER: single partial match for '%s' -> %s",
                item_name, canonical_name
            )
        else:
            # Multiple matches - return the search term as item_name for disambiguation
            # item_adder_handler will trigger disambiguation when it finds multiple matches
            _, item_type_slug = partial_matches[0]  # Use first match's item_type
            canonical_name = item_name  # Use search term, not canonical name
            logger.info(
                "BY-WEIGHT ORDER: multiple matches for '%s' (%d options) - will trigger disambiguation",
                item_name, len(partial_matches)
            )
    else:
        canonical_name, item_type_slug = result

    # Look up the correct attribute slug for this item type (data-driven)
    # e.g., "cheese" uses "weight", "sized_beverage" uses "size"
    attr_slug = menu_cache.get_first_priced_attribute(item_type_slug)
    if not attr_slug:
        # Fallback to "weight" for by-weight items if no priced attribute found
        attr_slug = "weight"

    # Resolve the option slug from the display name (data-driven)
    # e.g., "1 lb" -> {"slug": "one_pound", "display_name": "1 lb", ...}
    option = menu_cache.resolve_option_by_alias(attr_slug, size)
    if option:
        option_slug = option.get("slug", size)
        option_display = option.get("display_name", size)
    else:
        # Fallback: convert display name to slug format
        option_slug = size.replace(" ", "_").replace("/", "_")
        option_display = size

    logger.info(
        "BY-WEIGHT ORDER: '%s' -> %s (attr=%s, option=%s, qty=%d, item_type=%s)",
        text[:50], canonical_name, attr_slug, option_slug, item_quantity, item_type_slug
    )

    # Build parsed_items using ParsedItemEntry (unified type)
    # Use the data-driven attribute slug and option slug
    parsed_items = [
        ParsedItemEntry(
            item_type=item_type_slug,  # "cheese", "fish", "spread", etc.
            item_name=canonical_name,
            quantity=item_quantity,
            selections=[Selection(slug=option_slug, category=attr_slug, display_name=option_display)],
        )
    ]

    return OpenInputResponse(
        parsed_items=parsed_items,
    )
