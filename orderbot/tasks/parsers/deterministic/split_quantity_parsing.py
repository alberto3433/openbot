"""
Split-Quantity Item Parsing.

Handles parsing of orders with multiple configurable items that have different
configurations, like:
    - "two plain bagels one with scallion cream cheese one with lox"
    - "2 lattes, one iced, one hot"
    - "three teas one with sugar one with honey one plain"
"""

import re
import logging

from orderbot.cache import menu_cache

from ...schemas import OpenInputResponse, ParsedItemEntry
from ..constants import WORD_TO_NUM
from .extraction import extract_attribute_values
from .item_building import build_parsed_item

logger = logging.getLogger(__name__)

# Module-level cache for split-indicator patterns built from database
_SPLIT_INDICATOR_PATTERNS_CACHE: list[str] | None = None


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


def _parse_split_quantity_items(
    text: str,
    detect_configurable_item_type_func,
    match_menu_item_name_for_type_func,
) -> OpenInputResponse | None:
    """
    Parse orders with multiple configurable items that have different configurations.

    This is a generic, data-driven parser that works for any configurable item type.

    Detects patterns like:
        - "two plain bagels one with scallion cream cheese one with lox"
        - "2 lattes, one iced, one hot"
        - "three teas one with sugar one with honey one plain"

    Args:
        text: User input text to parse
        detect_configurable_item_type_func: Function to detect item type from text
        match_menu_item_name_for_type_func: Function to match menu item name

    Returns:
        OpenInputResponse with parsed_items populated, or None if not a split-quantity order.
    """
    text_lower = text.lower().strip()

    # 1. Detect item type from text
    item_type, matched_trigger = detect_configurable_item_type_func(text_lower)
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
    base_item_name = match_menu_item_name_for_type_func(initial_part, item_type)

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
