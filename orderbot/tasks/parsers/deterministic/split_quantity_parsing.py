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
from ...utils.text import normalize_text
from .item_building import build_parsed_item
from .result_types import TextSpan

logger = logging.getLogger(__name__)


def _get_pipeline():
    """Lazy import to avoid circular dependency: pipeline → item_parsing → split_quantity_parsing → pipeline."""
    from .pipeline import get_pipeline
    return get_pipeline()


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
    except (ValueError, KeyError, TypeError, AttributeError):
        # Cache not loaded - return empty list but DON'T cache it
        # so we retry when cache is available
        return []

    if not attr_option_words:
        # Empty result - don't cache, retry later
        return []

    # Also include individual words from multi-word option names so that
    # abbreviated split indicators like "1 everything" match even though the
    # full option name is "everything bagel".  We skip only common English
    # words; item-type triggers (e.g., "bagel") are kept because
    # _parts_contain_different_item_type() already guards against cross-type
    # false positives later in the pipeline.
    skip_words = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for", "not",
        "no", "free", "style", "new",
    }

    individual_words: set[str] = set()
    for key in attr_option_words.keys():
        words = key.replace("_", " ").split()
        if len(words) > 1:
            for word in words:
                word_lower = word.lower()
                if len(word_lower) >= 3 and word_lower not in skip_words:
                    individual_words.add(word_lower)

    # Combine full option names with individual words
    all_pattern_words = set(attr_option_words.keys()) | individual_words

    # Build alternation pattern from option words
    # Sort by length descending for greedy matching
    sorted_words = sorted(all_pattern_words, key=len, reverse=True)
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
        r"\bone\s+without\b",
        r"\b1\s+without\b",
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

    # Ordinals and references that always mean "1 item" (not a count)
    _ORDINAL_QTY_ONE = {"first", "second", "third", "the other", "another"}

    result = []
    for qty_word, spec in raw_parts:
        qty_word_lower = normalize_text(qty_word)
        if qty_word_lower in _ORDINAL_QTY_ONE:
            qty = 1
        elif qty_word_lower.isdigit():
            qty = int(qty_word_lower)
        else:
            qty = WORD_TO_NUM.get(qty_word_lower, 1)
        result.append((qty, spec.strip()))

    return result


def _parts_contain_different_item_type(
    parts: list[tuple[int, str]], item_type: str
) -> bool:
    """Check if any split part references a different configurable item type.

    Uses item type triggers, attribute option words, and modifier phrases to
    distinguish genuine cross-type references (e.g., "latte" in a bagel split)
    from modifier contexts (e.g., "cheese" inside "cream cheese").

    Args:
        parts: List of (quantity, part_text) tuples from _split_into_parts.
        item_type: The detected item type slug for this split-quantity order.

    Returns:
        True if a part references a different item type (caller should bail out).
    """
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()
    all_triggers = menu_cache.get_item_type_triggers()

    # Triggers for the detected type itself — if a word is also a trigger for
    # the detected type, it's not evidence of a *different* type
    detected_type_triggers: set[str] = {t.lower() for t in all_triggers.get(item_type, set())}

    # All attribute option words across ALL types (e.g., "iced", "hot", "toasted", "scallion")
    all_attr_option_words: set[str] = set(menu_cache.get_all_attribute_option_words().keys())

    # Also add individual words from the detected type's attribute option names
    # (catches "everything" from "Everything Bagel" bread option, etc.)
    item_type_attrs = menu_cache.get_item_type_attributes(item_type)
    for attr_config in item_type_attrs.values():
        for opt in attr_config.get("options", []):
            for field in (opt.get("slug", "").replace("_", " "), opt.get("display_name", "")):
                for word in field.lower().split():
                    if len(word) >= 3:
                        all_attr_option_words.add(word)

    # All modifier/ingredient phrases (e.g., "cream cheese", "lox", "scallion cream cheese")
    all_modifier_phrases: set[str] = menu_cache.get_all_modifier_words()

    # Index: individual word → set of modifier phrases containing it
    # Used to check if a trigger word appears inside a longer modifier in context
    modifier_phrases_by_word: dict[str, list[str]] = {}
    for mod in all_modifier_phrases:
        for word in mod.split():
            modifier_phrases_by_word.setdefault(word, []).append(mod)

    skip_words = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
    }

    for _, part_text in parts:
        part_lower = part_text.lower()
        for other_type in configurable_slugs:
            if other_type == item_type:
                continue
            for trigger in all_triggers.get(other_type, set()):
                trigger_lower = trigger.lower()
                if trigger_lower in skip_words or len(trigger_lower) < 3:
                    continue
                if trigger_lower in detected_type_triggers:
                    continue
                if trigger_lower in all_attr_option_words:
                    continue
                if trigger_lower in all_modifier_phrases:
                    continue
                if not re.search(rf'\b{re.escape(trigger_lower)}s?\b', part_lower):
                    continue
                # Check if trigger appears within a longer modifier phrase in the part
                # e.g., "cheese" is part of modifier "cream cheese" → skip
                is_modifier_context = False
                for mod in modifier_phrases_by_word.get(trigger_lower, []):
                    if mod != trigger_lower and re.search(rf'\b{re.escape(mod)}\b', part_lower):
                        is_modifier_context = True
                        break
                if is_modifier_context:
                    continue
                logger.info(
                    "SPLIT-QUANTITY ITEMS: aborting - part '%s' has trigger '%s' for type '%s' (expected '%s')",
                    part_text[:40], trigger_lower, other_type, item_type
                )
                return True
    return False


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
    text_lower = normalize_text(text)

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

    # Extract total quantity - only from leading quantity > 1
    # "1 everything bagel 1 plain bagel" should NOT extract 1 as total
    # "2 bagels one iced one hot" SHOULD extract 2 as total
    # Search initial_part (before first split indicator) so preamble like
    # "I'd like two lattes, ..." doesn't cause the match to fail.
    total_quantity = None  # Will be computed from parts if not found
    qty_match = re.search(r"\b(\d+|two|three|four|five|six)\b", initial_part)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            extracted_qty = int(qty_str)
        else:
            extracted_qty = WORD_TO_NUM.get(qty_str, 1)
        # Only use as total if > 1 (to distinguish from per-item quantities)
        if extracted_qty > 1:
            total_quantity = extracted_qty

    # Exclude the leading quantity span from attribute extraction so "two" in
    # "two large lattes" isn't misinterpreted as quantity=2 for the size attribute.
    qty_exclude_spans = None
    if qty_match and total_quantity is not None:
        qty_exclude_spans = [TextSpan(start=qty_match.start(1), end=qty_match.end(1))]

    # Extract base attributes using data-driven extractor
    base_attr_result = _get_pipeline().extract_attributes(initial_part, item_type, exclude_spans=qty_exclude_spans)

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

    # Validate split parts don't contain triggers for different item types.
    # "two toasted bagels and two large iced lattes" → part "large iced lattes"
    # contains "latte" trigger for espresso_based_beverage, not bagel → bail out
    if _parts_contain_different_item_type(parts, item_type):
        return None

    # Compute total_quantity from parts if not extracted from leading text
    # For "1 everything bagel 1 plain bagel", sum = 1 + 1 = 2
    parts_sum = sum(qty for qty, _ in parts)
    if total_quantity is None:
        total_quantity = parts_sum

    # 5. Process each part
    parsed_items: list[ParsedItemEntry] = []
    item_count = 0

    # Filter out the base part if it's captured (first part with qty == total_quantity)
    # The base part describes ALL items, not a differentiated specification
    # Only applies when there's an explicit total at the start (e.g., "2 bagels one iced one hot")
    if parts and total_quantity != parts_sum and parts[0][0] == total_quantity:
        # First part is the base description, skip it
        # We already extracted base_attrs from initial_part
        parts = parts[1:]

    for part_qty, part_text in parts:
        if item_count >= total_quantity:
            break

        # Extract part-specific attributes (item-type-specific)
        part_attr_result = _get_pipeline().extract_attributes(part_text, item_type)

        # If the trigger word isn't already in the part text, try enriching with it.
        # e.g., "plain" + "bagel" → "plain bagel" matches "Plain Bagel" bread option
        if matched_trigger and matched_trigger.lower() not in part_text.lower():
            enriched_text = f"{part_text} {matched_trigger}"
            enriched_result = _get_pipeline().extract_attributes(enriched_text, item_type)
            if len(enriched_result.values) > len(part_attr_result.values):
                part_attr_result = enriched_result

        # Merge: part overrides base (None means "explicitly declined" and should override)
        merged_attr_result = base_attr_result.merge_with(part_attr_result)

        # Try per-part menu item resolution: combine part text with trigger
        # e.g., part "iced" + trigger "latte" → "iced latte" → "Iced Latte"
        part_item_name = None
        if matched_trigger and part_text.strip() != matched_trigger:
            for candidate in (f"{part_text} {matched_trigger}", f"{matched_trigger} {part_text}"):
                part_item_name = match_menu_item_name_for_type_func(candidate, item_type)
                if part_item_name:
                    break
        effective_item_name = part_item_name or base_item_name

        # Create one entry for this part with the appropriate quantity
        # e.g., "2 plain" → 1 entry with quantity=2, not 2 entries with quantity=1
        items_to_create = min(part_qty, total_quantity - item_count)
        if items_to_create > 0:
            parsed_items.append(build_parsed_item(
                item_type=item_type,
                item_name=effective_item_name,
                quantity=items_to_create,
                attr_result=merged_attr_result,
                original_text=text,
            ))
            item_count += items_to_create
            logger.info(
                "SPLIT-QUANTITY ITEMS: item %d (qty=%d): type=%s, attrs=%s",
                len(parsed_items), items_to_create, item_type, merged_attr_result.values
            )

    # 6. Fill remaining slots with base config
    remaining = total_quantity - item_count
    if remaining > 0:
        parsed_items.append(build_parsed_item(
            item_type=item_type,
            item_name=base_item_name,
            quantity=remaining,
            attr_result=base_attr_result,
            original_text=text,
        ))

    return OpenInputResponse(parsed_items=parsed_items)
