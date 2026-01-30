"""
Inquiry Parsing Functions for Deterministic Parsing.

This module contains functions for parsing non-order queries including:
- Price inquiries
- Menu category queries
- Recommendation questions
- Store information inquiries (hours, location, delivery zone)
- Item description inquiries
- Modifier/add-on inquiries
- Ingredient-based menu search
"""

import re
import logging

from orderbot.menu_data_cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse

from ..constants import (
    PRICE_INQUIRY_PATTERNS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    RECOMMENDATION_GENERAL_PATTERNS,
    RECOMMENDATION_TERM_PATTERNS,
    ITEM_DESCRIPTION_PATTERNS,
    MODIFIER_INQUIRY_PATTERNS,
    MORE_MENU_ITEMS_PATTERNS,
    clean_extracted_text,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level cache for order signals
# =============================================================================

_ORDER_SIGNALS_CACHE: list[str] | None = None


# =============================================================================
# Helper for required_match_phrases filtering
# =============================================================================

def _passes_required_match_filter(item: dict, user_input: str) -> bool:
    """Check if item passes required_match_phrases filter.

    If the item has required_match_phrases set, the user's input must contain
    at least ONE of the comma-separated phrases for the item to match.

    Args:
        item: Menu item dict (may have 'required_match_phrases' key)
        user_input: The user's search input

    Returns:
        True if the item passes the filter (or has no filter), False otherwise.

    Example:
        Item: "Bagel Chips - Salt" with required_match_phrases="bagel chips, chips"
        - user_input="bagel" -> False (doesn't contain "bagel chips" OR "chips")
        - user_input="bagel chips" -> True (contains "bagel chips")
    """
    required_phrases = item.get("required_match_phrases")

    # No filter set - item passes
    if not required_phrases:
        return True

    user_input_lower = user_input.lower()

    # Parse comma-separated phrases and check if user input contains at least one
    phrases = [p.strip().lower() for p in required_phrases.split(",") if p.strip()]
    return any(phrase in user_input_lower for phrase in phrases)


def _build_ingredient_search_response(
    ingredient: str,
    matches: list[dict],
    user_input: str,
    pattern_name: str,
) -> OpenInputResponse | None:
    """Build ingredient search response with required_match_phrases filtering.

    Args:
        ingredient: The ingredient that was matched
        matches: List of menu items containing the ingredient
        user_input: Original user input text (for filtering and logging)
        pattern_name: Name of pattern for logging (e.g., "standalone", "with_pattern")

    Returns:
        OpenInputResponse if matches exist after filtering, None otherwise.
    """
    filtered = [m for m in matches if _passes_required_match_filter(m, user_input)]
    if not filtered:
        return None

    logger.info(
        "INGREDIENT SEARCH (%s): '%s' -> found %d items with '%s'",
        pattern_name, user_input[:50], len(filtered), ingredient
    )
    return OpenInputResponse(
        ingredient_search_query=ingredient,
        ingredient_search_matches=filtered,
    )


# =============================================================================
# Price Inquiry Parsing
# =============================================================================

def _parse_price_inquiry_deterministic(text: str) -> OpenInputResponse | None:
    """Parse price inquiry questions."""
    text_lower = text.lower().strip()

    for pattern in PRICE_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = match.group(1).strip()
            item_text = clean_extracted_text(item_text)

            logger.debug("Price inquiry detected: item_text='%s'", item_text)

            # Look up category keyword in DB-loaded cache
            category_info = menu_cache.get_category_keyword_mapping(item_text)
            if category_info:
                menu_type = category_info["slug"]
                logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    asks_about_price=True,
                    menu_query=True,
                    menu_query_type=menu_type,
                )

            your_match = re.match(r"your\s+(.+)", item_text)
            if your_match:
                item_after_your = your_match.group(1).strip()
                category_info = menu_cache.get_category_keyword_mapping(item_after_your)
                if category_info:
                    menu_type = category_info["slug"]
                    logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", text[:50], menu_type)
                    return OpenInputResponse(
                        asks_about_price=True,
                        menu_query=True,
                        menu_query_type=menu_type,
                    )

            logger.info("PRICE INQUIRY (specific): '%s' -> price_query_item=%s", text[:50], item_text)
            return OpenInputResponse(
                asks_about_price=True,
                price_query_item=item_text,
            )

    return None


# =============================================================================
# Menu Query Parsing
# =============================================================================

def _parse_menu_query_deterministic(text: str) -> OpenInputResponse | None:
    """Parse 'what X do you have?' type menu queries."""
    text_lower = text.lower().strip()

    # Generic terms that should trigger a GENERAL menu listing (all categories)
    # These are not specific category queries - they're asking about the whole menu
    general_menu_terms = {
        "food", "foods", "stuff", "things", "items", "menu items",
        "menu", "options", "choices", "eats", "grub",
    }

    # Patterns for GENERAL menu inquiries (should list all categories)
    general_menu_patterns = [
        # "what's on your/the menu?" / "whats on your menu?" / "what is on your/the menu?"
        re.compile(r"what(?:'?s|\s+is)\s+on\s+(?:your|the)\s+menu", re.IGNORECASE),
        # "what do you have?" / "what do you have on the menu?"
        re.compile(r"what\s+do\s+you\s+have(?:\s+on\s+(?:the|your)\s+menu)?(?:\?|$)", re.IGNORECASE),
        # "what do you serve?" / "what do you sell?"
        re.compile(r"what\s+do\s+you\s+(?:serve|sell|offer|make)", re.IGNORECASE),
        # "what can I order?" / "what can I get?"
        re.compile(r"what\s+can\s+i\s+(?:order|get|have)", re.IGNORECASE),
        # "show me the menu" / "let me see the menu"
        re.compile(r"(?:show|let\s+me\s+see|can\s+i\s+see)\s+(?:me\s+)?(?:the|your)\s+menu", re.IGNORECASE),
        # "menu please" / "the menu"
        re.compile(r"^(?:the\s+)?menu(?:\s+please)?(?:\?|!|\.)?$", re.IGNORECASE),
    ]

    # Check for general menu inquiry patterns first
    for pattern in general_menu_patterns:
        if pattern.search(text_lower):
            logger.info("GENERAL MENU QUERY: '%s'", text[:50])
            return OpenInputResponse(
                menu_query=True,
                menu_query_type=None,  # None means list all categories
            )

    # Patterns for menu category queries
    # "what desserts do you have?", "what sweets do you have?", "what pastries do you have?"
    # "what kind of muffins do you have?"
    menu_query_patterns = [
        # "what kind of X do you have" - capture X
        re.compile(r"what\s+(?:kind|type|types|kinds)\s+of\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        # "what X do you have" - capture X
        re.compile(r"what\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|have\s+you)\s+got", re.IGNORECASE),
        re.compile(r"what\s+(?:are\s+)?(?:your|the)\s+(.+?)(?:\s+options)?(?:\?|$)", re.IGNORECASE),
        re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    ]

    for pattern in menu_query_patterns:
        match = pattern.search(text_lower)
        if match:
            category_text = match.group(1).strip()
            # Remove trailing punctuation
            category_text = clean_extracted_text(category_text)

            # Check if it's a generic term that should trigger general menu listing
            if category_text in general_menu_terms:
                logger.info("GENERAL MENU QUERY (generic term '%s'): '%s'", category_text, text[:50])
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=None,  # None means list all categories
                )

            # Check if it maps to a known category (DB lookup)
            category_info = menu_cache.get_category_keyword_mapping(category_text)
            if category_info:
                menu_type = category_info["slug"]
                logger.info("MENU QUERY: '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=menu_type,
                )

    return None


# =============================================================================
# Recommendation Inquiry Parsing
# =============================================================================

def _parse_recommendation_inquiry(text: str) -> OpenInputResponse | None:
    """Parse recommendation questions using data-driven two-tier lookup.

    1. Check general patterns (domain-agnostic) - return "general" match type
    2. Check term-extracting patterns - singularize term and do lookup:
       a. Search menu_items by partial name/alias match
       b. Fallback: Search item_types by display_name/aliases
    3. Return structured match result with menu_item_ids or item_type_slug
    """
    text_lower = text.lower().strip()

    # 1. Check general patterns first (domain-agnostic, no term extraction)
    for pattern in RECOMMENDATION_GENERAL_PATTERNS:
        if pattern.search(text_lower):
            logger.info("RECOMMENDATION INQUIRY (general): '%s'", text[:50])
            return OpenInputResponse(
                asks_recommendation=True,
                recommendation_match_type="general",
            )

    # 2. Check term-extracting patterns
    for pattern in RECOMMENDATION_TERM_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            # Extract and clean the captured term
            raw_term = match.group(1).strip()

            # Skip if term is too short or generic
            if len(raw_term) < 2 or raw_term in {"a", "an", "the", "some", "any"}:
                continue

            # Remove trailing punctuation and common words
            term = re.sub(r"[?!.,]+$", "", raw_term).strip()
            if not term:
                continue

            # Singularize the term
            term_singular = singularize(term)

            logger.info(
                "RECOMMENDATION INQUIRY (term): '%s' -> term='%s' (singular='%s')",
                text[:50], term, term_singular
            )

            # 3a. Search menu items first
            matching_items = menu_cache.search_menu_items_for_recommendation(term_singular)
            if matching_items:
                menu_item_ids = [item["id"] for item in matching_items]
                logger.info(
                    "RECOMMENDATION: Found %d menu items for '%s': %s",
                    len(menu_item_ids), term_singular, menu_item_ids[:5]
                )
                return OpenInputResponse(
                    asks_recommendation=True,
                    recommendation_match_type="menu_items",
                    recommendation_menu_item_ids=menu_item_ids,
                    recommendation_search_term=term_singular,
                )

            # 3b. Fallback: Search item types
            item_type_slug = menu_cache.search_item_type_for_recommendation(term_singular)
            if item_type_slug:
                logger.info(
                    "RECOMMENDATION: Found item type '%s' for '%s'",
                    item_type_slug, term_singular
                )
                return OpenInputResponse(
                    asks_recommendation=True,
                    recommendation_match_type="item_type",
                    recommendation_item_type_slug=item_type_slug,
                    recommendation_search_term=term_singular,
                )

            # No matches found, but it's still a recommendation question - return general
            logger.info(
                "RECOMMENDATION: No matches for '%s', returning general",
                term_singular
            )
            return OpenInputResponse(
                asks_recommendation=True,
                recommendation_match_type="general",
            )

    return None


# =============================================================================
# Store Info Inquiry Parsing
# =============================================================================

def _parse_store_info_inquiry(text: str) -> OpenInputResponse | None:
    """Parse store info inquiries."""
    text_lower = text.lower().strip()

    for pattern in STORE_HOURS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (hours): '%s'", text[:50])
            return OpenInputResponse(asks_store_hours=True)

    for pattern in STORE_LOCATION_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (location): '%s'", text[:50])
            return OpenInputResponse(asks_store_location=True)

    for pattern in DELIVERY_ZONE_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            location_query = match.group(1).strip()
            location_query = clean_extracted_text(location_query)
            logger.info("STORE INFO INQUIRY (delivery zone): '%s' -> '%s'", text[:50], location_query)
            return OpenInputResponse(
                asks_delivery_zone=True,
                delivery_zone_query=location_query,
            )

    return None


# =============================================================================
# Item Description Inquiry Parsing
# =============================================================================

def _parse_item_description_inquiry(text: str) -> OpenInputResponse | None:
    """Parse item description questions."""
    text_lower = text.lower().strip()

    if any(word in text_lower for word in ["my cart", "my order", "the cart", "the order"]):
        return None

    for pattern in ITEM_DESCRIPTION_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_name = match.group(1).strip()
            item_name = clean_extracted_text(item_name)
            item_name = re.sub(r'\s+sandwich$', '', item_name).strip()
            if item_name:
                logger.info("ITEM DESCRIPTION INQUIRY: '%s' -> item='%s'", text[:50], item_name)
                return OpenInputResponse(
                    asks_item_description=True,
                    item_description_query=item_name,
                )

    return None


# =============================================================================
# Modifier Inquiry Parsing
# =============================================================================

def _parse_modifier_inquiry(
    text: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
) -> OpenInputResponse | None:
    """Parse modifier/add-on inquiry questions.

    Args:
        text: User input text to parse
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
            If None, modifier category detection is skipped but item detection still works.
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
            If None, item detection is skipped.
    """
    text_lower = text.lower().strip()
    keywords = modifier_category_keywords or {}
    item_keywords = modifier_item_keywords or {}

    for pattern, item_group, category_group in MODIFIER_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = None
            category_text = None

            # Extract item from match if present
            if item_group > 0:
                try:
                    item_text = match.group(item_group).strip()
                    item_text = clean_extracted_text(item_text)
                except (IndexError, AttributeError):
                    pass

            # Extract category from match if present
            if category_group > 0:
                try:
                    category_text = match.group(category_group).strip()
                    category_text = clean_extracted_text(category_text)
                except (IndexError, AttributeError):
                    pass

            # Normalize item type
            item_type = None
            if item_text:
                item_type = item_keywords.get(item_text.lower())
                # If item_text doesn't match known items, it might be a category
                if not item_type and item_text.lower() in keywords:
                    category_text = item_text
                    item_text = None

            # Normalize category
            category = None
            if category_text:
                category = keywords.get(category_text.lower())

            # Only return if we have a valid item or category
            if item_type or category:
                logger.info(
                    "MODIFIER INQUIRY: '%s' -> item=%s, category=%s",
                    text[:50], item_type, category
                )
                return OpenInputResponse(
                    asks_modifier_options=True,
                    modifier_query_item=item_type,
                    modifier_query_category=category,
                )

    return None


# =============================================================================
# More Menu Items Parsing (Pagination)
# =============================================================================

def _parse_more_menu_items(text: str) -> OpenInputResponse | None:
    """Parse 'show more' menu requests like 'what other drinks do you have?'

    Also extracts the category from "what other X" patterns so the handler can
    start a fresh query if no pagination context exists.
    """
    text_lower = text.lower().strip()

    for pattern in MORE_MENU_ITEMS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("MORE MENU ITEMS: '%s'", text[:50])

            # Try to extract the category from "what other X" patterns
            # e.g., "what other signature sandwiches do you have?" -> "signature sandwiches"
            category_match = re.search(
                r'what (?:other|else|more) ([a-z]+(?: [a-z]+)*?)(?:\s+(?:do you have|are there|can i get|you got)|\?|$)',
                text_lower
            )
            category = None
            if category_match:
                category = category_match.group(1).strip()
                # Clean up common suffixes
                if category.endswith(' options'):
                    category = category[:-8].strip()
                if category:
                    logger.info("MORE MENU ITEMS: extracted category '%s'", category)

            return OpenInputResponse(wants_more_menu_items=True, more_menu_category=category)

    return None


# =============================================================================
# Order Signals (for Ingredient Search)
# =============================================================================

def _get_order_signals() -> list[str]:
    """Build order signals list combining data-driven food terms with hardcoded command terms.

    Food-related signals (item types, trigger words) are loaded from database.
    Command signals (ordering verbs, cancel/add commands) remain hardcoded as they
    are domain-agnostic.

    Returns:
        List of order signal terms for detecting ordering context vs ingredient queries.
    """
    global _ORDER_SIGNALS_CACHE
    if _ORDER_SIGNALS_CACHE is not None:
        return _ORDER_SIGNALS_CACHE

    # Data-driven: Get all item type trigger words from database
    food_signals: set[str] = set()
    item_type_triggers = menu_cache.get_item_type_triggers()
    for triggers in item_type_triggers.values():
        food_signals.update(triggers)

    # Also include item type slugs themselves
    food_signals.update(menu_cache.get_all_item_type_slugs())

    # Hardcoded: Non-food command terms (domain-agnostic)
    command_signals = [
        # Ordering verbs
        "please", "want", "like", "get",
        # Cancel/remove commands - should not trigger ingredient search
        "remove", "cancel", "delete", "take off", "no more", "drop",
        "forget", "skip", "hold the", "without", "lose the", "scratch",
        # Add-modifier commands - should not trigger ingredient search
        "add", "extra", "more", "put",
    ]

    _ORDER_SIGNALS_CACHE = list(food_signals) + command_signals
    return _ORDER_SIGNALS_CACHE


# =============================================================================
# Ingredient Search Parsing
# =============================================================================

def _parse_ingredient_search(
    text: str,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse | None:
    """
    Parse ingredient-only inputs and return matching menu items.

    When a user types just an ingredient name (like "chicken" or "something with bacon"),
    this function searches for menu items that contain that ingredient by default.

    Args:
        text: User input text to parse
        ingredient_to_items: Mapping from ingredient names to menu items containing them.
            If None, ingredient search is disabled.

    Returns:
        OpenInputResponse with ingredient_search_query and ingredient_search_matches set,
        or None if no ingredient match found.
    """
    if not ingredient_to_items:
        return None

    text_lower = text.lower().strip()

    # Patterns that indicate ingredient search:
    # - "chicken" (standalone ingredient)
    # - "something with chicken"
    # - "anything with bacon"
    # - "items with turkey"
    # - "what has chicken"
    # - "do you have anything with chicken"

    # Pattern 1: "something/anything/items with [ingredient]"
    with_pattern = re.match(
        r'^(?:(?:i(?:\'?d| would)? like |(?:can i )?(?:get|have) )?'
        r'(?:something|anything|an item|items|a sandwich|sandwiches) '
        r'(?:with|that (?:has|have|contain|contains)) '
        r'(\w+))\s*[?.]?$',
        text_lower
    )
    if with_pattern:
        ingredient = with_pattern.group(1)
        if ingredient in ingredient_to_items:
            result = _build_ingredient_search_response(
                ingredient, ingredient_to_items[ingredient], text_lower, "with_pattern"
            )
            if result:
                return result

    # Pattern 2: "what has [ingredient]" / "what contains [ingredient]"
    what_has_pattern = re.match(
        r'^what (?:has|have|contains?) (\w+)\s*[?.]?$',
        text_lower
    )
    if what_has_pattern:
        ingredient = what_has_pattern.group(1)
        if ingredient in ingredient_to_items:
            result = _build_ingredient_search_response(
                ingredient, ingredient_to_items[ingredient], text_lower, "what_has"
            )
            if result:
                return result

    # Pattern 3: Standalone ingredient name (e.g., just "chicken")
    # Only trigger if it's a short phrase (1-3 words) ending with an ingredient
    # This avoids triggering on complex orders
    words = text_lower.split()
    if len(words) <= 3:
        # Check if the last word is a known ingredient
        potential_ingredient = words[-1].rstrip('?.,!')
        if potential_ingredient in ingredient_to_items:
            # Skip ingredient search if this term is a configurable item type slug
            # e.g., "bagel" should order a bagel, not search for items with bagel
            # Only check against item type slugs (not full triggers which include first words)
            configurable_slugs = menu_cache.get_configurable_item_type_slugs()
            if potential_ingredient in configurable_slugs:
                logger.debug(
                    "INGREDIENT SEARCH: skipping '%s' - configurable item type slug",
                    potential_ingredient
                )
                return None

            # Make sure it's not part of an obvious order ("chicken sandwich", "bacon egg")
            # or a modification/removal command ("remove the bacon", "cancel the ham")
            # or an add-modifier command ("add bacon", "extra cheese")
            order_signals = _get_order_signals()
            # Exclude the ingredient itself from the signal check - if "chicken" is both
            # a trigger and an ingredient, we should allow searching when it's standalone
            # e.g., "chicken" alone should search, "chicken sandwich" should order
            other_signals = [s for s in order_signals if s != potential_ingredient]
            has_order_signal = any(signal in text_lower for signal in other_signals)

            if not has_order_signal:
                result = _build_ingredient_search_response(
                    potential_ingredient,
                    ingredient_to_items[potential_ingredient],
                    text_lower,
                    "standalone"
                )
                if result:
                    return result

    return None
