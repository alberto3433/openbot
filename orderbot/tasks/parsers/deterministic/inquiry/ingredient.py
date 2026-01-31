"""Ingredient search parsing."""

import logging
import re

from orderbot.menu_data_cache import menu_cache

from ....schemas import OpenInputResponse

logger = logging.getLogger(__name__)


# Module-level cache for order signals
_ORDER_SIGNALS_CACHE: list[str] | None = None


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


def get_order_signals() -> list[str]:
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


def parse_ingredient_search(
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

    # Pattern 3: Availability questions - "is X available?", "do you have X?"
    availability_pattern = re.match(
        r'^(?:is\s+(?:the\s+)?|do\s+you\s+have\s+(?:any\s+)?|got\s+any\s+)(\w+)(?:\s+available)?\s*\??$',
        text_lower
    )
    if availability_pattern:
        ingredient = availability_pattern.group(1)
        if ingredient in ingredient_to_items:
            result = _build_ingredient_search_response(
                ingredient, ingredient_to_items[ingredient], text_lower, "availability"
            )
            if result:
                return result

    # Pattern 4: Standalone ingredient name (e.g., just "chicken")
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
            order_signals = get_order_signals()
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
