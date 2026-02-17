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
    match_small_talk,
    CANCEL_LAST_ITEM,
    CANCEL_ALL_ITEMS,
    REDUCE_TO_ONE,
    make_last_n_sentinel,
    make_reduce_to_one_sentinel,
)
from ..intent_patterns import (
    strip_conversational_fillers,
    MAKE_IT_N_PATTERN,
    REDUCE_TO_ONE_PATTERN,
    ONE_MORE_PATTERN,
    ANOTHER_ITEM_PATTERN,
    REPLACE_ITEM_PATTERN,
    CANCEL_ITEM_PATTERN,
    MORE_OF_SAME_PATTERN,
    MAKE_IT_N_WITH_ITEM_PATTERN,
)
from .pipeline import get_pipeline
from .result_types import ParserContext, TextSpan
from ..quantity_utils import extract_make_it_n_target, parse_make_it_n_quantity
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

# Get shared pipeline instance for extraction operations
_pipeline = get_pipeline()


def _filter_duplicate_modifications(
    additions: list[dict[str, str]],
    attr_result: "AttributeExtractionResult",
    item_type: str | None,
) -> list[dict[str, str]]:
    """Remove modifier additions that duplicate already-extracted attribute options.

    When both attribute extraction and modification extraction match the same
    ingredient (e.g., "jalapeño cream" matches both as a spread attribute option
    and as an ingredient modifier), remove the modifier to avoid duplicates.

    Resolves modifier slugs to canonical ingredient slugs via ingredient details
    and checks against the set of attribute option slugs already extracted.
    """
    if not item_type or not additions:
        return additions

    # Collect canonical slugs of attribute options that were extracted
    extracted_option_slugs: set[str] = set()
    for value in attr_result.values.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    slug = item.get("slug", "")
                    if slug:
                        extracted_option_slugs.add(slug.lower())
        elif isinstance(value, str):
            extracted_option_slugs.add(value.lower())

    if not extracted_option_slugs:
        return additions

    # Build pattern -> ingredient slug mapping to resolve modifier aliases
    pattern_to_slug: dict[str, str] = {}
    ingredients_by_cat = menu_cache.get_ingredients_by_category_for_item_type(item_type)
    for cat in ingredients_by_cat:
        for detail in menu_cache.get_ingredient_details(cat):
            detail_slug = detail.get("slug", "").lower()
            for pattern in detail.get("patterns", []):
                pattern_to_slug[pattern.lower()] = detail_slug

    filtered = []
    for add in additions:
        mod_slug = add.get("slug", "").lower()
        # Resolve to canonical ingredient slug
        canonical_slug = pattern_to_slug.get(mod_slug, mod_slug)
        if canonical_slug in extracted_option_slugs:
            logger.debug(
                "Filtered duplicate modification '%s' (canonical: %s) - already an attribute option",
                mod_slug, canonical_slug,
            )
            continue
        filtered.append(add)

    return filtered


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
# Sub-functions for parse_open_input_deterministic
# =============================================================================


def _try_parse_greeting_or_meta(text: str) -> OpenInputResponse | None:
    """Check for greetings, gratitude, help requests, done ordering, repeat order.

    Args:
        text: Cleaned user input text (after abbreviation expansion).

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
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
    # Must run BEFORE small talk so "I'm good" is treated as done ordering, not social chat
    if menu_cache.is_done(text):
        logger.debug("Deterministic parse: done ordering detected")
        return OpenInputResponse(done_ordering=True)

    # Check for small talk ("how are you?", "what's up?", etc.)
    small_talk_response = match_small_talk(text)
    if small_talk_response:
        logger.debug("Deterministic parse: small talk detected")
        return OpenInputResponse(is_small_talk=True, small_talk_response=small_talk_response)

    # Check for repeat order
    if REPEAT_ORDER_PATTERNS.match(text):
        logger.debug("Deterministic parse: repeat order detected")
        return OpenInputResponse(wants_repeat_order=True)

    return None


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


def _try_parse_quantity_change(text: str) -> OpenInputResponse | None:
    """Check for make-it-N and reduce-to-one patterns.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for "make it 2" patterns BEFORE replacement (since "make it X" could match both)
    make_it_n_match = MAKE_IT_N_PATTERN.match(text)
    if make_it_n_match:
        target_qty = extract_make_it_n_target(make_it_n_match)
        if target_qty is not None:
            # User says "make it 2" means they want 2 total, so add (target - 1) more
            additional = target_qty - 1
            logger.info(
                "Deterministic parse: 'make it N' detected, target=%d, adding %d more",
                target_qty, additional,
            )
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
            cancel_value = make_reduce_to_one_sentinel(item_type)
        else:
            cancel_value = REDUCE_TO_ONE

        logger.info(
            "Deterministic parse: 'just/only one' detected, reducing to 1 (item_type=%s)",
            item_type or "any",
        )
        return OpenInputResponse(cancel_item=cancel_value)

    return None


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
                from collections import Counter
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

    return None


def _try_parse_cancellation(text: str) -> OpenInputResponse | None:
    """Check for cancel all/last/N items and 'add more' patterns.

    Args:
        text: Cleaned user input text.

    Returns:
        OpenInputResponse if matched, None otherwise.
    """
    # Check for cancellation phrases
    cancel_match = CANCEL_ITEM_PATTERN.match(text)
    if cancel_match:
        cancel_item = None
        # Check all capture groups dynamically (pattern may have varying number of groups)
        for i in range(1, CANCEL_ITEM_PATTERN.groups + 1):
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
                "order", "whole order", "whole thing",
                # Cart-based phrases
                "cart", "the cart", "my cart",
            }
            if cancel_item.lower() in all_items_phrases:
                logger.info("Deterministic parse: cancel ALL items detected (phrase='%s')", cancel_item)
                return OpenInputResponse(cancel_item=CANCEL_ALL_ITEMS)
            # Handle pronouns that refer to the last item
            last_item_pronouns = {
                "that", "it", "this", "last", "the last one", "the last item", "last one", "last item",
                # "remove from the order" -> remove the last item mentioned
                "from the order", "from my order"
            }
            if cancel_item.lower() in last_item_pronouns:
                logger.info("Deterministic parse: cancellation of last item detected (pronoun='%s')", cancel_item)
                return OpenInputResponse(cancel_item=CANCEL_LAST_ITEM)

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
                    return OpenInputResponse(cancel_item=make_last_n_sentinel(count))

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
                    return OpenInputResponse(cancel_item=make_last_n_sentinel(count))

            logger.info("Deterministic parse: cancellation detected, item='%s'", cancel_item)
            return OpenInputResponse(cancel_item=cancel_item)

    # Check for "add more" requests (add a third, add another, etc.)
    add_more_result = _parse_add_more_request(text)
    if add_more_result:
        return add_more_result

    return None


def _try_parse_new_items(
    text: str,
    order_type: Literal["pickup", "delivery"] | None,
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
    # This matches direct menu items from the database (known_menu_items already excludes
    # configurable items, so no additional filtering needed)
    menu_item, qty, matched_alias = _extract_menu_item_from_text(text)
    if menu_item:
        # Get item_type for data-driven attribute and modification extraction
        item_type_for_mods = menu_cache.get_item_type_for_menu_item(menu_item)
        # Extract attributes using the item's actual item_type (fully data-driven)
        # Find the span where the menu item name appears in the text to exclude from
        # attribute matching. This prevents words within the menu item name (e.g., "butter"
        # in "Cinnamon Sugar Butter Sandwich") from matching as attributes.
        # Use the matched_alias (the text that actually matched) instead of the canonical
        # name, since the user may have typed an alias like "cinnamon butter sandwich"
        # instead of "Cinnamon Sugar Butter Sandwich".
        menu_item_span = None
        text_lower = text.lower()
        # Try the matched alias first, then fall back to canonical name
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
            attr_result = _pipeline.extract_attributes(text, item_type_for_mods, exclude_spans)
        modifications = _extract_menu_item_modifications(text, item_type_for_mods)
        # Deduplicate: remove modifications whose ingredient is already matched
        # as an attribute option (e.g., "jalapeño cream" modifier when attribute
        # extraction already matched it as spread → jalapeno_cc)
        if attr_result and modifications.get("additions"):
            modifications["additions"] = _filter_duplicate_modifications(
                modifications["additions"], attr_result, item_type_for_mods
            )
        attr_keys = list(attr_result.values.keys()) if attr_result else []
        logger.info("DETERMINISTIC MENU ITEM: matched '%s' -> %s (qty=%d, attrs=%s, mods=%s)", text[:50], menu_item, qty, attr_keys, modifications)
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
                original_text=text,
                attr_result=attr_result,
                modifiers=mod_list,
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

    return None


# =============================================================================
# Main Deterministic Parser
# =============================================================================

def _strip_noise_phrases(text: str) -> str:
    """Strip container words, indifference phrases, and conditional phrases.

    Removes patterns like:
    - "a bottle of orange juice" -> "orange juice"
    - "coffee or whatever" -> "coffee"
    - "bagel if you have it" -> "bagel"
    """
    # Strip container/packaging words that don't affect item identification
    # e.g., "a bottle of orange juice" -> "a  orange juice" -> parsers match "orange juice"
    # Only strips "container of" patterns (requires "of" to avoid false positives)
    text = re.sub(
        r'\b(?:bottles?|glasses?|cups?|cans?|boxes?|cartons?|bags?|packs?|jars?|jugs?)\s+of\s+',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Strip trailing indifference/flexibility phrases that don't affect item identification
    # e.g., "orange juice or whatever they have" -> "orange juice"
    # e.g., "a coffee or something" -> "a coffee"
    text = re.sub(
        r'\s+or\s+(?:whatever(?:\s+(?:you|they|you guys)\s+(?:have|got|recommend))?'
        r'|something(?:\s+like\s+that)?'
        r'|anything(?:\s+(?:like\s+that|similar|really|works?))?'
        r')\s*$',
        '', text, flags=re.IGNORECASE
    ).strip()

    # Also strip "if you have it/that", "if that's available", "if possible", etc.
    text = re.sub(
        r'\s+if\s+(?:you\s+have\s+(?:it|that|any|some)'
        r'|that(?:\'s|\s+is)\s+(?:available|okay|ok|fine|possible)'
        r'|possible'
        r')\s*$',
        '', text, flags=re.IGNORECASE
    ).strip()

    return text


def parse_open_input_deterministic(
    user_input: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
    ctx: ParserContext | None = None,
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
    # Build ParserContext from legacy kwargs if not provided
    if ctx is None:
        ctx = ParserContext(
            modifier_category_keywords=modifier_category_keywords,
            modifier_item_keywords=modifier_item_keywords,
            ingredient_to_items=ingredient_to_items,
        )

    text = user_input.strip()

    # Expand abbreviations before any parsing (e.g., "cc" -> "cream cheese")
    # This must happen first so downstream parsers see canonical forms
    text = menu_cache.expand_abbreviations(text)

    # Check for greetings, gratitude, help, done ordering, repeat order
    greeting_or_meta = _try_parse_greeting_or_meta(text)
    if greeting_or_meta:
        return greeting_or_meta

    # Strip conversational fillers (after greeting/done checks, before order parsing)
    # e.g., "actually, make it two" -> "make it two"
    text = strip_conversational_fillers(text)

    # Strip container words, indifference phrases, and conditional phrases
    text = _strip_noise_phrases(text)

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

    # Check for all inquiry types (price, dietary, menu, store, modifier, etc.)
    inquiry_result = _try_parse_inquiry(text, ctx)
    if inquiry_result:
        return inquiry_result

    # Check for make-it-N, reduce-to-one quantity changes
    quantity_result = _try_parse_quantity_change(text)
    if quantity_result:
        return quantity_result

    # Check for "another" patterns, "one more", "make it N [item]"
    another_result = _try_parse_another_item(text)
    if another_result:
        return another_result

    # Check for modify-existing-item and replacement phrases
    modification_result = _try_parse_modification(text)
    if modification_result:
        return modification_result

    # Check for cancellation and "add more" patterns
    cancellation_result = _try_parse_cancellation(text)
    if cancellation_result:
        return cancellation_result

    # Strip ordering prefixes ("just", "some") before new-item parsing.
    # These are in ORDERING_PREFIXES but not HESITATION_FILLERS. Must happen AFTER
    # quantity change checks (e.g., "just one bagel" = reduce-to-one needs "just")
    # but BEFORE item parsing (e.g., "just a 6 Bagel Package" needs "just a" stripped).
    # Also strip the trailing article (a/an/the) so "just a bagel" -> "bagel".
    text = re.sub(r'^(?:just|some)\b[,\s]*(?:(?:a|an|the)\b\s*)?', '', text, flags=re.IGNORECASE).strip()

    # Check for new item orders (split-qty, multi-item, configurable, direct, simple)
    new_items_result = _try_parse_new_items(text, order_type)
    if new_items_result:
        return new_items_result

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


# =============================================================================
# Inline Attribute Spec Pattern Detection
# =============================================================================

def _is_inline_attribute_spec_pattern(text: str) -> bool:
    """Check if text is an inline attribute specification pattern.

    Inline spec pattern: "N items N attr1 N attr2" where:
    - "N items" identifies the item type (e.g., "2 bagels")
    - "N attr1 N attr2" are quantity+attribute pairs (e.g., "1 everything 1 plain")

    This differs from multi-item orders like "2 bagels 2 coffees" where
    each quantity is followed by a different item type.

    Args:
        text: Lowercase user input

    Returns:
        True if this is an inline spec pattern that should NOT be split
        by comma insertion.
    """
    from .item_parsing import _detect_configurable_item_type

    # Pattern: qty word qty word qty word...
    # e.g., "2 bagels 1 everything 1 plain"
    qty_word_pattern = r'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(\w+)'
    raw_matches = list(re.finditer(qty_word_pattern, text, re.IGNORECASE))

    if len(raw_matches) < 2:
        return False  # Not enough qty+word pairs

    matches = [(m.group(1), m.group(2)) for m in raw_matches]

    # First match should identify the item type
    first_word = matches[0][1].lower()

    # Detect item type from the first qty+word pair
    first_phrase = f"{matches[0][0]} {first_word}"
    detected_type, _ = _detect_configurable_item_type(first_phrase)

    if not detected_type:
        return False  # Couldn't identify item type

    # Get attribute options for this item type
    attrs = menu_cache.get_item_type_attributes(detected_type)
    if not attrs:
        return False

    # Build set of all attribute option words (slugs, display names, aliases)
    # Also extract individual words from multi-word options for partial matching
    # e.g., "everything_bagel" -> add "everything" as well
    attr_option_words: set[str] = set()
    for attr_slug, attr_info in attrs.items():
        options = attr_info.get("options", [])
        for opt in options:
            if isinstance(opt, dict):
                slug = opt.get("slug", "")
                display_name = opt.get("display_name", "")
                aliases = opt.get("aliases", [])

                # Add full names
                if slug:
                    attr_option_words.add(slug.lower())
                    # Also add parts split by underscore (e.g., "everything" from "everything_bagel")
                    for part in slug.lower().split("_"):
                        if len(part) >= 3:  # Skip very short parts
                            attr_option_words.add(part)
                if display_name:
                    attr_option_words.add(display_name.lower())
                    # Also add parts split by space
                    for part in display_name.lower().split():
                        if len(part) >= 3:
                            attr_option_words.add(part)
                for alias in aliases:
                    attr_option_words.add(alias.lower())
                    for part in alias.lower().split():
                        if len(part) >= 3:
                            attr_option_words.add(part)

    # If item type triggers appear between qty+word pairs, this is multi-item, not inline spec
    all_trigger_flat = menu_cache.get_all_triggers_flat()

    for i in range(len(raw_matches) - 1):
        gap_text = text[raw_matches[i].end():raw_matches[i + 1].start()].strip()
        if gap_text:
            for word in gap_text.lower().split():
                if word in all_trigger_flat or singularize(word) in all_trigger_flat:
                    return False

    # Check if subsequent qty+word pairs have words that are attribute options
    subsequent_words = [m[1].lower() for m in matches[1:]]
    attr_matches = [w for w in subsequent_words if w in attr_option_words]

    # If ALL subsequent words are attribute options, this is an inline spec pattern
    if len(attr_matches) == len(subsequent_words):
        logger.debug(
            "Inline spec detected: type=%s, specs=%s",
            detected_type, subsequent_words
        )
        return True

    return False


# =============================================================================
# Main Parse Open Input Function
# =============================================================================

def parse_open_input(
    user_input: str,
    context: str = "",
    model: str = "gpt-4o-mini",
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
    ctx: ParserContext | None = None,
) -> OpenInputResponse:
    """Parse user input when open for new orders.

    Uses deterministic parsing only - no LLM fallback.
    All parsing is data-driven via database-loaded patterns.

    Args:
        user_input: The user's input string
        context: Unused (kept for API compatibility)
        model: Unused (kept for API compatibility)
        modifier_category_keywords: Mapping of keywords to category slugs
        modifier_item_keywords: Mapping of item keywords to item type slugs
        ingredient_to_items: Mapping of ingredient names to menu items containing them
        ctx: ParserContext bundling the keyword arguments above
    """
    # Build ParserContext from legacy kwargs if not provided
    if ctx is None:
        ctx = ParserContext(
            modifier_category_keywords=modifier_category_keywords,
            modifier_item_keywords=modifier_item_keywords,
            ingredient_to_items=ingredient_to_items,
        )
    # Strip greetings/fillers early so ALL paths get clean text
    user_input = strip_conversational_fillers(user_input.strip())

    # Check for "make it N [item]" quantity pattern BEFORE replacement patterns
    # e.g., "make it two bagels" should duplicate the configured bagel, not replace it
    make_n_item_match = MAKE_IT_N_WITH_ITEM_PATTERN.match(user_input)
    if make_n_item_match:
        num_str = make_n_item_match.group(1).lower()
        target_qty = parse_make_it_n_quantity(num_str)
        if target_qty is not None:
            item_ref = make_n_item_match.group(2).strip()
            additional = target_qty - 1
            logger.info(
                "Quantity-with-item detected early, target=%d, item_ref='%s', adding %d more",
                target_qty, item_ref, additional,
            )
            return OpenInputResponse(
                duplicate_last_item=additional,
                duplicate_by_reference=item_ref,
            )

    # Check for replacement patterns FIRST, before configurable item parsing
    # This ensures "No, I said plain bagel" triggers replacement, not a new item
    replace_match = REPLACE_ITEM_PATTERN.match(user_input)
    if replace_match:
        replacement_item = None
        for i in range(1, 11):  # 10 capture groups in REPLACE_ITEM_PATTERN
            if replace_match.group(i):
                replacement_item = replace_match.group(i)
                break
        if replacement_item:
            replacement_item = replacement_item.strip()
            replacement_item = re.sub(r"^(?:a|an)\s+", "", replacement_item, flags=re.IGNORECASE)
            logger.info("Replacement pattern detected early, item='%s'", replacement_item)

            # Parse the replacement item
            parsed_replacement = parse_open_input_deterministic(
                replacement_item,
                ctx=ctx,
            )
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    # Check if input likely contains multiple items
    input_lower = user_input.lower()
    # Clean up compound phrases that contain "and" but aren't multi-item orders
    # These are loaded from database (menu item names/aliases with "and")
    # Order matters: longer phrases first to match properly
    cleaned = input_lower
    compound_phrases = menu_cache.get_compound_phrases()
    for phrase in sorted(compound_phrases, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, "")

    # Check for repeated quantity patterns (e.g., "2 plain bagels 2 everything bagels")
    # This handles space-separated items without "and" or commas
    quantity_pattern = re.compile(
        r'(?:^|\s)(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+\w+',
        re.IGNORECASE
    )
    quantity_matches = quantity_pattern.findall(cleaned)
    has_repeated_quantities = len(quantity_matches) >= 2

    # If "and" or comma still appears, it might be multi-item OR a single item with modifiers
    # Also try multi-item parsing if we detect repeated quantity patterns
    # Try multi-item parsing first - the multi-item parser has built-in logic to detect
    # modifier chains ("bagel with butter and cream cheese") and will return None for those.
    if " and " in cleaned or ", " in cleaned or has_repeated_quantities:
        logger.info("Potential multi-item detected, trying multi-item parse: %s", user_input[:50])

        # If we detected repeated quantities without commas, normalize by inserting commas
        # e.g., "2 plain bagels 2 everything bagels" -> "2 plain bagels, 2 everything bagels"
        # BUT: skip if this looks like an inline attribute spec pattern
        # e.g., "2 bagels 1 everything 1 plain" should NOT be split - it's 2 bagels with inline specs
        parse_input = user_input
        if has_repeated_quantities and ", " not in input_lower and " and " not in cleaned:
            # Check if this is an inline attribute spec pattern before inserting commas
            if not _is_inline_attribute_spec_pattern(input_lower):
                # Build trigger set from cache for boundary detection
                all_trigger_flat = menu_cache.get_all_triggers_flat()

                qty_words = r'\d+|one|two|three|four|five|six|seven|eight|nine|ten'

                def _comma_if_trigger(m: re.Match) -> str:
                    word = m.group(1).lower()
                    if word in all_trigger_flat or singularize(word) in all_trigger_flat:
                        return f"{m.group(1)}, {m.group(2)}"
                    return m.group(0)

                parse_input = re.sub(
                    rf'(\w+)\s+({qty_words})(?=\s+\w)',
                    _comma_if_trigger,
                    user_input,
                    flags=re.IGNORECASE,
                )
                if parse_input != user_input:
                    logger.info("Normalized repeated quantities: %s", parse_input[:60])
            else:
                logger.info("Detected inline attribute spec pattern, skipping comma: %s", input_lower[:60])

        # Try split-quantity FIRST (e.g., "two bagels one with lox one with cream cheese")
        # Mirrors priority in _try_parse_new_items() (lines 722-734).
        split_qty_result = _parse_split_quantity_items(parse_input)
        if split_qty_result is not None:
            logger.info("Parsed split-quantity order: %s", user_input[:50])
            return split_qty_result

        result = _parse_multi_item_order(parse_input)
        if result is not None:
            logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
            return result
        # Fall through to configurable item if multi-item parse fails
        logger.info("Multi-item parse failed, trying configurable item: %s", user_input[:50])

        # Try configurable item patterns (bagels, coffees, etc.)
        # e.g., "plain bagel with Egg Whites, Swiss, and Spinach", "large iced latte"
        logger.info("Trying configurable item pattern: %s", user_input[:50])
        result = _parse_configurable_item(user_input)
        if result is not None:
            logger.info("Parsed configurable item: %s", user_input[:50])
            return result

    # Try deterministic parsing for single-item orders
    result = parse_open_input_deterministic(
        user_input,
        ctx=ctx,
    )
    if result is not None:
        logger.info("Parsed deterministically: %s", user_input[:50])
        return result

    # No LLM fallback - return unclear response
    logger.info("Unable to parse deterministically, returning unclear: %s", user_input[:50])
    return OpenInputResponse(unclear=True)
