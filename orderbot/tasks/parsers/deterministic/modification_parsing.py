"""
Modification Parsing Functions for Deterministic Parsing.

This module contains functions for parsing modifications to existing items,
including adding modifiers, extracting modifications, and "add more" requests.
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import (
    OpenInputResponse,
)

from ..constants import (
    get_known_menu_items,
    clean_extracted_text,
    SKIP_WORDS,
)
from ..intent_patterns import ADD_MORE_PATTERN, ADD_N_MORE_PATTERN
from ..quantity_utils import extract_leading_quantity, BASIC_WORD_TO_NUM

from .pipeline import get_pipeline
from ...shared_constants import ORDERING_PREFIX_RE, LEADING_ARTICLE_RE

# Re-exports from modify_item_parsing
from .modify_item_parsing import (
    _get_attribute_terminators_pattern,
    _match_modifier_before_target_type,
    _match_target_with_modifier,
    _match_implicit_target_modifier,
    _parse_modify_existing_item,
)

# Re-exports from add_modifier_parsing
from .add_modifier_parsing import (
    _match_modifier_before_target,
    _match_modifier_no_target,
    _match_modifier_implicit_target,
    _parse_add_modifier_to_item,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Menu Item Modifications Extraction
# =============================================================================

def _extract_menu_item_modifications(
    text: str, item_type: str | None = None
) -> dict[str, list[dict[str, str]]]:
    """Extract modifications like 'with mayo and mustard' or 'no onions' from text.

    This is the data-driven version that only accepts ingredients explicitly
    linked to the item type in the database.

    Args:
        text: The user input text
        item_type: The item type slug (e.g., "sandwich", "salad"). If None,
            returns empty result.

    Returns:
        Dict with 'additions' and 'removals' lists. Each entry is a dict with:
        - slug: The ingredient slug (lowercase, normalized)
        - category: The ingredient category (e.g., "topping", "protein")

    Examples:
        >>> _extract_menu_item_modifications("with mayo and lettuce", "sandwich")
        {"additions": [{"slug": "mayo", "category": "condiment"}, {"slug": "lettuce", "category": "topping"}], "removals": []}

        >>> _extract_menu_item_modifications("no onions please", "sandwich")
        {"additions": [], "removals": [{"slug": "onion", "category": "topping"}]}
    """
    result: dict[str, list[dict[str, str]]] = {"additions": [], "removals": []}

    if not item_type:
        logger.debug("No item_type provided, returning empty modifications")
        return result

    text_lower = text.lower()

    # Get valid ingredients for this item type, organized by category
    # This is the data-driven lookup that replaces hardcoded known_additions
    ingredients_by_category = menu_cache.get_ingredients_by_category_for_item_type(item_type)
    if not ingredients_by_category:
        logger.debug("No ingredients defined for item type '%s'", item_type)
        return result

    # Build reverse lookup: ingredient name -> category
    ingredient_to_category: dict[str, str] = {}
    for category, ingredients in ingredients_by_category.items():
        for ingredient in ingredients:
            ingredient_to_category[ingredient.lower()] = category

    def match_ingredient(term: str) -> dict[str, str] | None:
        """Try to match a term against valid ingredients for the item type."""
        term = term.strip().lower()
        if not term:
            return None

        # Handle "extra X" by stripping the "extra" prefix
        if term.startswith("extra "):
            term = term[6:].strip()

        # Direct match
        if term in ingredient_to_category:
            return {"slug": term, "category": ingredient_to_category[term]}

        # Try singular form (remove trailing 's')
        if term.endswith("s") and len(term) > 2:
            singular = term[:-1]
            if singular in ingredient_to_category:
                return {"slug": singular, "category": ingredient_to_category[singular]}

        # Try with 's' added (in case user said singular but DB has plural)
        plural = term + "s"
        if plural in ingredient_to_category:
            return {"slug": plural, "category": ingredient_to_category[plural]}

        return None

    # Pattern for "with X and Y" or "with X, Y, and Z"
    # Build dynamic terminator pattern from attribute options
    attr_terminators = _get_attribute_terminators_pattern()
    with_pattern = re.search(
        rf'\bwith\s+(.+?)(?:\s*(?:please|thanks|{attr_terminators})|\s*$)',
        text_lower,
        re.IGNORECASE
    )

    if with_pattern:
        with_text = with_pattern.group(1).strip()
        # Remove trailing punctuation
        with_text = clean_extracted_text(with_text)

        # Split by "and" and commas
        parts = re.split(r'\s*(?:,\s*|\s+and\s+)\s*', with_text)
        for part in parts:
            part = part.strip()
            # Exclude common non-modifier words
            if part in SKIP_WORDS:
                continue

            matched = match_ingredient(part)
            if matched:
                result["additions"].append(matched)

    # Pattern for "no X" modifications
    no_pattern = re.findall(r'\bno\s+(\w+(?:\s+\w+)?)', text_lower)
    for item in no_pattern:
        item = item.strip()
        # Skip common false positives (language patterns, not food)
        skip_items = {'thanks', 'problem', 'worries', 'that', 'more', 'need'}
        if item in skip_items:
            continue

        matched = match_ingredient(item)
        if matched:
            result["removals"].append(matched)

    logger.debug("Extracted modifications from '%s' for item_type '%s': %s", text[:50], item_type, result)
    return result


# =============================================================================
# Menu Item Extraction from Text
# =============================================================================

def _extract_menu_item_from_text(text: str) -> tuple[str | None, int, str | None]:
    """Try to extract a known menu item from text.

    Returns:
        Tuple of (canonical_name, quantity, matched_alias) where:
        - canonical_name: The canonical menu item name or None if not found
        - quantity: Number of items (default 1)
        - matched_alias: The alias text that was found in the input, or None.
            This is useful for finding the span of the match in the original text
            to exclude from attribute/modifier extraction.
    """
    text_lower = text.lower().strip()

    # Strip ordering phrases like "I want", "add", "can I get", etc.
    text_lower = ORDERING_PREFIX_RE.sub('', text_lower)
    text_lower = LEADING_ARTICLE_RE.sub('', text_lower)

    # FIRST: Try matching with FULL text (including any leading numbers)
    # This handles menu items like "3 Bagel Package" where the number is part of the name
    text_for_full_match = text_lower.strip()
    for item in sorted(get_known_menu_items(), key=len, reverse=True):
        pattern = rf'\b{re.escape(item)}\b'
        if re.search(pattern, text_for_full_match):
            canonical = menu_cache.resolve_menu_item_alias(item)
            if canonical is not None:
                return canonical, 1, item

    # Extract quantity using extract_leading_quantity which handles all quantity phrases
    # (a few, couple, dozen, etc.)
    extracted_qty, remaining = extract_leading_quantity(text_lower)
    if extracted_qty is not None:
        quantity = extracted_qty
        text_lower = remaining
        # Strip trailing filler words before singularizing to handle cases like
        # "chocolate babkas please" -> "chocolate babkas" -> "chocolate babka"
        # Without this, "please" at the end confuses the singularization
        trailing_fillers = {"please", "thanks", "thank", "you"}
        words = text_lower.split()
        while words and words[-1] in trailing_fillers:
            words.pop()
        text_lower = " ".join(words)
        # Singularize after extracting quantity: "two cookies" -> "cookie"
        text_lower = singularize(text_lower)
    else:
        quantity = 1

    for item in sorted(get_known_menu_items(), key=len, reverse=True):
        # Use word boundary check to prevent partial matches (e.g., "ham" matching "hamburger")
        # The item should appear as complete words in the text
        pattern = rf'\b{re.escape(item)}\b'
        if re.search(pattern, text_lower):
            # Check if user input is longer than matched item - if so, there might be
            # more specific items that match the full user phrase
            # Example: "orange juice" should NOT match the generic "Juice" item
            # if there are items like "Fresh Squeezed Orange Juice" that match better
            if len(text_lower) > len(item) + 3:  # Allow for minor variations
                # Check if the full user input word-matches any menu items
                more_specific_matches = menu_cache.find_items_by_word_match(text_lower)
                if more_specific_matches:
                    # Found more specific matches - skip this generic match
                    # and let the disambiguation flow handle it
                    logger.debug(
                        "Skipping generic match '%s' for '%s' - found %d more specific matches",
                        item, text_lower, len(more_specific_matches)
                    )
                    continue

            # Use database lookup to get canonical name
            canonical = menu_cache.resolve_menu_item_alias(item)
            if canonical is None:
                # Item not found in database - skip this match and try next
                continue
            return canonical, quantity, item

    return None, 0, None


# =============================================================================
# Add More Request Parsing
# =============================================================================

def _parse_add_more_request(text: str) -> OpenInputResponse | None:
    """
    Parse "add more" requests like "add a third orange juice", "add another coffee",
    or "give me 2 more pounds".

    These phrases mean "add N more" - ordinals like "third" mean "one more to make 3 total",
    NOT "add 3 items".

    Returns OpenInputResponse with quantity for the item, or None if no match.
    """
    stripped = text.strip()
    quantity = 1
    item_text = None

    # Try "another <thing>" pattern first (quantity always 1)
    match = ADD_MORE_PATTERN.match(stripped)
    if match:
        item_text = match.group(1)
    else:
        # Try "N more <thing>" pattern (e.g., "give me 2 more pounds")
        n_match = ADD_N_MORE_PATTERN.match(stripped)
        if n_match:
            qty_str = n_match.group(1)
            quantity = int(qty_str) if qty_str.isdigit() else BASIC_WORD_TO_NUM.get(qty_str.lower(), 1)
            item_text = n_match.group(2)
        else:
            return None

    if item_text:
        item_text = item_text.strip()
        # Clean up trailing punctuation
        item_text = clean_extracted_text(item_text)

    logger.info("ADD MORE REQUEST: detected in '%s', item_text='%s', qty=%d", text[:50], item_text, quantity)

    # If no item specified, we can't parse deterministically - need context
    # The state machine will need to infer from the last item type
    if not item_text:
        if quantity > 1:
            # "give me 2 more" (no item) — duplicate last item N times
            logger.info("ADD MORE: no item specified, qty=%d, treating as duplicate", quantity)
            return OpenInputResponse(duplicate_last_item=quantity)
        # Return a special marker that indicates "add 1 more of whatever was last ordered"
        # For now, return None and let it fall through to LLM or state machine handling
        logger.debug("ADD MORE: no item specified, needs context")
        return None

    # If item_text is an attribute option (e.g., "pound" → weight, "large" → size),
    # treat as "another of the same" — the handler will duplicate the last cart item.
    # Try both the original text and singularized form (e.g., "pounds" → "pound").
    is_option, attr_slug = menu_cache.is_known_attribute_option(item_text)
    if not is_option:
        singular = singularize(item_text)
        if singular != item_text:
            is_option, attr_slug = menu_cache.is_known_attribute_option(singular)
    if is_option:
        all_triggers = menu_cache.get_all_triggers_flat()
        check_text = singularize(item_text) if singularize(item_text) != item_text else item_text
        if item_text not in all_triggers and check_text not in all_triggers:
            logger.info("ADD MORE: '%s' is attribute option (attr=%s), treating as duplicate (qty=%d)", item_text, attr_slug, quantity)
            return OpenInputResponse(duplicate_last_item=quantity)
        logger.info("ADD MORE: '%s' is attribute option but also item type trigger, attempting item parse first", item_text)

    # Import here to avoid circular imports
    from .item_parsing import (
        _parse_configurable_item,
        _detect_configurable_item_type,
        build_parsed_item,
    )
    from .simple_item_parsing import _parse_simple_item_deterministic

    # Try simple (non-configurable) items first - they have more specific names
    # and don't require additional configuration questions
    simple_result = _parse_simple_item_deterministic(item_text)
    if simple_result and simple_result.parsed_items:
        for item in simple_result.parsed_items:
            item.quantity = quantity
        item_name = simple_result.parsed_items[0].item_name if hasattr(simple_result.parsed_items[0], 'item_name') else "item"
        logger.info("ADD MORE: parsed as simple item '%s' (qty=%d)", item_name, quantity)
        return simple_result

    # Try configurable item types using data-driven parser
    configurable_result = _parse_configurable_item(item_text)
    if configurable_result and configurable_result.parsed_items:
        for item in configurable_result.parsed_items:
            item.quantity = quantity
        item_type = configurable_result.parsed_items[0].item_type if hasattr(configurable_result.parsed_items[0], 'item_type') else "item"
        logger.info("ADD MORE: parsed as configurable item '%s' (qty=%d)", item_type, quantity)
        return configurable_result

    # Try menu item (includes signature items)
    menu_item, _, _ = _extract_menu_item_from_text(item_text)
    if menu_item:
        logger.info("ADD MORE: parsed as menu item '%s' (qty=%d)", menu_item, quantity)
        return OpenInputResponse(
            parsed_items=[build_parsed_item(item_type="menu_item", item_name=menu_item, quantity=quantity)],
        )

    # Try to detect any configurable item type using data-driven triggers
    # This replaces hardcoded bagel detection
    detected_type, trigger = _detect_configurable_item_type(item_text)
    if detected_type:
        # Extract attributes using data-driven extraction
        attr_result = get_pipeline().extract_attributes(item_text, detected_type)

        # Try to find the actual menu item name to avoid falling back to item_type slug
        item_name = None
        # 1. Try the trigger as a menu item alias (e.g., "smoked trout" → "Smoked Trout")
        if trigger:
            item_name = menu_cache.resolve_menu_item_alias(trigger)
        # 2. Fallback: check all items of this type for word-boundary match in item_text
        if not item_name:
            type_item_names = menu_cache.get_item_names(detected_type)
            for name in sorted(type_item_names, key=len, reverse=True):
                if re.search(rf'\b{re.escape(name)}\b', item_text.lower()):
                    item_name = menu_cache.resolve_menu_item_alias(name)
                    if item_name:
                        break

        logger.info(
            "ADD MORE: parsed as %s (qty=%d), attrs=%s, item_name=%s",
            detected_type, quantity, list(attr_result.values.keys()), item_name,
        )
        return OpenInputResponse(
            parsed_items=[build_parsed_item(
                item_type=detected_type,
                item_name=item_name,
                attr_result=attr_result,
                quantity=quantity,
            )],
        )

    # Try to resolve item via menu alias lookup (data-driven, replaces hardcoded drink_shorthands)
    resolved_item = menu_cache.resolve_menu_item_alias(item_text)
    if resolved_item:
        # Look up item type for the resolved item
        resolved_item_type = menu_cache.get_item_type_for_menu_item(resolved_item)
        logger.info("ADD MORE: resolved alias '%s' -> '%s' (type=%s, qty=%d)", item_text[:30], resolved_item, resolved_item_type, quantity)
        return OpenInputResponse(
            parsed_items=[build_parsed_item(
                item_type=resolved_item_type or "menu_item",
                item_name=resolved_item,
                quantity=quantity,
            )],
        )

    # Couldn't parse the item as a menu item.
    # If it was a known attribute option (e.g., "pound"), treat as duplicate_last_item.
    if is_option:
        logger.info("ADD MORE: '%s' not parseable as item, falling back to duplicate (attr=%s, qty=%d)", item_text, attr_slug, quantity)
        return OpenInputResponse(duplicate_last_item=quantity)

    # Fall back to LLM
    logger.debug("ADD MORE: couldn't parse item '%s', falling back", item_text)
    return None
