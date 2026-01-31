"""
Soda/Bottled Beverage Parsing.

Handles parsing of bottled drink orders like "coke", "sprite", "orange juice".
Routes through new_menu_item for disambiguation (not new_coffee which is
reserved for sized beverages).
"""

import re
import logging

from orderbot.menu_data_cache import menu_cache

from ...schemas import OpenInputResponse
from ..constants import WORD_TO_NUM
from .item_building import build_parsed_item

logger = logging.getLogger(__name__)


def _parse_soda_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse soda/bottled drink orders deterministically.

    Routes bottled beverages through new_menu_item for disambiguation,
    not new_coffee (which is reserved for sized beverages like coffee/tea).

    Uses database-loaded beverage item names which includes
    both item names and their aliases.
    """
    text_lower = text.lower()
    soda_types = menu_cache.get_item_names("beverage")

    drink_type = None
    for soda in sorted(soda_types, key=len, reverse=True):
        if re.search(rf'\b{re.escape(soda)}\b', text_lower):
            drink_type = soda
            break

    if not drink_type:
        # Try word-boundary matching on item names FIRST
        # This handles cases like "orange juice" matching "Fresh Squeezed Orange Juice"
        # but NOT matching "Apple Juice" or "Cranberry Juice"
        word_matches = menu_cache.find_items_by_word_match(text_lower)
        if word_matches:
            # Found items containing this phrase - use original term for disambiguation
            logger.debug(
                "Deterministic parse: '%s' word-matches %d items, using for disambiguation",
                text_lower, len(word_matches)
            )
            drink_type = text_lower
        else:
            # Only fall back to generic category clarification if no specific items match
            # This prevents "orange juice" from triggering "show all juices" when
            # specific orange juice items exist
            category_slug = menu_cache.get_category_needing_clarification(text_lower)
            if category_slug:
                logger.info("Deterministic parse: detected generic category term '%s', needs clarification", category_slug)
                return OpenInputResponse(needs_category_clarification=category_slug)
            return None

    # Resolve alias to canonical menu item name from database (e.g., "coke" -> "Coca-Cola")
    # If multiple items match by word, skip alias resolution to allow disambiguation
    word_match_count = len(menu_cache.find_items_by_word_match(drink_type))
    if word_match_count > 1:
        # Multiple items match - don't resolve alias, let item_adder disambiguate
        logger.debug(
            "Deterministic parse: '%s' matches %d items, skipping alias resolution",
            drink_type, word_match_count
        )
        canonical_name = drink_type
    else:
        # Single match or no word matches - resolve alias as before
        canonical_name = menu_cache.resolve_item_alias(drink_type, "beverage") or drink_type
    logger.debug("Deterministic parse: detected soda type '%s' -> canonical '%s'", drink_type, canonical_name)

    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    logger.debug("Deterministic parse: soda order - type=%s, qty=%d", canonical_name, quantity)

    # Build parsed_items for unified handler (Phase 8 dual-write)
    parsed_items = [
        build_parsed_item(
            item_type="menu_item",
            item_name=canonical_name,
            quantity=1,
        )
        for _ in range(quantity)
    ]

    # Phase 4: Only use parsed_items (deprecated fields removed)
    return OpenInputResponse(parsed_items=parsed_items)
