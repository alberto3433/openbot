"""
"Another Item" Parsing.

Contains functions for handling "another X", "one more", and
"make it N [item]" patterns.
"""

import logging
from collections import Counter

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse

from ..intent_patterns import (
    ANOTHER_ITEM_PATTERN,
    ONE_MORE_PATTERN,
    MAKE_IT_N_WITH_ITEM_PATTERN,
)
from ..quantity_utils import parse_make_it_n_quantity
from .item_parsing import (
    build_parsed_item,
    _parse_configurable_item,
)
from .modification_parsing import _extract_menu_item_from_text

logger = logging.getLogger(__name__)


def _resolve_another_as_parsed_item(
    item_keyword: str,
) -> OpenInputResponse | None:
    """Try to parse 'another X' keyword as a complete configurable item order.

    Handles cases like "another 6 bagel package" where the full item name is captured.
    """
    parsed_as_item = _parse_configurable_item(item_keyword)
    if parsed_as_item:
        logger.info("Deterministic parse: 'another %s' parsed as new item", item_keyword)
        return parsed_as_item
    return None


def _resolve_another_as_menu_item(
    item_keyword: str,
) -> OpenInputResponse | None:
    """Try to match 'another X' keyword as a direct menu item name."""
    menu_item, qty, _ = _extract_menu_item_from_text(item_keyword)
    if menu_item:
        item_type_for_item = menu_cache.get_item_type_for_menu_item(menu_item)
        logger.info(
            "Deterministic parse: 'another %s' matched menu item '%s'",
            item_keyword, menu_item,
        )
        parsed_items = [
            build_parsed_item(
                item_type=item_type_for_item or "menu_item",
                item_name=menu_item,
                quantity=1,
            )
            for _ in range(qty)
        ]
        return OpenInputResponse(parsed_items=parsed_items)
    return None


def _resolve_another_as_attribute_option(
    item_keyword: str,
    item_keyword_lower: str,
    item_keyword_singular: str,
) -> OpenInputResponse | None:
    """Check if 'another X' keyword is a known attribute option (e.g., "pound" -> weight).

    If so, treat as "one more of the same" -- mirrors _parse_add_more_request logic.
    """
    is_option, attr_slug = menu_cache.is_known_attribute_option(item_keyword_lower)
    if not is_option:
        is_option, attr_slug = menu_cache.is_known_attribute_option(item_keyword_singular)
    if is_option:
        logger.info(
            "Deterministic parse: 'another %s' is attribute option (attr=%s), treating as duplicate",
            item_keyword, attr_slug,
        )
        return OpenInputResponse(duplicate_last_item=1)
    return None


def _find_exact_word_match_item(
    item_keyword: str,
    item_keyword_lower: str,
    word_matches: list[dict],
) -> OpenInputResponse | None:
    """Given word-boundary matches, return a parsed item if one is an exact name match."""
    for m in word_matches:
        match_name = m.get("name", "")
        if match_name.lower() == item_keyword_lower:
            item_name = m.get("name")
            item_type_for_item = m.get("item_type")
            logger.info(
                "Deterministic parse: 'another %s' exact match menu item '%s'",
                item_keyword, item_name,
            )
            parsed_items = [
                build_parsed_item(
                    item_type=item_type_for_item or "menu_item",
                    item_name=item_name,
                    quantity=1,
                )
            ]
            return OpenInputResponse(parsed_items=parsed_items)
    return None


def _resolve_another_as_item_type(
    item_keyword: str,
    item_keyword_lower: str,
    item_keyword_singular: str,
) -> OpenInputResponse | None:
    """Resolve 'another X' via category keywords, item type triggers, or word-boundary matching.

    Returns a duplicate_new_item_type response, a specific parsed item (if an exact menu item
    name is found), or None if no item type could be resolved.
    """
    resolved_item_type: str | None = None

    # 1. Check category keyword mapping - returns the item type slug
    category_info = menu_cache.get_category_keyword_mapping(item_keyword_lower)
    if not category_info:
        category_info = menu_cache.get_category_keyword_mapping(item_keyword_singular)
    if category_info:
        resolved_item_type = category_info.get("slug")

    # 2. Check if keyword is a trigger for any item type (reverse lookup)
    # BUT first check if it's an exact menu item name - if so, return the specific item
    if not resolved_item_type:
        all_triggers = menu_cache.get_item_type_triggers()  # Returns dict[str, set[str]]
        for item_type_slug, triggers in all_triggers.items():
            if item_keyword_lower in triggers or item_keyword_singular in triggers:
                # Found trigger match - but check if this is also an exact menu item name
                # e.g., "6 bagel package" is both a trigger AND a menu item name
                word_matches = menu_cache.find_items_by_word_match(item_keyword_lower)
                exact_result = _find_exact_word_match_item(
                    item_keyword, item_keyword_lower, word_matches,
                )
                if exact_result:
                    return exact_result
                # No exact match - use item type
                resolved_item_type = item_type_slug
                break

    # 3. Fallback: Try word-boundary matching to find items containing the keyword
    # This handles cases like "tea" matching "Hot Tea", "Iced Tea", etc.
    # Also handles specific menu items with numbers like "6 Bagel Package"
    if not resolved_item_type:
        word_matches = menu_cache.find_items_by_word_match(item_keyword_lower)
        if not word_matches:
            word_matches = menu_cache.find_items_by_word_match(item_keyword_singular)
        if word_matches:
            # Check if any match is an EXACT match to the search term (case-insensitive)
            # This handles "6 bagel package" -> "6 Bagel Package"
            exact_result = _find_exact_word_match_item(
                item_keyword, item_keyword_lower, word_matches,
            )
            if exact_result:
                return exact_result

            # No exact match - find the most common item type among matches
            item_types = [m.get("item_type") for m in word_matches if m.get("item_type")]
            if item_types:
                # Use the most frequent item type
                resolved_item_type = Counter(item_types).most_common(1)[0][0]
                logger.debug(
                    "Deterministic parse: 'another %s' word-matches %d items, item_type '%s'",
                    item_keyword_lower, len(word_matches), resolved_item_type,
                )

    if resolved_item_type:
        # Valid item type keyword - pass the canonical item type to downstream handler
        logger.info(
            "Deterministic parse: 'another %s' detected -> item_type '%s'",
            item_keyword_lower, resolved_item_type,
        )
        return OpenInputResponse(duplicate_new_item_type=resolved_item_type)

    return None


def _try_parse_another_item(text: str) -> OpenInputResponse | None:
    """Check for 'another' patterns, 'one more', and 'make it N [item]'.

    Handles ANOTHER_ITEM_PATTERN (with item type specified), ONE_MORE_PATTERN
    (generic), and MAKE_IT_N_WITH_ITEM_PATTERN.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for "another" patterns (with item type specified)
    # This must be checked BEFORE ONE_MORE_PATTERN since it's more specific
    # Uses data-driven validation against menu_cache triggers
    another_item_match = ANOTHER_ITEM_PATTERN.match(text)
    if another_item_match:
        item_keyword = another_item_match.group(1).strip()
        item_keyword_lower = item_keyword.lower()
        # Get singular form for matching
        item_keyword_singular = singularize(item_keyword_lower)

        # 0. First try to parse the captured text as a complete item order
        result = _resolve_another_as_parsed_item(item_keyword)
        if result:
            return result

        # 1. Try direct menu item match (for non-configurable items)
        result = _resolve_another_as_menu_item(item_keyword)
        if result:
            return result

        # 2. Check if keyword is a known attribute option (e.g., "pound" -> weight)
        result = _resolve_another_as_attribute_option(
            item_keyword, item_keyword_lower, item_keyword_singular,
        )
        if result:
            return result

        # 3. Resolve via category keywords, item type triggers, or word-boundary matching
        result = _resolve_another_as_item_type(
            item_keyword, item_keyword_lower, item_keyword_singular,
        )
        if result:
            return result

        # 4. No item type match - check if it's a generic pronoun/reference
        # "another one", "one more of those", "another of them" should fall through
        generic_refs = {
            "one", "of those", "of them", "of that", "one of those", "one of them",
            "of these", "one of these", "please",
        }
        if item_keyword_lower not in generic_refs:
            # Return for cart lookup
            # e.g., "another bag of chips" -> duplicate_by_reference="bag of chips"
            # The handler will try to match against cart items
            logger.info(
                "Deterministic parse: 'another %s' -> duplicate_by_reference for cart lookup",
                item_keyword,
            )
            return OpenInputResponse(duplicate_by_reference=item_keyword)
        # else: fall through to ONE_MORE_PATTERN

    # Check for "one more" / "another" patterns (without item type)
    if ONE_MORE_PATTERN.match(text):
        logger.info("Deterministic parse: 'one more' / 'another' detected, adding 1 more")
        return OpenInputResponse(duplicate_last_item=1)

    # Check for "make it/that N [item]" BEFORE modification and replacement patterns
    # e.g., "make that two bags of chips" -> change quantity of chips to 2
    # This is more specific than REPLACE_ITEM_PATTERN which would incorrectly match
    make_n_with_item_match = MAKE_IT_N_WITH_ITEM_PATTERN.match(text)
    if make_n_with_item_match:
        num_str = make_n_with_item_match.group(1).lower()
        item_ref = make_n_with_item_match.group(2).strip()
        target_qty = parse_make_it_n_quantity(num_str)

        if target_qty is not None:
            # User says "make that 2 bags of chips" means they want 2 total
            # Return duplicate_by_reference with the additional count needed
            additional = target_qty - 1
            logger.info(
                "Deterministic parse: 'make it N [item]' detected, target=%d, item_ref='%s', adding %d more",
                target_qty, item_ref, additional,
            )
            return OpenInputResponse(
                duplicate_last_item=additional,
                duplicate_by_reference=item_ref,
            )

    return None
