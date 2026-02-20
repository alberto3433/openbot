"""
Inquiry Dispatch - Routes user input to appropriate inquiry sub-parsers.

Handles all inquiry types (price, dietary, menu, store, modifier, ingredient, etc.)
as well as add-modifier patterns, more-of-same, and by-the-pound orders that must
be checked in specific order relative to inquiry parsers.
"""

import logging

from ...schemas import OpenInputResponse
from ..intent_patterns import MORE_OF_SAME_PATTERN
from .result_types import ParserContext
from .by_pound_parsing import _parse_by_pound_order
from .inquiry import (
    parse_attribute_inquiry,
    parse_price_inquiry,
    parse_menu_query,
    parse_recommendation_inquiry,
    parse_store_info_inquiry,
    parse_item_description_inquiry,
    parse_modifier_inquiry,
    parse_more_menu_items,
    parse_ingredient_search,
    parse_dietary_inquiry,
    parse_signature_menu_inquiry,
)
from .modification_parsing import _parse_add_modifier_to_item

logger = logging.getLogger(__name__)


def _try_parse_inquiry(text: str, ctx: ParserContext) -> OpenInputResponse | None:
    """Check for all inquiry types: price, dietary, menu, store, modifier, ingredient, etc.

    Also handles add-modifier patterns, more-of-same, and by-the-pound orders since
    they must be checked in specific order relative to inquiry parsers.

    Args:
        text: Cleaned user input text.
        ctx: Parser context with modifier/ingredient keyword mappings.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for price inquiries
    price_result = parse_price_inquiry(text)
    if price_result:
        return price_result

    # Check for add-modifier patterns ("add bacon", "extra cheese", "more cheese")
    # This MUST run BEFORE parse_more_menu_items() because "more cheese" would otherwise
    # be caught by the "^more\b" pattern in MORE_MENU_ITEMS_PATTERNS
    add_modifier_result = _parse_add_modifier_to_item(text)
    if add_modifier_result:
        return add_modifier_result

    # Check for "more [item reference]" BEFORE parse_more_menu_items()
    # This catches "more chips" style requests that should duplicate cart items
    # rather than being treated as menu inquiry ("show me more options")
    more_of_same_match = MORE_OF_SAME_PATTERN.match(text)
    if more_of_same_match:
        item_ref = more_of_same_match.group(1).strip().lower()
        # Exclude menu inquiry words - these should fall through to parse_more_menu_items
        menu_inquiry_words = {
            "options", "items", "please", "of those", "of them", "of that",
            "choices", "things", "stuff", "menu", "food",
        }
        if item_ref not in menu_inquiry_words:
            logger.info("Deterministic parse: 'more %s' -> duplicate_by_reference", item_ref)
            return OpenInputResponse(duplicate_by_reference=item_ref)

    # Check for specials/signature menu inquiries BEFORE recommendation
    # "do you have any specials today?" must match as signature menu, not recommendation
    signature_result = parse_signature_menu_inquiry(text)
    if signature_result:
        return signature_result

    # Check for recommendation questions BEFORE "show more" menu requests
    # "what else do you think I should get?" must not be caught by MORE_MENU_ITEMS_PATTERNS
    recommendation_result = parse_recommendation_inquiry(text)
    if recommendation_result:
        return recommendation_result

    # Check for "show more" menu requests BEFORE menu queries
    # "what other pastries do you have?" should be pagination, not a new query
    more_items_result = parse_more_menu_items(text)
    if more_items_result:
        return more_items_result

    # Check for attribute option inquiries ("what bagel types do you have?")
    # Must run BEFORE parse_menu_query to prevent "bagel types" being treated as menu category
    attribute_inquiry_result = parse_attribute_inquiry(text)
    if attribute_inquiry_result:
        return attribute_inquiry_result

    # Check for dietary/allergen/availability/customization inquiries
    # Must run BEFORE parse_menu_query since "do you have vegan sandwiches?" is a
    # dietary+category query that should be handled specially, not as a generic menu query
    dietary_result = parse_dietary_inquiry(text)
    if dietary_result:
        return dietary_result

    # Check for ingredient-based menu search BEFORE menu query
    # "what menu items do you have with egg whites?" should find items containing
    # that ingredient, not be treated as a generic menu category query
    ingredient_search_result = parse_ingredient_search(text, ctx.ingredient_to_items)
    if ingredient_search_result:
        return ingredient_search_result

    # Check for menu category queries ("what sweets do you have?", "what desserts do you have?")
    menu_query_result = parse_menu_query(text)
    if menu_query_result:
        return menu_query_result

    # Check for store info inquiries
    store_info_result = parse_store_info_inquiry(text)
    if store_info_result:
        return store_info_result

    # Check for item description inquiries
    item_desc_result = parse_item_description_inquiry(text)
    if item_desc_result:
        return item_desc_result

    # Check for modifier/add-on inquiries
    modifier_inquiry_result = parse_modifier_inquiry(
        text, ctx.modifier_category_keywords, ctx.modifier_item_keywords
    )
    if modifier_inquiry_result:
        return modifier_inquiry_result

    # Check for by-the-pound orders EARLY
    # Must be checked BEFORE spread/salad sandwich matching to prevent
    # "half a pound of whitefish salad" from matching "Whitefish Salad Sandwich"
    by_pound_result = _parse_by_pound_order(text)
    if by_pound_result:
        return by_pound_result

    return None
