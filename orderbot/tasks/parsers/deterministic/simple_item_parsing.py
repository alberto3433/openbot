"""
Simple Item Parsing.

Handles parsing of simple menu items that don't require configuration,
such as beverages, pastries, sides, snacks, etc.

These items can be added directly to an order without asking additional
questions (no size, temperature, or customization needed).
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse
from ..constants import WORD_TO_NUM
from .item_building import build_parsed_item

logger = logging.getLogger(__name__)


def _parse_simple_item_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse simple menu item orders deterministically.

    Iterates through all simple (non-configurable) item types and tries
    to match the input against their menu items.

    Simple item types are those with no attributes to ask about,
    like beverages, pastries, sides, snacks, etc.

    Uses database-loaded item names and aliases for matching.
    """
    text_lower = text.lower()

    # Strip ordering phrases and articles
    text_lower = re.sub(
        r'^(i\s+want\s+|i\'?d\s+like\s+|can\s+i\s+(get|have)\s+|give\s+me\s+|let\s+me\s+(get|have)\s+)',
        '', text_lower
    )
    text_lower = re.sub(r'^(a|an|the)\s+', '', text_lower)

    # Extract quantity EARLY - before matching
    # This ensures "two cookies" -> qty=2, text_lower="cookie" (singularized)
    quantity = 1
    qty_match = re.match(r'^(\d+|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        text_lower = text_lower[qty_match.end():]  # Strip quantity from text
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)
        # Singularize after extracting quantity: "two cookies" -> "cookie"
        text_lower = singularize(text_lower)

    # Get all simple (non-configurable) item types from database
    simple_item_types = menu_cache.get_simple_item_types()

    matched_item = None
    matched_item_type = None

    # Try each simple item type
    for item_type_slug in simple_item_types:
        item_names = menu_cache.get_item_names(item_type_slug)

        # Try to match against item names (longest first for specificity)
        for item_name in sorted(item_names, key=len, reverse=True):
            if re.search(rf'\b{re.escape(item_name)}\b', text_lower):
                matched_item = item_name
                matched_item_type = item_type_slug
                break

        if matched_item:
            break

    if not matched_item:
        # Check if this is a generic category term (like just "soda" or "pastry")
        category_slug = menu_cache.is_category_reference(text_lower)
        if category_slug:
            logger.info(
                "Deterministic parse: exact generic category term '%s', needs clarification",
                category_slug
            )
            return OpenInputResponse(needs_category_clarification=category_slug)

        # Try word-boundary matching for partial matches
        word_matches = menu_cache.find_items_by_word_match(text_lower)
        if word_matches:
            logger.debug(
                "Deterministic parse: '%s' word-matches %d items, using for disambiguation",
                text_lower, len(word_matches)
            )
            matched_item = text_lower
            # Determine item type from first match
            first_match = word_matches[0]
            matched_item_type = first_match.get("item_type")
        else:
            return None

    # Resolve alias to canonical menu item name
    word_match_count = len(menu_cache.find_items_by_word_match(matched_item))
    if word_match_count > 1:
        # Multiple items match - don't resolve alias, let item_adder disambiguate
        logger.debug(
            "Deterministic parse: '%s' matches %d items, skipping alias resolution",
            matched_item, word_match_count
        )
        canonical_name = matched_item
    else:
        # Single match - resolve alias if we know the item type
        if matched_item_type:
            canonical_name = menu_cache.resolve_item_alias(matched_item, matched_item_type) or matched_item
        else:
            canonical_name = matched_item

    logger.debug(
        "Deterministic parse: simple item '%s' -> canonical '%s' (type=%s, qty=%d)",
        matched_item, canonical_name, matched_item_type, quantity
    )

    # Build parsed_items
    parsed_items = [
        build_parsed_item(
            item_type="menu_item",
            item_name=canonical_name,
            quantity=1,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(parsed_items=parsed_items)


# Backward compatibility alias
_parse_soda_deterministic = _parse_simple_item_deterministic
