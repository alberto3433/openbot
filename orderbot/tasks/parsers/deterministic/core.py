"""
Core Deterministic Parser - Main Entry Point.

This module contains the main deterministic parsing function that orchestrates
all sub-parsers to parse user input without LLM calls.
"""

import re
import logging
from typing import Literal

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse, Selection

from ..constants import (
    GRATITUDE_PATTERNS,
    HELP_PATTERNS,
    REPEAT_ORDER_PATTERNS,
)
from ..intent_patterns import (
    strip_conversational_fillers,
    MAKE_IT_N_PATTERN,
    REDUCE_TO_ONE_PATTERN,
    ONE_MORE_PATTERN,
    ANOTHER_ITEM_PATTERN,
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
)
from .extraction import extract_attribute_values
from .item_parsing import (
    build_parsed_item,
    _parse_configurable_item,
    _parse_split_quantity_items,
)
from .simple_item_parsing import _parse_simple_item_deterministic
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
from .modification_parsing import (
    _extract_menu_item_modifications,
    _parse_modify_existing_item,
    _parse_add_modifier_to_item,
    _extract_menu_item_from_text,
    _parse_add_more_request,
)
from .tokenization import _parse_multi_item_order

logger = logging.getLogger(__name__)


# =============================================================================
# Order Type Detection (Pickup/Delivery)
# =============================================================================

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
        r"(?:i(?:'d| would) like to )?(?:place\s+)?(?:a\s+)?(?:pick[\s-]?up|delivery)\s+order",
        "", result, flags=re.IGNORECASE
    )
    result = re.sub(r"(?:for|is\s+for)\s+(?:pick[\s-]?up|delivery)", "", result, flags=re.IGNORECASE)
    result = re.sub(r"i(?:'ll|\s+will)\s+pick\s+(?:it\s+)?up", "", result, flags=re.IGNORECASE)
    result = re.sub(r"to\s+be\s+deliver(?:y|ed)", "", result, flags=re.IGNORECASE)
    result = re.sub(r"can\s+you\s+deliver", "", result, flags=re.IGNORECASE)
    result = re.sub(r"(?:^|\s)(?:pick[\s-]?up|delivery)(?:\s+please)?(?:$|\s)", " ", result, flags=re.IGNORECASE)
    return result.strip()


def _is_only_filler(text: str) -> bool:
    """Check if text contains only filler words after stripping order type.

    Args:
        text: Text to check

    Returns:
        True if text is empty or only contains filler words
    """
    # Remove common filler words and check if anything meaningful remains
    filler_words = {
        "and", "also", "i", "want", "would", "like", "to", "a", "an", "the", "please",
        "this", "is", "it", "that", "for", "can", "you", "be",
    }
    words = text.lower().split()
    meaningful_words = [w for w in words if w not in filler_words]
    return len(meaningful_words) == 0


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


# =============================================================================
# Main Deterministic Parser
# =============================================================================

def parse_open_input_deterministic(
    user_input: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Spread options are loaded from the database cache (GlobalAttributeOption for "spread").

    Args:
        user_input: The user's input string
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
        ingredient_to_items: Mapping of ingredient names to menu items containing them
            (e.g., {"chicken": [{"name": "Chicken Salad Sandwich", ...}]})

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.
    """
    text = user_input.strip()

    # Expand abbreviations before any parsing (e.g., "cc" -> "cream cheese")
    # This must happen first so downstream parsers see canonical forms
    text = menu_cache.expand_abbreviations(text)

    # Check for greetings (patterns loaded from database)
    if menu_cache.is_greeting(text):
        logger.debug("Deterministic parse: greeting detected")
        return OpenInputResponse(is_greeting=True)

    # Check for gratitude ("thank you", "thanks", etc.)
    if GRATITUDE_PATTERNS.match(text):
        logger.debug("Deterministic parse: gratitude detected")
        return OpenInputResponse(is_gratitude=True)

    # Check for help requests ("help", "I'm confused", "what can you do")
    if HELP_PATTERNS.match(text):
        logger.debug("Deterministic parse: help request detected")
        return OpenInputResponse(is_help_request=True)

    # Check for done ordering (patterns loaded from database)
    if menu_cache.is_done(text):
        logger.debug("Deterministic parse: done ordering detected")
        return OpenInputResponse(done_ordering=True)

    # Check for repeat order
    if REPEAT_ORDER_PATTERNS.match(text):
        logger.debug("Deterministic parse: repeat order detected")
        return OpenInputResponse(wants_repeat_order=True)

    # Strip conversational fillers (after greeting/done checks, before order parsing)
    # e.g., "actually, make it two" -> "make it two"
    text = strip_conversational_fillers(text)

    # Check for order type mentions (pickup/delivery)
    order_type = _extract_order_type(text)
    if order_type:
        logger.debug("Deterministic parse: order type '%s' detected", order_type)
        # Strip order type phrase from text to continue parsing any items
        text_for_items = _strip_order_type_phrase(text)

        # If nothing meaningful left, return just order type
        if not text_for_items.strip() or _is_only_filler(text_for_items):
            return OpenInputResponse(order_type=order_type)

        # Continue parsing with cleaned text, will add order_type at the end
        text = text_for_items

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

    # Check for specials/signature menu inquiries BEFORE dietary inquiry
    # "do you have any specials today?" was incorrectly matched by availability patterns
    # because it ends with "today", so we need to check for specials first
    signature_result = parse_signature_menu_inquiry(text)
    if signature_result:
        return signature_result

    # Check for dietary/allergen/availability/customization inquiries
    # Must run BEFORE parse_menu_query since "do you have vegan sandwiches?" is a
    # dietary+category query that should be handled specially, not as a generic menu query
    dietary_result = parse_dietary_inquiry(text)
    if dietary_result:
        return dietary_result

    # Check for menu category queries ("what sweets do you have?", "what desserts do you have?")
    menu_query_result = parse_menu_query(text)
    if menu_query_result:
        return menu_query_result

    # Check for recommendation questions
    recommendation_result = parse_recommendation_inquiry(text)
    if recommendation_result:
        return recommendation_result

    # Check for store info inquiries
    store_info_result = parse_store_info_inquiry(text)
    if store_info_result:
        return store_info_result

    # Check for item description inquiries
    item_desc_result = parse_item_description_inquiry(text)
    if item_desc_result:
        return item_desc_result

    # Check for modifier/add-on inquiries
    modifier_inquiry_result = parse_modifier_inquiry(text, modifier_category_keywords, modifier_item_keywords)
    if modifier_inquiry_result:
        return modifier_inquiry_result

    # Check for ingredient-based menu search
    # When user says "chicken" or "something with bacon", show matching items
    ingredient_search_result = parse_ingredient_search(text, ingredient_to_items)
    if ingredient_search_result:
        return ingredient_search_result

    # Check for by-the-pound orders EARLY
    # Must be checked BEFORE spread/salad sandwich matching to prevent
    # "half a pound of whitefish salad" from matching "Whitefish Salad Sandwich"
    by_pound_result = _parse_by_pound_order(text)
    if by_pound_result:
        return by_pound_result

    # Check for "make it 2" patterns BEFORE replacement (since "make it X" could match both)
    make_it_n_match = MAKE_IT_N_PATTERN.match(text)
    if make_it_n_match:
        # Find which group matched
        num_str = None
        for i in range(1, 9):
            if make_it_n_match.group(i):
                num_str = make_it_n_match.group(i).lower()
                break
        if num_str:
            # Convert to number
            word_to_num = {
                "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
            }
            if num_str.isdigit():
                target_qty = int(num_str)
            else:
                target_qty = word_to_num.get(num_str, 0)

            if target_qty >= 2:
                # User says "make it 2" means they want 2 total, so add (target - 1) more
                additional = target_qty - 1
                logger.info("Deterministic parse: 'make it N' detected, target=%d, adding %d more", target_qty, additional)
                return OpenInputResponse(duplicate_last_item=additional)

    # Check for "just one" / "only one" patterns - reduces quantity to 1
    # e.g., "actually just one bagel", "only one", "just one"
    reduce_to_one_match = REDUCE_TO_ONE_PATTERN.match(text)
    if reduce_to_one_match:
        # Extract item type if specified (any of the capture groups)
        item_type = None
        all_item_type_slugs = menu_cache.get_configurable_item_types()
        for i in range(1, 6):  # Check all capture groups
            if reduce_to_one_match.group(i):
                item_type = reduce_to_one_match.group(i).lower()
                # Normalize plurals using data-driven approach:
                # Check if the word matches an item type, if not try singular form
                if item_type not in all_item_type_slugs:
                    singular = singularize(item_type)
                    if singular in all_item_type_slugs:
                        item_type = singular
                break

        # Return special cancel_item value to signal quantity reduction
        if item_type:
            cancel_value = f"__reduce_to_one_{item_type}__"
        else:
            cancel_value = "__reduce_to_one__"

        logger.info("Deterministic parse: 'just/only one' detected, reducing to 1 (item_type=%s)", item_type or "any")
        return OpenInputResponse(cancel_item=cancel_value)

    # Check for "another" patterns (with item type specified)
    # This must be checked BEFORE ONE_MORE_PATTERN since it's more specific
    # Uses data-driven validation against menu_cache triggers
    another_item_match = ANOTHER_ITEM_PATTERN.match(text)
    if another_item_match:
        item_keyword = another_item_match.group(1).lower()
        # Get singular form for matching
        item_keyword_singular = singularize(item_keyword)

        # Validate against data-driven category keywords or item type triggers
        # This replaces the hardcoded ANOTHER_ITEM_TYPE_KEYWORDS mapping
        resolved_item_type: str | None = None

        # 1. Check category keyword mapping - returns the item type slug
        category_info = menu_cache.get_category_keyword_mapping(item_keyword)
        if not category_info:
            category_info = menu_cache.get_category_keyword_mapping(item_keyword_singular)
        if category_info:
            resolved_item_type = category_info.get("slug")

        # 2. Check if keyword is a trigger for any item type (reverse lookup)
        if not resolved_item_type:
            all_triggers = menu_cache.get_item_type_triggers()  # Returns dict[str, set[str]]
            for item_type_slug, triggers in all_triggers.items():
                if item_keyword in triggers or item_keyword_singular in triggers:
                    resolved_item_type = item_type_slug
                    break

        # 3. Fallback: Try word-boundary matching to find items containing the keyword
        # This handles cases like "tea" matching "Hot Tea", "Iced Tea", etc.
        if not resolved_item_type:
            word_matches = menu_cache.find_items_by_word_match(item_keyword)
            if not word_matches:
                word_matches = menu_cache.find_items_by_word_match(item_keyword_singular)
            if word_matches:
                # Find the most common item type among matches
                item_types = [m.get("item_type") for m in word_matches if m.get("item_type")]
                if item_types:
                    # Use the most frequent item type
                    from collections import Counter
                    resolved_item_type = Counter(item_types).most_common(1)[0][0]
                    logger.debug(
                        "Deterministic parse: 'another %s' word-matches %d items, item_type '%s'",
                        item_keyword, len(word_matches), resolved_item_type
                    )

        if resolved_item_type:
            # Valid item type keyword - pass the canonical item type to downstream handler
            logger.info("Deterministic parse: 'another %s' detected -> item_type '%s'", item_keyword, resolved_item_type)
            return OpenInputResponse(duplicate_new_item_type=resolved_item_type)

    # Check for "one more" / "another" patterns (without item type - needs clarification if multiple items)
    if ONE_MORE_PATTERN.match(text):
        logger.info("Deterministic parse: 'one more' / 'another' detected, adding 1 more")
        return OpenInputResponse(duplicate_last_item=1)

    # Check for modification to existing item BEFORE replacement patterns
    # This catches patterns like "make the bagel with scallion cream cheese"
    # which should modify an existing bagel, not trigger replace_last_item
    modify_existing_result = _parse_modify_existing_item(text)
    if modify_existing_result:
        return modify_existing_result

    # Check for replacement phrases
    replace_match = REPLACE_ITEM_PATTERN.match(text)
    if replace_match:
        replacement_item = None
        for i in range(1, 11):  # 10 capture groups in REPLACE_ITEM_PATTERN
            if replace_match.group(i):
                replacement_item = replace_match.group(i)
                break
        if replacement_item:
            replacement_item = replacement_item.strip()
            replacement_item = re.sub(r"^(?:a|an)\s+", "", replacement_item, flags=re.IGNORECASE)
            logger.info("Deterministic parse: replacement detected, item='%s'", replacement_item)

            parsed_replacement = parse_open_input_deterministic(replacement_item)
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    # Check for cancellation phrases
    cancel_match = CANCEL_ITEM_PATTERN.match(text)
    if cancel_match:
        cancel_item = None
        for i in range(1, 11):  # 10 capture groups in pattern
            if cancel_match.group(i):
                cancel_item = cancel_match.group(i)
                break
        if cancel_item:
            cancel_item = cancel_item.strip()
            # Handle "all" / "everything" to clear entire order
            all_items_phrases = {
                "all", "everything", "all of it", "the order", "my order",
                "the whole order", "my whole order", "all items", "all the items",
                "the whole thing", "it all", "them all",
                # Without "the" prefix (pattern strips "the")
                "order", "whole order", "whole thing"
            }
            if cancel_item.lower() in all_items_phrases:
                logger.info("Deterministic parse: cancel ALL items detected (phrase='%s')", cancel_item)
                return OpenInputResponse(cancel_item="__all_items__")
            # Handle pronouns that refer to the last item
            last_item_pronouns = {
                "that", "it", "this", "last", "the last one", "the last item", "last one", "last item",
                # "remove from the order" -> remove the last item mentioned
                "from the order", "from my order"
            }
            if cancel_item.lower() in last_item_pronouns:
                logger.info("Deterministic parse: cancellation of last item detected (pronoun='%s')", cancel_item)
                return OpenInputResponse(cancel_item="__last_item__")

            # Handle "last N" or "last N items" - remove the last N items from cart
            last_n_match = re.match(
                r"^last\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
                r"(?:\s+(?:items?|ones?))?$",
                cancel_item.lower()
            )
            if last_n_match:
                from ..quantity_utils import BASIC_WORD_TO_NUM
                num_str = last_n_match.group(1)
                if num_str.isdigit():
                    count = int(num_str)
                else:
                    count = BASIC_WORD_TO_NUM.get(num_str, 0)
                if count >= 1:
                    logger.info("Deterministic parse: remove last %d items detected", count)
                    return OpenInputResponse(cancel_item=f"__last_n_items_{count}__")

            # Handle "N" or "N more" or "N items" - remove N items from the end
            # e.g., "remove 2", "remove 2 more", "remove two items"
            just_n_match = re.match(
                r"^(\d+|two|three|four|five|six|seven|eight|nine|ten)"
                r"(?:\s+(?:more|items?|ones?))?$",
                cancel_item.lower()
            )
            if just_n_match:
                from ..quantity_utils import BASIC_WORD_TO_NUM
                num_str = just_n_match.group(1)
                if num_str.isdigit():
                    count = int(num_str)
                else:
                    count = BASIC_WORD_TO_NUM.get(num_str, 0)
                if count >= 1:
                    logger.info("Deterministic parse: remove %d items detected", count)
                    return OpenInputResponse(cancel_item=f"__last_n_items_{count}__")

            logger.info("Deterministic parse: cancellation detected, item='%s'", cancel_item)
            return OpenInputResponse(cancel_item=cancel_item)

    # Check for "add more" requests (add a third, add another, etc.)
    add_more_result = _parse_add_more_request(text)
    if add_more_result:
        return add_more_result

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
    # This matches direct menu items from the database (known_menu_items already excludes
    # configurable items, so no additional filtering needed)
    menu_item, qty = _extract_menu_item_from_text(text)
    if menu_item:
        # Get item_type for data-driven attribute and modification extraction
        item_type_for_mods = menu_cache.get_item_type_for_menu_item(menu_item)
        # Extract attributes using the item's actual item_type (fully data-driven)
        # Find the span where the menu item name appears in the text to exclude from
        # attribute matching. This prevents words within the menu item name (e.g., "butter"
        # in "Cinnamon Sugar Butter Sandwich") from matching as attributes.
        menu_item_span = None
        text_lower = text.lower()
        menu_item_lower = menu_item.lower()
        pos = text_lower.find(menu_item_lower)
        if pos != -1:
            menu_item_span = (pos, pos + len(menu_item_lower))
        attr_values = {}
        if item_type_for_mods:
            exclude_spans = [menu_item_span] if menu_item_span else None
            attr_values, _ = extract_attribute_values(text, item_type_for_mods, exclude_spans)
        modifications = _extract_menu_item_modifications(text, item_type_for_mods)
        # Look up is_signature from database (data-driven, no special handling)
        is_sig = menu_cache.item_has_default_ingredients(menu_item)
        logger.info("DETERMINISTIC MENU ITEM: matched '%s' -> %s (qty=%d, attrs=%s, mods=%s, is_signature=%s)", text[:50], menu_item, qty, list(attr_values.keys()), modifications, is_sig)
        # Convert structured modifications to Selection objects
        mod_list = []
        for add in modifications.get("additions", []):
            mod_list.append(Selection(slug=add["slug"], category=add.get("category")))
        for rem in modifications.get("removals", []):
            mod_list.append(Selection(slug=f"no_{rem['slug']}", category=rem.get("category")))
        menu_item_parsed_items = [
            build_parsed_item(
                item_type=item_type_for_mods or "menu_item",
                item_name=menu_item,
                quantity=1,
                attribute_values=attr_values,
                modifiers=mod_list,
                is_signature=is_sig,
            )
            for _ in range(qty)
        ]
        return _add_order_type_to_response(
            OpenInputResponse(parsed_items=menu_item_parsed_items), order_type
        )

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

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
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
    text_lower = text.lower().strip()
    for prefix in ["i want ", "i'd like ", "i would like ", "give me ", "can i get ", "can i have "]:
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
