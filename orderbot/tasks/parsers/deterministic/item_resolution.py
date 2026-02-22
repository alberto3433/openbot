"""
Item Resolution for Deterministic Parser.

Functions for resolving user text to menu items, handling modifications,
replacement patterns, direct menu item lookups, and standalone ingredients.
"""

import re
import logging
from typing import Literal

from orderbot.cache import menu_cache

from ...schemas import OpenInputResponse, Selection

from ..quantity_utils import QTY_WORDS_RE
from ..intent_patterns import REPLACE_ITEM_PATTERN
from .pipeline import get_pipeline
from .result_types import TextSpan
from .item_parsing import build_parsed_item, _parse_configurable_item, _parse_split_quantity_items
from .simple_item_parsing import _parse_simple_item_deterministic
from .modification_parsing import (
    _extract_menu_item_modifications,
    _parse_modify_existing_item,
    _extract_menu_item_from_text,
)
from .tokenization import _parse_multi_item_order
from .extraction import _detect_inapplicable_attributes
from .text_cleaning import _extract_replacement_item, _filter_duplicate_modifications, _strip_leading_attribute_words
from .order_type_parsing import _add_order_type_to_response
from ...utils.text import normalize_text

logger = logging.getLogger(__name__)


def _try_parse_modification(text: str) -> OpenInputResponse | None:
    """Check for modify-existing-item and replacement phrases.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for modification to existing item BEFORE replacement patterns
    # This catches patterns like "make the bagel with scallion cream cheese"
    # which should modify an existing bagel, not trigger replace_last_item
    modify_existing_result = _parse_modify_existing_item(text)
    if modify_existing_result:
        return modify_existing_result

    # Check for replacement phrases
    replace_match = REPLACE_ITEM_PATTERN.match(text)
    if replace_match:
        replacement_item = _extract_replacement_item(replace_match)
        if replacement_item:
            logger.info("Deterministic parse: replacement detected, item='%s'", replacement_item)

            # Deferred import to avoid circular dependency
            from .core import parse_open_input_deterministic
            parsed_replacement = parse_open_input_deterministic(replacement_item)
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    return None


def _parse_direct_menu_item(text: str) -> OpenInputResponse | None:
    """Match text against direct (non-configurable) menu items from the database.

    Performs item lookup, attribute extraction (excluding the matched item name span),
    modification extraction, and deduplication. Returns parsed items with quantity.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if a menu item matched, None otherwise.
    """
    menu_item, qty, matched_alias = _extract_menu_item_from_text(text)
    if not menu_item:
        return None

    item_type_for_mods = menu_cache.get_item_type_for_menu_item(menu_item)

    # Find the span where the menu item name appears in the text to exclude from
    # attribute matching. This prevents words within the menu item name (e.g., "butter"
    # in "Cinnamon Sugar Butter Sandwich") from matching as attributes.
    # Use the matched_alias (the text that actually matched) instead of the canonical
    # name, since the user may have typed an alias like "cinnamon butter sandwich".
    menu_item_span = None
    text_lower = text.lower()
    search_terms = [matched_alias, menu_item.lower()] if matched_alias else [menu_item.lower()]
    for search_term in search_terms:
        if search_term:
            pos = text_lower.find(search_term.lower())
            if pos != -1:
                menu_item_span = (pos, pos + len(search_term))
                break

    attr_result = None
    if item_type_for_mods:
        exclude_spans = [TextSpan(start=menu_item_span[0], end=menu_item_span[1])] if menu_item_span else None
        attr_result = get_pipeline().extract_attributes(text, item_type_for_mods, exclude_spans)

    modifications = _extract_menu_item_modifications(text, item_type_for_mods)
    # Deduplicate: remove modifications whose ingredient is already matched
    # as an attribute option (e.g., "jalapeño cream" modifier when attribute
    # extraction already matched it as spread → jalapeno_cc)
    if attr_result and modifications.get("additions"):
        modifications["additions"] = _filter_duplicate_modifications(
            modifications["additions"], attr_result, item_type_for_mods
        )

    attr_keys = list(attr_result.values.keys()) if attr_result else []
    logger.info(
        "DETERMINISTIC MENU ITEM: matched '%s' -> %s (qty=%d, attrs=%s, mods=%s)",
        text[:50], menu_item, qty, attr_keys, modifications,
    )

    # Convert structured modifications to Selection objects
    mod_list = []
    for add in modifications.get("additions", []):
        mod_list.append(Selection(slug=add["slug"], category=add.get("category")))
    for rem in modifications.get("removals", []):
        mod_list.append(Selection(slug=f"no_{rem['slug']}", category=rem.get("category")))

    # Detect inapplicable attribute words: known attribute options (e.g., "small")
    # that don't apply to this item type (e.g., sandwich has no size attribute)
    inapplicable_attrs = _detect_inapplicable_attributes(
        text_lower, menu_item, menu_item_span, item_type_for_mods
    )

    parsed_items = [
        build_parsed_item(
            item_type=item_type_for_mods or "menu_item",
            item_name=menu_item,
            quantity=1,
            original_text=text,
            attr_result=attr_result,
            modifiers=mod_list,
            inapplicable_attributes=inapplicable_attrs,
        )
        for _ in range(qty)
    ]
    return OpenInputResponse(parsed_items=parsed_items)


def _try_parse_new_items(
    text: str,
    order_type: Literal["pickup", "delivery"] | None,
    *,
    _is_retry: bool = False,
) -> OpenInputResponse | None:
    """Check for new item orders: split-quantity, multi-item, configurable, direct lookup, simple.

    Also checks for standalone ingredient orders.

    Args:
        text: Cleaned user input text.
        order_type: Detected order type to attach to response, or None.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for split-quantity items (e.g., "two bagels one with lox one with cream cheese")
    # This MUST run BEFORE configurable_item to handle multi-item orders with different configs
    # Generic, data-driven parser that works for any configurable item type
    split_qty_result = _parse_split_quantity_items(text)
    if split_qty_result:
        return _add_order_type_to_response(split_qty_result, order_type)

    # Check for multi-item orders (e.g., "the leo and avocado toast")
    # Must run BEFORE single-item parsers to handle "X and Y" patterns
    # Has built-in logic to avoid splitting modifier chains like "bagel with butter and cream cheese"
    multi_item_result = _parse_multi_item_order(text)
    if multi_item_result:
        return _add_order_type_to_response(multi_item_result, order_type)

    # Check for configurable items using data-driven patterns
    # This ensures "bagel with cream cheese" goes to bagel parser, not cream cheese menu item
    configurable_item_result = _parse_configurable_item(text)
    if configurable_item_result:
        return _add_order_type_to_response(configurable_item_result, order_type)

    # Data-driven menu item lookup - runs AFTER configurable item parsing
    direct_result = _parse_direct_menu_item(text)
    if direct_result:
        return _add_order_type_to_response(direct_result, order_type)

    # Check for simple items (beverages, pastries, sides, etc. - no config needed)
    simple_result = _parse_simple_item_deterministic(text)
    if simple_result:
        logger.info("DETERMINISTIC SIMPLE ITEM: matched '%s'", text[:50])
        return _add_order_type_to_response(simple_result, order_type)

    # Check if user ordered just an ingredient/modifier without specifying an item
    # e.g., "I want caramel syrup" - we should suggest items that can have this modifier
    ingredient_result = _check_standalone_ingredient(text)
    if ingredient_result:
        return ingredient_result

    # Fallback: strip leading attribute option words and retry
    # Handles cases like "large orange juice" where "large" is a size attribute word
    # but Orange Juice is non-configurable, so the attribute word is just noise.
    # Only runs after ALL parsers fail, so legitimate matches are never affected.
    if not _is_retry:
        stripped_text = _strip_leading_attribute_words(text)
        if stripped_text:
            logger.info(
                "ATTR_STRIP_RETRY: retrying with '%s' (original: '%s')",
                stripped_text, text[:50],
            )
            return _try_parse_new_items(stripped_text, order_type, _is_retry=True)

    return None


def _check_standalone_ingredient(text: str) -> OpenInputResponse | None:
    """Check if user input is just an ingredient that could be a modifier.

    Handles cases like "I want caramel syrup" where the user orders a modifier
    without specifying an item. We should suggest items that can have this modifier.

    Args:
        text: User input text

    Returns:
        OpenInputResponse with found_ingredient_without_item=True if matched,
        None otherwise.
    """
    # Strip common ordering phrases
    text_lower = normalize_text(text)
    for prefix in ["i want ", "i'd like ", "i would like ", "i'll do ", "i'll take ",
                    "i'll have ", "i'll get ", "i'll grab ", "give me ", "can i get ", "can i have "]:
        if text_lower.startswith(prefix):
            text_lower = text_lower[len(prefix):].strip()
            break

    # Strip articles
    for article in ["a ", "an ", "some ", "the "]:
        if text_lower.startswith(article):
            text_lower = text_lower[len(article):].strip()
            break

    # Check if it's a known ingredient that can be a modifier
    normalized = menu_cache.normalize_modifier(text_lower)
    if normalized:
        # Check if this ingredient can be added to any item types
        item_types = menu_cache.get_item_types_for_ingredient(text_lower)
        if item_types:
            logger.info(
                "STANDALONE INGREDIENT: '%s' -> ingredient='%s', can be added to %d item types",
                text[:50], normalized, len(item_types)
            )
            return OpenInputResponse(
                found_ingredient_without_item=True,
                found_ingredient_name=normalized,
            )

    return None
