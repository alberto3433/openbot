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
from ..quantity_utils import extract_leading_quantity
from .item_building import build_parsed_item
from .extraction import _detect_inapplicable_modifiers

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

    # Strip ordering phrases and articles (but preserve numbers - they may be part of item names)
    text_lower = re.sub(
        r'^(i\s+want\s+|i\s+would\s+like\s+|i\'?d\s+like\s+|i\'?ll\s+have\s+|i\s+will\s+have\s+|'
        r'can\s+i\s+(get|have)\s+|give\s+me\s+|let\s+me\s+(get|have)\s+)',
        '', text_lower
    )
    text_lower = re.sub(r'^(a|an|the)\s+', '', text_lower)

    # Get all simple (non-configurable) item types from database
    simple_item_types = menu_cache.get_simple_item_types()

    # FIRST: Try exact match with FULL text (including any leading numbers)
    # This handles menu items like "3 Bagel Package" where the number is part of the name
    text_for_exact_match = text_lower.strip()
    matched_item = None
    matched_item_type = None

    for item_type_slug in simple_item_types:
        item_names = menu_cache.get_item_names(item_type_slug)
        # Try to match against item names (longest first for specificity)
        for item_name in sorted(item_names, key=len, reverse=True):
            if re.search(rf'\b{re.escape(item_name)}\b', text_for_exact_match):
                matched_item = item_name
                matched_item_type = item_type_slug
                break
        if matched_item:
            break

    # If exact match found with full text, quantity = 1 (the number is part of the name)
    if matched_item:
        quantity = 1
    else:
        # No exact match - try extracting quantity and matching again
        # This handles "two cookies" -> qty=2, "cookie"
        extracted_qty, remaining = extract_leading_quantity(text_lower)
        if extracted_qty is not None:
            quantity = extracted_qty
            text_lower = remaining
            # Singularize after extracting quantity: "two cookies" -> "cookie"
            text_lower = singularize(text_lower)
        else:
            quantity = 1

        # Try each simple item type with the quantity-stripped text
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
        # FIRST: Try with FULL original text (including numbers) to match items like "3 Bagel Package"
        # If that gives a single match, use it (the number is part of the name, not a quantity)
        full_text_matches = menu_cache.find_items_by_word_match(text_for_exact_match)
        if len(full_text_matches) == 1:
            # Exact single match with full text - the number is part of the item name
            matched_item = full_text_matches[0].get("name")
            matched_item_type = full_text_matches[0].get("item_type")
            quantity = 1  # Override any extracted quantity
            logger.debug(
                "Deterministic parse: '%s' single word-match to '%s', treating as exact item",
                text_for_exact_match, matched_item
            )
        else:
            # Multiple matches or no matches - try with quantity-stripped text
            word_matches = menu_cache.find_items_by_word_match(text_lower)
            if not word_matches:
                singularized = singularize(text_lower)
                if singularized != text_lower:
                    word_matches = menu_cache.find_items_by_word_match(singularized)
                    if word_matches:
                        text_lower = singularized  # Use singularized form going forward
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

    # Detect inapplicable modifiers (globally known but not valid for this item)
    unrecognized = _detect_inapplicable_modifiers(text_lower)

    # Build parsed_items
    parsed_items = [
        build_parsed_item(
            item_type="menu_item",
            item_name=canonical_name,
            quantity=1,
            unrecognized_ingredients=unrecognized,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(parsed_items=parsed_items)
