"""
Configurable Item Parsing - Entry Point and Orchestration.

This module contains the main configurable item parsing logic, including
the entry point `_parse_configurable_item()` and supporting functions
for multi-item deferral, inline spec parsing, attribute extraction with
exclusions, and the final item building step.

Split from item_parsing.py during refactoring.
"""

import re
import logging

from orderbot.cache import menu_cache

from ...schemas import (
    OpenInputResponse,
    Selection,
    ParsedItemEntry,
)
from ..constants import (
    WORD_TO_NUM,
    get_items_with_defaults_aliases,
)
from ..quantity_utils import extract_quantity_for_pattern
from ...shared_constants import ORDERING_PREFIX_RE, LEADING_ARTICLE_RE
from ...utils.text import normalize_text

# Import from specialized modules
from .item_building import build_parsed_item
from .menu_item_matching import (
    _resolve_item_type_and_menu_item,
    _has_unrecognized_item_text,
    _get_default_menu_item_for_type,
    _match_menu_item_name_for_type,
)
from .item_type_detection import _detect_item_type
from .qualifier_attachment import (
    _filter_duplicate_instructions,
    _attach_position_qualifiers,
    _attach_amount_qualifiers,
    _handle_partial_modifier_split,
)

logger = logging.getLogger(__name__)


def _should_defer_to_multi_item_parser(text_lower: str, text: str) -> bool:
    """Check if text contains multi-item patterns that should be handled by _parse_multi_item_order.

    Checks two patterns:
    1. "one X and one Y" or "2 X and 3 Y" - quantity on both sides of "and"
    2. Same item type trigger appears on BOTH sides of " and "

    Args:
        text_lower: Lowercased user input text
        text: Original user input text

    Returns:
        True if multi-item parser should handle this text
    """
    # Pattern 1: "one X and one Y" or "2 X and 3 Y" - quantity on both sides of "and"
    # This prevents "one everything bagel and one plain bagel" from being treated as one item
    # BUT: We must verify the qty word after "and" is followed by an item trigger, not a modifier
    # e.g., "a latte with milk and 2 sugars" should NOT be multi-item (sugars is a modifier)
    # e.g., "a latte and 2 coffees" SHOULD be multi-item (coffees is an item trigger)
    qty_words = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|an?)"
    if " and " in text_lower:
        parts = text_lower.split(" and ", 1)
        if len(parts) == 2:
            before_and, after_and = parts[0], parts[1].strip()
            # Check if before_and has a quantity pattern
            left_has_qty = re.search(rf'\b{qty_words}\b', before_and)
            # Check if after_and starts with qty + word
            right_qty_match = re.match(rf'^({qty_words})\s+(\w+)', after_and)
            if left_has_qty and right_qty_match:
                following_word = right_qty_match.group(2).lower()
                # Strip trailing 's' for singular form check
                following_word_singular = following_word.rstrip('s') if following_word.endswith('s') else following_word
                # Check if this word is an item type trigger
                all_triggers = menu_cache.get_all_triggers_flat()
                is_item_trigger = (
                    following_word in all_triggers or
                    following_word_singular in all_triggers
                )
                if is_item_trigger:
                    logger.debug("CONFIGURABLE_ITEM: skipping multi-item pattern (qty before and after 'and' with item trigger '%s'), delegating to multi-item parser: '%s'", following_word, text[:50])
                    return True

                # Also check if after_and (minus the quantity) is a menu item or item with defaults
                # This handles "one bagel and one classic BEC" where "classic BEC" has default ingredients
                # Strip the leading quantity from after_and to get the item part
                after_and_item_part = re.sub(rf'^{qty_words}\s+', '', after_and, count=1)
                # Late import to avoid circular dependency
                from .item_indicator import _has_item_indicator
                has_item, _, _ = _has_item_indicator(after_and_item_part)
                if has_item:
                    logger.debug("CONFIGURABLE_ITEM: skipping multi-item pattern (qty before and after 'and', right part '%s' is item indicator), delegating to multi-item parser: '%s'", after_and_item_part, text[:50])
                    return True

    # Pattern 2: Same item type trigger appears on BOTH sides of " and "
    # This catches "plain bagel and everything bagel" where no explicit quantities are used
    # but the same item type keyword appears twice (once on each side)
    if " and " in text_lower:
        parts = text_lower.split(" and ", 1)
        if len(parts) == 2:
            left_part, right_part = parts
            # Check if the same configurable item type trigger appears in both parts
            configurable_slugs = menu_cache.get_configurable_item_type_slugs()
            for item_type_slug in configurable_slugs:
                triggers = menu_cache.get_item_type_triggers(item_type_slug)
                for trigger in triggers:
                    trigger_lower = trigger.lower()
                    # Skip very short triggers that might cause false positives
                    if len(trigger_lower) < 3:
                        continue
                    # Check if trigger appears as word boundary in BOTH parts
                    trigger_pattern = rf'\b{re.escape(trigger_lower)}s?\b'
                    left_match = re.search(trigger_pattern, left_part)
                    right_match = re.search(trigger_pattern, right_part)
                    if left_match and right_match:
                        logger.debug(
                            "CONFIGURABLE_ITEM: skipping multi-item pattern (trigger '%s' appears before and after 'and'), "
                            "delegating to multi-item parser: '%s'",
                            trigger, text[:50]
                        )
                        return True

    return False


def _try_parse_inline_specs(
    text: str,
    text_lower: str,
    detected_item_type: str,
    matched_item_name: str | None,
    quantity: int,
) -> OpenInputResponse | None:
    """Check for inline attribute specifications and parse them if found.

    Handles patterns like "2 bagels 1 everything 1 plain" where the user specifies
    attribute values inline with quantities.

    Args:
        text: Original user input text
        text_lower: Lowercased user input text
        detected_item_type: The detected item type slug
        matched_item_name: The matched menu item name (if any)
        quantity: The extracted quantity

    Returns:
        OpenInputResponse if inline specs found, None otherwise
    """
    if quantity > 1 and matched_item_name is None:
        from .inline_spec_parsing import (
            parse_inline_attribute_specs,
            extract_text_after_item_match,
            get_primary_configurable_attribute,
        )

        # Check if this item type has a primary configurable attribute
        primary_attr = get_primary_configurable_attribute(detected_item_type)
        if primary_attr:
            # Get triggers for this item type to find text after item mention
            triggers = menu_cache.get_item_type_triggers(detected_item_type)
            text_after_item = extract_text_after_item_match(text_lower, list(triggers))

            if text_after_item:
                # Try to parse inline specs
                inline_specs = parse_inline_attribute_specs(
                    text_after_item,
                    quantity,
                    detected_item_type,
                )

                if inline_specs:
                    # Create separate ParsedItemEntry for each specification
                    parsed_items = []
                    specified_total = sum(s["quantity"] for s in inline_specs)

                    for spec in inline_specs:
                        item_entry = build_parsed_item(
                            item_type=detected_item_type,
                            item_name=matched_item_name,
                            quantity=spec["quantity"],
                            attribute_values={spec["attr_slug"]: spec["attr_value"]},
                            original_text=text,
                        )
                        parsed_items.append(item_entry)

                    # If partial spec (specified_total < quantity), add remaining unspecified items
                    if specified_total < quantity:
                        remaining_qty = quantity - specified_total
                        unspecified_entry = build_parsed_item(
                            item_type=detected_item_type,
                            item_name=matched_item_name,
                            quantity=remaining_qty,
                            original_text=text,
                        )
                        parsed_items.append(unspecified_entry)

                    logger.info(
                        "INLINE_SPEC: Created %d items from inline specs: %s",
                        len(parsed_items),
                        [(p.quantity, list(s.slug for s in p.selections)) for p in parsed_items]
                    )
                    return OpenInputResponse(parsed_items=parsed_items)

    return None


def _extract_attributes_with_exclusions(
    text: str,
    detected_item_type: str,
    matched_item_span: tuple[int, int] | None,
    item_qty_span: tuple[int, int] | None,
    inferred_attr_values: dict,
) -> tuple:
    """Extract attributes via pipeline, applying span exclusions and merging inferred values.

    Builds exclude_spans from the matched menu item name and item quantity to prevent
    attribute extraction from matching words within those spans. Then merges any
    inferred attribute values (from option alias fallback) into the result.

    Returns:
        (attr_result, attr_matched_spans) where attr_result is an AttributeExtractionResult
        and attr_matched_spans is a list of (start, end) tuples.
    """
    from .pipeline import get_pipeline
    from .result_types import TextSpan
    exclude_spans_for_attrs: list[TextSpan] = []
    if matched_item_span:
        exclude_spans_for_attrs.append(TextSpan(start=matched_item_span[0], end=matched_item_span[1]))
    if item_qty_span:
        exclude_spans_for_attrs.append(TextSpan(start=item_qty_span[0], end=item_qty_span[1]))

    attr_result = get_pipeline().extract_attributes(text, detected_item_type, exclude_spans=exclude_spans_for_attrs if exclude_spans_for_attrs else None)
    attr_matched_spans = [(s.start, s.end) for s in attr_result.matched_spans]

    # Merge inferred attribute values from option alias fallback
    # Only add inferred values if not already extracted from text
    # Create a new result with merged values to preserve typed data
    if inferred_attr_values:
        from .result_types import AttributeExtractionResult
        merged_values = {**inferred_attr_values}
        merged_values.update(attr_result.values)  # Extracted values override inferred
        attr_result = AttributeExtractionResult(
            values=merged_values,
            matched_spans=attr_result.matched_spans,
            unavailable=attr_result.unavailable,
            unmatched=attr_result.unmatched,
        )

    return attr_result, attr_matched_spans


def _extract_and_build_configurable_item(
    text: str,
    text_lower: str,
    detected_item_type: str,
    matched_item_name: str | None,
    matched_item_span: tuple[int, int] | None,
    inferred_attr_values: dict,
    quantity: int,
    item_qty_span: tuple[int, int] | None = None,
) -> OpenInputResponse | None:
    """Extract attributes, modifiers, and build the final configurable item response.

    Coordinates helper methods to:
    1. Match menu item name (if not already matched)
    2. Extract attributes via pipeline with span exclusions
    3. Resolve item name (unrecognized text guard, default fallback)
    4. Handle partial modifier splits (e.g., "4 coffees 2 with milk")
    5. Extract food modifiers and special instructions
    6. Build the final ParsedItemEntry

    Args:
        text: Original user input text
        text_lower: Lowercased user input text
        detected_item_type: The detected item type slug
        matched_item_name: The matched menu item name (if any)
        matched_item_span: The span of the matched item name in text_lower (if any)
        inferred_attr_values: Pre-filled attribute values from option alias fallback
        quantity: The extracted quantity
        item_qty_span: The span of the item-level quantity word (if any)

    Returns:
        OpenInputResponse with parsed_items, or None if unrecognized item text detected
    """
    from .pipeline import get_pipeline
    # Early menu item name matching
    # This finds the specific menu item within the item type (e.g., "Hot Coffee" for coffee).
    # NOTE: We do NOT use the span from this match for exclusion because menu item NAMES
    # like "Bagel" are short and don't contain modifier words. The span exclusion is only
    # needed for ALIASES matched in step 1b (e.g., "ham egg and cheese" contains "cheese"
    # which shouldn't trigger cheese attribute matching).
    if not matched_item_name:
        matched_item_name = _match_menu_item_name_for_type(text, detected_item_type)

    # Extract attributes with span exclusions and merge inferred values
    attr_result, attr_matched_spans = _extract_attributes_with_exclusions(
        text, detected_item_type, matched_item_span, item_qty_span, inferred_attr_values,
    )

    item_name = matched_item_name

    # Guard against creating generic items from partial trigger matches
    # If we detected an item type but no specific menu item matched,
    # check if there's unrecognized text that could be a missing menu item.
    # E.g., "iced mocha" - "iced" triggers coffee_based_beverage but "mocha" is unrecognized.
    if not item_name:
        if _has_unrecognized_item_text(text, detected_item_type):
            logger.info(
                "CONFIGURABLE_ITEM: rejecting generic parse - unrecognized text in '%s' for type '%s'",
                text[:50], detected_item_type
            )
            return None

    # If no specific menu item matched (and no unrecognized text), try to pick a default
    # This handles cases like "hot tea" or just "coffee" where we use the type's default item
    if not item_name:
        item_name = _get_default_menu_item_for_type(detected_item_type)
        if item_name:
            logger.debug(
                "Using default menu item '%s' for type '%s'",
                item_name, detected_item_type
            )

    # Check if this item has default ingredients (used for populating defaults)
    has_defaults = False
    if item_name:
        items_with_defaults = get_items_with_defaults_aliases()
        name_lower = item_name.lower()
        if name_lower in items_with_defaults or item_name in items_with_defaults.values():
            has_defaults = True

    # Extract item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions = get_pipeline().extract_special_instructions(text).instructions

    # Check for partial-modifier split (e.g., "4 coffees 2 with milk")
    if quantity > 1 and item_name:
        split_response = _handle_partial_modifier_split(
            text, text_lower, detected_item_type, item_name,
            quantity, has_defaults, special_instructions,
        )
        if split_response:
            return split_response

    # Extract food modifiers (proteins, spreads, toppings, etc.)
    # These are ingredients not handled via attribute_values (which handles items that
    # overlap with attribute options like bread types, egg styles, etc.)
    # Pass exclude_spans to avoid double-extraction of text already matched as attributes
    food_modifiers = get_pipeline().extract_modifiers_raw(text_lower, detected_item_type, exclude_spans=attr_matched_spans)
    modifier_selections: list[Selection] = []
    for mod in food_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        mod_quantity = extract_quantity_for_pattern(text_lower, mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=mod_quantity
        ))

    # Filter out special instructions already captured as selections
    special_instructions = _filter_duplicate_instructions(
        special_instructions, attr_result, modifier_selections,
    )

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, mods=%s, has_defaults=%s, instructions=%s",
        detected_item_type, quantity, item_name, list(attr_result.values.keys()), [s.slug for s in modifier_selections], has_defaults, special_instructions,
    )

    # Build ParsedItemEntry using build_parsed_item (converts attr_result to selections)
    # Create single entry with full quantity - ItemAdderHandler handles threshold logic
    parsed_item = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=quantity,
        attr_result=attr_result,
        modifiers=modifier_selections,
        original_text=text,
        special_instructions=special_instructions,
    )

    # Attach position qualifiers (e.g., "on the side") to matching selections
    _attach_position_qualifiers(parsed_item, text_lower)
    # Attach amount qualifiers (e.g., "extra", "light") to matching selections
    _attach_amount_qualifiers(parsed_item, text_lower)

    return OpenInputResponse(parsed_items=[parsed_item])


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
    6. Extract attributes using pipeline.extract_attributes()
    7. Build and return ParsedItemEntry via build_parsed_item()

    Returns:
        OpenInputResponse with parsed_items if a configurable item was detected,
        None otherwise.
    """
    text_lower = normalize_text(text)

    # Strip ordering phrases for cleaner matching (these don't affect item detection)
    # Note: "i like" is NOT stripped - it's a statement, not an ordering phrase
    text_cleaned = ORDERING_PREFIX_RE.sub('', text_lower)
    text_cleaned = LEADING_ARTICLE_RE.sub('', text_cleaned)

    # 1. Check for exclusion phrases (e.g., "coffee cake" -> not a coffee beverage)
    if menu_cache.text_matches_exclusion_phrase(text):
        logger.debug("CONFIGURABLE_ITEM: excluded by required_match_phrases: '%s'", text[:50])
        return None

    # 2. Check for multi-item patterns that should be handled by _parse_multi_item_order
    if _should_defer_to_multi_item_parser(text_lower, text):
        return None

    # 3. Resolve item type and menu item
    resolution = _resolve_item_type_and_menu_item(text, text_lower, text_cleaned)
    if resolution is None:
        return None
    detected_item_type, matched_item_name, matched_item_span, inferred_attr_values = resolution

    logger.info("CONFIGURABLE_ITEM: detected type '%s' in '%s'", detected_item_type, text[:50])

    # 4. Extract quantity BEFORE menu item name matching
    # We need quantity first to check for inline attribute specs like "2 bagels 1 everything 1 plain"
    quantity = 1
    item_qty_span = None
    qty_match = re.match(
        r"^(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|i'?ll\s*(?:have|do|take|grab|get)|"
        r"(?:can|could|may)\s+i\s+(?:get|have)|"
        r"give\s+me|"
        r"let\s*(?:me|'s)\s*(?:get|have)|"
        r")?(?:\s*to\s+(?:order|get|have|buy))?\s*"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple|a\s+few|few|half\s+(?:a\s+)?dozen|a?\s*dozen)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1).strip()
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

        # Capture span of item-level quantity word to prevent attribute-level re-consumption
        # e.g., "two" in "two large iced lattes" should not also set size quantity to 2
        if quantity > 1:
            item_qty_span = (qty_match.start(1), qty_match.end(1))

        # Check if the extracted number is actually part of a menu item name
        # e.g., "3 bagel package" -> "3" is part of "3 Bagel Package", not a quantity
        # Try matching the full text (with number) against menu items for this item type
        if quantity > 1 or qty_str.isdigit():
            item_names = menu_cache.get_item_names(detected_item_type)
            for item_name in sorted(item_names, key=len, reverse=True):
                if qty_str in item_name and re.search(rf'\b{re.escape(item_name)}\b', text_cleaned):
                    # The number is part of the item name, not a quantity
                    quantity = 1
                    item_qty_span = None
                    logger.debug(
                        "CONFIGURABLE_ITEM: number '%s' is part of item name '%s', qty reset to 1",
                        qty_str, item_name
                    )
                    break

    # 5. Check for inline attribute specifications
    inline_result = _try_parse_inline_specs(text, text_lower, detected_item_type, matched_item_name, quantity)
    if inline_result:
        return inline_result

    # 6. Extract configuration and build result
    return _extract_and_build_configurable_item(
        text, text_lower, detected_item_type, matched_item_name,
        matched_item_span, inferred_attr_values, quantity,
        item_qty_span=item_qty_span,
    )
