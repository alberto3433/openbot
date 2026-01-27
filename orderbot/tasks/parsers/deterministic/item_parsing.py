"""
Item Order Parsing Functions.

This module contains functions for parsing item orders from user input,
including configurable items, sodas, by-the-pound items, and split-quantity orders.
"""

import re
import logging

from orderbot.menu_data_cache import menu_cache

from ...schemas import (
    OpenInputResponse,
    Selection,
    ParsedItemEntry,
)
from ..constants import (
    WORD_TO_NUM,
    get_signature_item_aliases,
)
from .extraction import (
    extract_attribute_values,
    _extract_modifiers_generic,
    _extract_quantity,
    _extract_by_pound_info,
)

logger = logging.getLogger(__name__)

# Module-level cache for split-indicator patterns built from database
_SPLIT_INDICATOR_PATTERNS_CACHE: list[str] | None = None


# =============================================================================
# Generic Parsed Item Builder (Data-Driven)
# =============================================================================

def build_parsed_item(
    item_type: str,
    *,
    item_name: str | None = None,
    quantity: int = 1,
    selections: list[Selection] | None = None,
    original_text: str | None = None,
    is_signature: bool = False,
    weight_unit: str | None = None,
    # Backward compatibility - convert to selections internally
    attribute_values: dict | None = None,
    modifiers: list[Selection] | None = None,
) -> ParsedItemEntry:
    """
    Build a ParsedItemEntry from provided data.

    This is a pure data assembly function with no domain knowledge.
    It accepts any item_type, any attribute names, any modifier categories.

    All customizations should be provided via the `selections` parameter.
    The `attribute_values` and `modifiers` parameters are deprecated and
    provided for backward compatibility during migration.

    Args:
        item_type: The item type slug
        item_name: Specific menu item name if known
        quantity: Number of items
        selections: List of Selection objects (preferred)
        original_text: Original user input (for disambiguation context)
        is_signature: Whether this is a signature/speed menu item
        weight_unit: For by-pound items (e.g., "1/4 lb")
        attribute_values: DEPRECATED - Dict of attribute slug -> value
        modifiers: DEPRECATED - List of Selection objects (old parameter name)

    Returns:
        ParsedItemEntry with all fields populated
    """
    # Build the selections list
    final_selections: list[Selection] = []

    # Extract unavailable selections from attribute_values (keys like "_unavailable_size")
    # These are stored separately for helpful "We don't have X" messaging
    unavailable_selections: dict[str, dict] = {}
    clean_attribute_values: dict = {}
    if attribute_values:
        for key, value in attribute_values.items():
            if key.startswith("_unavailable_"):
                # Extract attr_slug from key (e.g., "_unavailable_size" -> "size")
                attr_slug = key[len("_unavailable_"):]
                unavailable_selections[attr_slug] = value
            else:
                clean_attribute_values[key] = value
    else:
        clean_attribute_values = {}

    # If selections provided directly, use them
    if selections:
        final_selections.extend(selections)

    # Backward compat: convert attribute_values dict to selections
    if clean_attribute_values:
        for category, value in clean_attribute_values.items():
            if value is None:
                # Explicitly declined: create _declined marker so orchestrator won't ask
                final_selections.append(Selection(
                    slug="_declined",
                    category=category,
                    quantity=0,
                ))
            elif isinstance(value, bool):
                # Boolean attribute: use yes/no slugs
                final_selections.append(Selection(
                    slug="yes" if value else "no",
                    category=category,
                ))
            elif isinstance(value, list):
                # Multi-select: each item is a dict with slug, quantity, etc.
                for item in value:
                    if isinstance(item, dict):
                        # Use item's category if present and not None, otherwise use outer category
                        item_category = item.get("category") or category
                        final_selections.append(Selection(
                            slug=item.get("slug", ""),
                            category=item_category,
                            quantity=item.get("quantity", 1),
                            price=item.get("price", 0.0),
                            display_name=item.get("display_name"),
                        ))
                    else:
                        # Simple string value
                        final_selections.append(Selection(slug=str(item), category=category))
            elif isinstance(value, str):
                # Single-select: just the slug
                final_selections.append(Selection(slug=value, category=category))

    # Backward compat: add modifiers if provided
    if modifiers:
        final_selections.extend(modifiers)

    return ParsedItemEntry(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        selections=final_selections,
        original_text=original_text,
        is_signature=is_signature,
        weight_unit=weight_unit,
        unavailable_selections=unavailable_selections,
    )


# =============================================================================
# Item Type Detection
# =============================================================================

def _detect_item_type(text: str) -> tuple[str | None, str | None]:
    """Detect item type and matched menu item from text.

    Uses database-driven trigger keywords for each item type.
    Prefers triggers that match at the end of the text (noun position)
    over adjective-position matches of the same length.

    Args:
        text: User input text

    Returns:
        (item_type_slug, menu_item_name) or (None, None)

    """
    text_lower = text.lower()

    # Get all item type triggers from cache
    all_triggers = menu_cache.get_item_type_triggers()

    # Common words that should not be treated as item triggers
    # - Quantity words (e.g., "two" from "Two Egg Sandwich" shouldn't match "two coffees")
    # - Articles and prepositions (e.g., "the" from "The Leo Omelette" shouldn't match "on the side")
    skip_trigger_words = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
    }

    # Collect all matches with their position and length
    # Format: (item_type, keyword, match_length, end_position, is_at_end_region, slug_matches)
    matches: list[tuple[str, str, int, int, bool, bool]] = []

    for item_type_slug, triggers in all_triggers.items():
        for keyword in triggers:
            # Skip common words that appear as triggers from menu item names
            if keyword.lower() in skip_trigger_words:
                continue
            keyword_lower = keyword.lower()
            # Find all occurrences
            idx = text_lower.find(keyword_lower)
            while idx != -1:
                end_pos = idx + len(keyword_lower)
                # Check if this match is in the "end region" (last 20% of text or last 15 chars)
                text_len = len(text_lower)
                end_region_start = max(text_len - 15, int(text_len * 0.8))
                is_at_end = end_pos >= end_region_start
                # Prefer item types where the slug matches the trigger
                slug_matches = keyword_lower == item_type_slug or keyword_lower.rstrip("s") == item_type_slug
                matches.append((item_type_slug, keyword, len(keyword_lower), end_pos, is_at_end, slug_matches))
                idx = text_lower.find(keyword_lower, idx + 1)

    if not matches:
        return None, None

    # Sort by: (1) is_at_end_region (True first), (2) slug_matches (True first), (3) match_length (longer first)
    # This prefers: triggers at end > slug matches > longer matches
    matches.sort(key=lambda x: (not x[4], not x[5], -x[2]))
    best_item_type, best_match, _, _, _, _ = matches[0]

    return best_item_type, best_match


def _is_modifier_chain(text: str) -> bool:
    """Check if text is a single item with modifier chain.

    Returns:
        True if text appears to be a single item with chained modifiers
    """
    if " with " not in text or " and " not in text:
        return False

    text_lower = text.lower()

    # Get the part after "with"
    parts = text_lower.split(" with ", 1)
    if len(parts) < 2:
        return False

    after_with = parts[1]

    if " and " not in after_with:
        return False

    # Get what's after "and"
    and_parts = after_with.split(" and ", 1)
    if len(and_parts) < 2:
        return False

    after_and = and_parts[1].strip()

    # Check if after_and contains an item keyword (would indicate multi-item)
    item_type, _ = _detect_item_type(after_and)
    if item_type:
        # Contains an item keyword - it's multi-item, not modifier chain
        return False

    # If no item keyword found, it's likely a modifier chain
    return True


# =============================================================================
# Generic Item Parsing
# =============================================================================

def _parse_item_generic(
    text: str,
    item_type: str | None = None,
    item_name: str | None = None
) -> ParsedItemEntry | None:
    """Parse any item type using database configuration.

    This is a generic parser that uses database-driven attribute and modifier
    extraction instead of item-type-specific logic. It works for all item types
    that have proper configuration in the database.

    Also handles by-pound items (e.g., "quarter pound of cream cheese").

    Args:
        text: User input text
        item_type: Detected item type slug
                   If None, will attempt to detect from text.
        item_name: Matched menu item name (if any)

    Returns:
        ParsedItemEntry with extracted attributes and modifiers, or None if
        unable to parse

    Example:
        >>> _parse_item_generic("large iced latte", "sized_beverage", "latte")
        ParsedItemEntry(item_type="sized_beverage", item_name="latte",
                       attribute_values={"size": "large", "temperature": "iced"})
        >>> _parse_item_generic("quarter pound of plain cream cheese")
        ParsedItemEntry(item_type="by_pound", item_name="plain cream cheese",
                       weight_unit="1/4 lb")
    """
    text_lower = text.lower()

    # Check for by-pound pattern first
    weight_unit, product_name = _extract_by_pound_info(text_lower)
    if weight_unit:
        # This is a by-pound order - find matching menu item
        by_weight_items = menu_cache.get_menu_items_by_unit_type("by_weight")
        matched_item = None
        for item_name in by_weight_items:
            # Check if product name matches (fuzzy match)
            item_lower = item_name.lower()
            if product_name in item_lower or any(
                word in item_lower for word in product_name.split() if len(word) > 3
            ):
                # Check if weight matches too
                if weight_unit.replace(" ", "") in item_lower.replace(" ", ""):
                    matched_item = item_name
                    break

        return ParsedItemEntry(
            item_type="by_pound",
            item_name=matched_item or product_name,
            quantity=1,
            weight_unit=weight_unit,
            original_text=text,
        )

    # Auto-detect item type if not provided
    if not item_type:
        item_type, detected_name = _detect_item_type(text_lower)
        if not item_type:
            return None
        if not item_name:
            item_name = detected_name

    # Extract quantity from text
    quantity = 1
    qty_match = re.match(r'^(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+dozen|half\s+a\s+dozen|a\s+couple(?:\s+of)?)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1).strip()
        extracted_qty = _extract_quantity(qty_str)
        if extracted_qty is not None:
            quantity = extracted_qty

    # Extract all attributes for this item type using database config
    # This handles all attribute types (single_select, multi_select, boolean)
    # including combined attributes like milk_sweetener_syrup
    attribute_values = extract_attribute_values(text, item_type)

    # Extract food modifiers (proteins, spreads, toppings, etc.)
    # Beverage modifiers (sweeteners, syrups, milk) are handled via attribute_values
    food_modifiers = _extract_modifiers_generic(text_lower, item_type)

    # Check if this is a signature/speed menu item
    is_signature = False
    if item_name:
        signature_items = get_signature_item_aliases()
        # Check if the menu item name matches any signature item
        name_lower = item_name.lower()
        if name_lower in signature_items or item_name in signature_items.values():
            is_signature = True

    # Build food modifiers list with category from database
    modifier_selections: list[Selection] = []
    for mod in food_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=1
        ))

    return build_parsed_item(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attribute_values=attribute_values,
        modifiers=modifier_selections,
        is_signature=is_signature,
        original_text=text,
    )


# =============================================================================
# Configurable Item Parsing (Data-Driven)
# =============================================================================

def _parse_configurable_item(text: str) -> OpenInputResponse | None:
    """
    Parse orders for any configurable item type using data-driven patterns.

    This is the generic replacement for _parse_bagel_with_modifiers() and
    _parse_coffee_deterministic(). It uses database configuration to detect
    which item type is being ordered and extract the appropriate attributes.

    Algorithm:
    1. Check for exclusion phrases (e.g., "coffee cake" should not match "coffee")
    2. Detect item type from text by matching against configurable item type triggers
    3. If no configurable item type detected, return None
    4. Extract quantity
    5. Match specific menu item name within that type
    6. Extract attributes using extract_attribute_values()
    7. Build and return ParsedItemEntry via build_parsed_item()

    Returns:
        OpenInputResponse with parsed_items if a configurable item was detected,
        None otherwise.
    """
    text_lower = text.lower().strip()

    # 1. Check for exclusion phrases (e.g., "coffee cake" -> not a coffee beverage)
    if menu_cache.text_matches_exclusion_phrase(text):
        logger.debug("CONFIGURABLE_ITEM: excluded by required_match_phrases: '%s'", text[:50])
        return None

    # 1b. Check for signature items FIRST - they take precedence over trigger-based detection
    # This prevents "The Classic BEC on a wheat bagel" from matching "omelette" due to "bagel"
    signature_item_name: str | None = None
    signature_item_type: str | None = None
    signature_aliases = get_signature_item_aliases()
    # Sort aliases by length (longest first) for most specific match
    sorted_aliases = sorted(signature_aliases.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if re.search(rf'\b{re.escape(alias)}\b', text_lower):
            signature_item_name = signature_aliases[alias]
            # Look up the item type for this signature item
            signature_item_type = menu_cache.get_item_type_for_menu_item(signature_item_name)
            if signature_item_type:
                logger.info("CONFIGURABLE_ITEM: signature item '%s' detected -> type '%s'", signature_item_name, signature_item_type)
                break

    # 2. Detect which configurable item type this text matches
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()
    detected_item_type: str | None = signature_item_type  # Use signature item type if found

    # Only do trigger-based detection if no signature item was found
    if not detected_item_type:
        # Common words that should not be treated as item triggers
        skip_trigger_words = {
            "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
            "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
        }

        # Collect all matches with position info for smarter selection
        # Format: (item_type, trigger, length, end_pos, is_at_end, slug_matches)
        matches: list[tuple[str, str, int, int, bool, bool]] = []
        text_len = len(text_lower)

        for item_type_slug in configurable_slugs:
            triggers = menu_cache.get_item_type_triggers(item_type_slug)
            for trigger in triggers:
                # Skip common words that appear as triggers from menu item names
                if trigger.lower() in skip_trigger_words:
                    continue
                # Check for word boundary match
                pattern = rf'\b{re.escape(trigger)}s?\b'
                match = re.search(pattern, text_lower)
                if match:
                    end_pos = match.end()
                    # Check if match is in "end region" (last 20% or last 15 chars)
                    end_region_start = max(text_len - 15, int(text_len * 0.8))
                    is_at_end = end_pos >= end_region_start
                    # Prefer item types where slug matches trigger
                    slug_matches = trigger.lower() == item_type_slug or trigger.lower().rstrip("s") == item_type_slug
                    matches.append((item_type_slug, trigger, len(trigger), end_pos, is_at_end, slug_matches))

        if matches:
            # Sort by: (1) is_at_end (True first), (2) slug_matches (True first), (3) length (longer first)
            matches.sort(key=lambda x: (not x[4], not x[5], -x[2]))
            detected_item_type = matches[0][0]

    if not detected_item_type:
        return None

    logger.info("CONFIGURABLE_ITEM: detected type '%s' in '%s'", detected_item_type, text[:50])

    # 3. Extract quantity
    # Handle common prefixes like "I want 5", "Can I get three", "Give me two", etc.
    quantity = 1
    qty_match = re.match(
        r"^(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
        r"(?:can|could|may)\s+i\s+(?:get|have)|"
        r"give\s+me|"
        r"let\s*(?:me|'s)\s*(?:get|have)|"
        r")?\s*"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple|half\s+(?:a\s+)?dozen|a?\s*dozen)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1).strip()
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # 4. Extract attribute values using data-driven extraction
    # This returns all attributes as {slug: value} where value can be:
    # - string for single_select
    # - list[{slug, quantity, ...}] for multi_select
    # - bool for boolean
    attr_values = extract_attribute_values(text, detected_item_type)

    # 5. Try to match a specific menu item name within this type
    # If we already found a signature item, use that name; otherwise try to match
    item_name = signature_item_name or _match_menu_item_name_for_type(text, detected_item_type)

    # Check if this is a signature/speed menu item
    is_signature = False
    if item_name:
        signature_items = get_signature_item_aliases()
        name_lower = item_name.lower()
        if name_lower in signature_items or item_name in signature_items.values():
            is_signature = True

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, is_signature=%s",
        detected_item_type, quantity, item_name, list(attr_values.keys()), is_signature
    )

    # 6. Build ParsedItemEntry using build_parsed_item (converts attr_values to selections)
    parsed_items = [
        build_parsed_item(
            item_type=detected_item_type,
            item_name=item_name,
            attribute_values=attr_values.copy(),
            original_text=text,
            is_signature=is_signature,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(parsed_items=parsed_items)


def _match_menu_item_name_for_type(text: str, item_type_slug: str) -> str | None:
    """
    Try to match a specific menu item name within an item type.

    For example, for sized_beverage, this would try to match "Iced Latte",
    "Hot Coffee", "Chai Tea", etc.

    Args:
        text: User input text
        item_type_slug: The item type slug to search within

    Returns:
        The canonical menu item name if found, None otherwise
    """
    text_lower = text.lower()

    # Get all item names for this type
    item_names = menu_cache.get_item_names_by_type(item_type_slug)
    alias_to_canonical = menu_cache.get_item_alias_to_canonical_by_type(item_type_slug)

    # Try to match longest name first for specificity
    all_names_and_aliases = list(item_names) + list(alias_to_canonical.keys())
    all_names_and_aliases.sort(key=len, reverse=True)

    for name in all_names_and_aliases:
        pattern = rf'\b{re.escape(name)}s?\b'
        if re.search(pattern, text_lower):
            # Return canonical name
            return alias_to_canonical.get(name, name.title())

    return None


def _detect_configurable_item_type(text: str) -> tuple[str | None, str | None]:
    """
    Detect configurable item type from text using database-driven keywords.

    Uses smart matching to prefer:
    1. Triggers that match the item type slug
    2. Triggers that appear at the start of the text
    3. Longer triggers

    Args:
        text: User input text (lowercase)

    Returns:
        (item_type_slug, matched_trigger) or (None, None) if no match
    """
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()
    text_lower = text.lower()
    text_len = len(text_lower)

    # Common words that should not be treated as item triggers
    # - Quantity words (e.g., "two" from "Two Egg Sandwich" shouldn't match "two coffees")
    # - Articles and prepositions (e.g., "the" from "The Leo Omelette" shouldn't match "on the side")
    skip_trigger_words = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
    }

    # Collect all matches with position info for smarter selection
    # Format: (item_type, trigger, length, start_pos, slug_matches)
    matches: list[tuple[str, str, int, int, bool]] = []

    for item_type_slug in configurable_slugs:
        triggers = menu_cache.get_item_type_triggers(item_type_slug)
        for trigger in triggers:
            # Skip common words that appear as triggers from menu item names
            if trigger.lower() in skip_trigger_words:
                continue
            # Match trigger with optional plural 's'
            pattern = rf'\b{re.escape(trigger)}s?\b'
            match = re.search(pattern, text_lower)
            if match:
                start_pos = match.start()
                # Prefer item types where slug matches trigger
                slug_matches = trigger.lower() == item_type_slug or trigger.lower().rstrip("s") == item_type_slug
                matches.append((item_type_slug, trigger, len(trigger), start_pos, slug_matches))

    if not matches:
        return None, None

    # Sort by: (1) slug_matches (True first), (2) start_pos (earlier first), (3) length (longer first)
    matches.sort(key=lambda x: (not x[4], x[3], -x[2]))
    return matches[0][0], matches[0][1]


# =============================================================================
# Split-Quantity Parsing
# =============================================================================

def _get_split_attribute_patterns() -> list[str]:
    """Build split-indicator patterns from database attribute options.

    Returns patterns like:
        r"\\b(?:one|1)\\s+(?:not\\s+)?(?:toasted|iced|hot|...)\\b"

    The attribute option words come from the database, making this data-driven
    instead of hardcoding specific food attributes.

    Returns:
        List of regex patterns for split-quantity detection.
    """
    global _SPLIT_INDICATOR_PATTERNS_CACHE
    if _SPLIT_INDICATOR_PATTERNS_CACHE is not None:
        return _SPLIT_INDICATOR_PATTERNS_CACHE

    # Get all attribute option words from database
    # Handle case where menu cache isn't loaded yet (e.g., during test setup)
    try:
        attr_option_words = menu_cache.get_all_attribute_option_words()
    except Exception:
        # Cache not loaded - return empty list but DON'T cache it
        # so we retry when cache is available
        return []

    if not attr_option_words:
        # Empty result - don't cache, retry later
        return []

    # Build alternation pattern from option words
    # Sort by length descending for greedy matching
    sorted_words = sorted(attr_option_words.keys(), key=len, reverse=True)
    words_pattern = "|".join(re.escape(w) for w in sorted_words)

    # Build patterns for each quantity
    _SPLIT_INDICATOR_PATTERNS_CACHE = [
        rf"\b(?:one|1)\s+(?:not\s+)?(?:{words_pattern})\b",
        rf"\b(?:two|2)\s+(?:not\s+)?(?:{words_pattern})\b",
        rf"\b(?:three|3)\s+(?:not\s+)?(?:{words_pattern})\b",
    ]
    return _SPLIT_INDICATOR_PATTERNS_CACHE


def _count_split_indicators(text: str) -> int:
    """Count split-quantity indicators in text."""
    # Static patterns that don't need DB lookup
    static_indicators = [
        r"\bone\s+with\b",
        r"\b1\s+with\b",
        r"\bfirst\s+with\b",
        r"\bsecond\s+with\b",
        r"\bthe\s+other\s+with\b",
        r"\banother\s+with\b",
        r"\bfirst\s+one\b",
        r"\bsecond\s+one\b",
    ]

    # Get data-driven patterns for attribute options (e.g., "one toasted", "two iced")
    dynamic_patterns = _get_split_attribute_patterns()

    # Combine all patterns
    indicators = static_indicators + dynamic_patterns

    count = 0
    for pattern in indicators:
        count += len(re.findall(pattern, text, re.IGNORECASE))
    return count


def _get_initial_part(text: str) -> str:
    """Get the initial part of text before first split indicator."""
    return re.split(r"\b(?:one|1|first)\s+(?:with\s+)?", text, maxsplit=1, flags=re.IGNORECASE)[0]


def _split_into_parts(text: str) -> list[tuple[int, str]]:
    """
    Split text into (quantity, specification) tuples.

    Returns list of (qty, spec_text) for each part of a split-quantity order.
    """
    pattern = re.compile(
        r"(?:,?\s*(?:and\s+)?)"  # Optional comma/and separator
        r"(one|two|three|1|2|3|first|second|third|the\s+other|another)\s+"  # Quantity/ordinal
        r"(.+?)"  # Specification (non-greedy)
        r"(?=(?:,?\s*(?:and\s+)?(?:one|two|three|1|2|3|first|second|third|the\s+other|another)\s+)|$)",
        re.IGNORECASE
    )

    raw_parts = pattern.findall(text)

    result = []
    for qty_word, spec in raw_parts:
        qty_word_lower = qty_word.lower().strip()
        # Map quantity words to numbers
        if qty_word_lower in ("one", "1", "first", "the other", "another"):
            qty = 1
        elif qty_word_lower in ("two", "2"):
            qty = 2
        elif qty_word_lower == "second":
            qty = 1  # "second" means the second item, qty=1
        elif qty_word_lower in ("three", "3"):
            qty = 3
        elif qty_word_lower == "third":
            qty = 1
        else:
            qty = 1
        result.append((qty, spec.strip()))

    return result


def _parse_split_quantity_items(text: str) -> OpenInputResponse | None:
    """
    Parse orders with multiple configurable items that have different configurations.

    This is a generic, data-driven parser that works for any configurable item type.

    Detects patterns like:
        - "two plain bagels one with scallion cream cheese one with lox"
        - "2 lattes, one iced, one hot"
        - "three teas one with sugar one with honey one plain"

    Returns:
        OpenInputResponse with parsed_items populated, or None if not a split-quantity order.
    """
    text_lower = text.lower().strip()

    # 1. Detect item type from text
    item_type, matched_trigger = _detect_configurable_item_type(text_lower)
    if not item_type:
        return None

    # 2. Detect split-quantity pattern (need at least 2 indicators)
    split_count = _count_split_indicators(text_lower)
    if split_count < 2:
        return None

    logger.info(
        "SPLIT-QUANTITY ITEMS: detected %d split indicators for item_type=%s in '%s'",
        split_count, item_type, text[:60]
    )

    # 3. Extract base properties from initial part
    initial_part = _get_initial_part(text_lower)

    # Extract total quantity
    total_quantity = 2  # Default
    qty_match = re.match(r"^(\d+|two|three|four|five|six)\s+", text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            total_quantity = int(qty_str)
        else:
            total_quantity = WORD_TO_NUM.get(qty_str, 2)

    # Extract base attributes using data-driven extractor
    base_attrs = extract_attribute_values(initial_part, item_type)

    # Try to match a specific menu item name within the type
    base_item_name = _match_menu_item_name_for_type(initial_part, item_type)

    # 4. Split into parts
    parts = _split_into_parts(text_lower)
    if len(parts) < 2:
        # Try simpler split as fallback
        simple_split = re.split(r",?\s*(?:and\s+)?(?:one|1)\s+(?:with\s+)?", text_lower, flags=re.IGNORECASE)
        parts = [(1, p.strip()) for p in simple_split[1:] if p.strip()]

    if len(parts) < 2:
        return None

    logger.info("SPLIT-QUANTITY ITEMS: found %d parts: %s", len(parts), parts)

    # 5. Process each part
    parsed_items: list[ParsedItemEntry] = []
    item_count = 0

    # Filter out the base part if it's captured (first part with qty == total_quantity)
    # The base part describes ALL items, not a differentiated specification
    if parts and parts[0][0] == total_quantity:
        # First part is the base description, skip it
        # We already extracted base_attrs from initial_part
        parts = parts[1:]

    for part_qty, part_text in parts:
        if item_count >= total_quantity:
            break

        # Extract part-specific attributes (item-type-specific)
        part_attrs = extract_attribute_values(part_text, item_type)

        # Merge: part overrides base (None means "explicitly declined" and should override)
        merged_attrs = {**base_attrs}
        for k, v in part_attrs.items():
            merged_attrs[k] = v

        # Create items for this part (build_parsed_item converts attrs to selections)
        items_to_create = min(part_qty, total_quantity - item_count)
        for _ in range(items_to_create):
            parsed_items.append(build_parsed_item(
                item_type=item_type,
                item_name=base_item_name,
                quantity=1,
                attribute_values=merged_attrs,  # Keep None values (explicit decline)
                original_text=text,
            ))
            item_count += 1
            logger.info(
                "SPLIT-QUANTITY ITEMS: item %d: type=%s, attrs=%s",
                item_count, item_type, merged_attrs
            )

    # 6. Fill remaining slots with base config
    while len(parsed_items) < total_quantity:
        parsed_items.append(build_parsed_item(
            item_type=item_type,
            item_name=base_item_name,
            quantity=1,
            attribute_values=base_attrs,  # Keep None values (explicit decline)
            original_text=text,
        ))

    return OpenInputResponse(parsed_items=parsed_items)


# =============================================================================
# Soda Parsing
# =============================================================================

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


# =============================================================================
# By-the-Pound Order Parsing
# =============================================================================

# Pattern to match by-weight orders like "half a pound of whitefish salad"
# Captures: quantity phrase + item name
BY_POUND_PATTERN = re.compile(
    r"""
    (?:
        ((?:a\s+)?half\s+(?:a\s+)?(?:pound|lb))    # a half pound / half a pound / half pound / half lb
        |(\d+(?:\s*/\s*\d+)?)\s*(?:pound|lb)s?     # 1/4 pound, 2 pounds, 1 lb
        |(a\s+(?:pound|lb))                        # a pound / a lb
        |((?:a\s+)?quarter\s+(?:pound|lb))         # a quarter pound / quarter pound / quarter lb
    )
    \s+(?:of\s+)?
    (.+?)                                          # item name
    (?:\s+please)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)


def _find_by_weight_item(item_name: str) -> tuple[str, str] | None:
    """
    Find a by-weight item and its item type by name or alias.

    Uses the generic find_item_by_unit_type() to look up items sold by weight.
    The cache handles exact matches, partial matches, and aliases
    (e.g., "lox" -> "Nova Scotia Salmon").

    Args:
        item_name: The item name to look up (e.g., "whitefish salad", "muenster", "lox")

    Returns:
        Tuple of (canonical_name, item_type_slug) or None if not found.
    """
    from ..constants import find_item_by_unit_type
    return find_item_by_unit_type(item_name, "by_weight")


def _parse_by_pound_order(text: str) -> OpenInputResponse | None:
    """
    Parse by-the-pound orders like "half a pound of whitefish salad".

    This MUST be called BEFORE menu item parsing to prevent items like
    "whitefish salad" from being matched to "Whitefish Salad Sandwich".

    Returns:
        OpenInputResponse with by_pound_items if matched, None otherwise.
    """
    text_lower = text.lower().strip()

    # Strip common action verb prefixes - these indicate intent, not item type
    # The quantity phrase ("quarter pound", "half pound") identifies by-the-pound orders
    action_prefixes = [
        "i'll have ", "i will have ", "i have ", "i'll take ", "i will take ", "i take ",
        "i'll get ", "i will get ", "i get ", "i want ", "i'd like ", "i would like ",
        "i like ", "i need ", "give me ", "can i have ", "can i get ", "let me get ",
        "let me have ", "may i have ", "could i get ", "could i have ",
    ]
    for prefix in action_prefixes:
        if text_lower.startswith(prefix):
            text_lower = text_lower[len(prefix):]
            break

    match = BY_POUND_PATTERN.match(text_lower)
    if not match:
        return None

    # Extract weight and convert to (size, quantity) pair
    # Available sizes in DB: "1/4 lb" and "1 lb"
    half_lb = match.group(1)
    numeric_lb = match.group(2)
    a_lb = match.group(3)
    quarter_lb = match.group(4)
    item_name = match.group(5).strip()

    # Convert weight phrases to (size, quantity) pairs
    # size is "1/4 lb" or "1 lb", quantity is how many of that size
    if quarter_lb:
        size = "1/4 lb"
        item_quantity = 1
    elif half_lb:
        size = "1/4 lb"
        item_quantity = 2
    elif numeric_lb:
        # Handle fractions like "1/4", "1/2", "3/4"
        if "/" in numeric_lb:
            num, denom = numeric_lb.replace(" ", "").split("/")
            fraction = float(num) / float(denom)
            if fraction <= 0.25:
                size = "1/4 lb"
                item_quantity = 1
            elif fraction <= 0.5:
                size = "1/4 lb"
                item_quantity = 2
            elif fraction <= 0.75:
                size = "1/4 lb"
                item_quantity = 3
            else:
                size = "1 lb"
                item_quantity = 1
        else:
            # Whole number of pounds
            num = int(numeric_lb)
            size = "1 lb"
            item_quantity = num
    elif a_lb:
        size = "1 lb"
        item_quantity = 1
    else:
        size = "1 lb"
        item_quantity = 1

    # Look up the item in database via find_item_by_unit_type
    result = _find_by_weight_item(item_name)
    if not result:
        logger.debug("By-weight pattern matched but item not found: '%s'", item_name)
        return None

    canonical_name, item_type_slug = result
    logger.info(
        "BY-WEIGHT ORDER: '%s' -> %s (size=%s, qty=%d, item_type=%s)",
        text[:50], canonical_name, size, item_quantity, item_type_slug
    )

    # Build parsed_items using ParsedItemEntry (unified type)
    # By-weight items are just sized menu items
    parsed_items = [
        ParsedItemEntry(
            item_type=item_type_slug,  # "cheese", "fish", "spread", etc.
            item_name=canonical_name,
            quantity=item_quantity,
            attribute_values={"size": size},
        )
    ]

    return OpenInputResponse(
        parsed_items=parsed_items,
    )
