"""
Item Order Parsing Functions.

This module contains the core item parsing logic for configurable items.
Specialized parsers for sodas, by-pound items, and split-quantity orders
are in separate modules.

Main entry point: _parse_configurable_item()

Sub-modules:
- item_type_detection: Item type detection via triggers and option aliases
- menu_item_matching: Menu item name matching and resolution
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
from .extraction import (
    _extract_quantity,
    _extract_by_pound_info,
)
from ..quantity_utils import extract_quantity_for_pattern
from ...shared_constants import ORDERING_PREFIX_RE, LEADING_ARTICLE_RE

# Import from specialized modules
from .item_building import build_parsed_item
from .split_quantity_parsing import _parse_split_quantity_items as _parse_split_quantity_items_impl

# Re-export item type detection functions for backward compatibility
from .item_type_detection import (  # noqa: F401
    _SKIP_TRIGGER_WORDS,
    _find_trigger_matches,
    _detect_item_type,
    _is_modifier_chain,
    _detect_type_by_triggers,
    _try_option_alias_fallback,
    _detect_configurable_item_type,
)

# Re-export menu item matching functions for backward compatibility
from .menu_item_matching import (  # noqa: F401
    _match_item_with_defaults,
    _check_more_specific_menu_items,
    _resolve_item_type_and_menu_item,
    _has_unrecognized_item_text,
    _get_default_menu_item_for_type,
    _match_menu_item_name_for_type_with_span,
    _match_menu_item_name_for_type,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Partial Quantity Split Detection
# =============================================================================

def _detect_partial_modifier_split(text_after_item: str, total_qty: int) -> tuple[int, str] | None:
    """
    Detect patterns like "2 with milk and sugar" after item name.

    This handles cases where a subset of items should have modifiers applied,
    e.g., "4 coffees 2 with milk" -> 2 with milk, 2 plain.

    This is MVP functionality that handles only SIMPLE splits:
    - "4 coffees 2 with milk" -> split detected
    - "4 coffees, 2 with milk" -> split detected (comma is fine)
    - "10 coffees - 5 with milk, 3 black, 2 with cream" -> NOT handled (multiple splits)

    Args:
        text_after_item: The text appearing after the item name
        total_qty: Total quantity of items ordered

    Returns:
        (split_qty, modifier_text) if pattern found and split_qty < total_qty
        None otherwise
    """
    # Normalize: strip leading punctuation/whitespace for cleaner matching
    text_clean = text_after_item.lstrip(' ,-')

    # Check for multiple split specs (e.g., "2 with milk, 1 black" or "2 with milk 1 with sugar")
    # Pattern matches "N with" or "N [word]" where N is a quantity
    qty_pattern = r'\b(\d+|one|two|three|four|five)\s+(?:with\b|\w+)'
    qty_matches = list(re.finditer(qty_pattern, text_clean, re.IGNORECASE))
    if len(qty_matches) > 1:
        return None

    # Simple pattern: "N with modifiers"
    pattern = r'\b(\d+|one|two|three|four|five)\s+with\s+(.+)'
    match = re.search(pattern, text_clean, re.IGNORECASE)
    if match:
        qty_str = match.group(1).lower()
        modifier_text = match.group(2).strip()
        split_qty = int(qty_str) if qty_str.isdigit() else WORD_TO_NUM.get(qty_str, 0)
        if 0 < split_qty < total_qty:
            return (split_qty, modifier_text)
    return None


# =============================================================================
# Generic Item Parsing
# =============================================================================

def _parse_by_pound_item(text: str, text_lower: str) -> ParsedItemEntry | None:
    """Check for and parse by-pound orders (e.g., "quarter pound of cream cheese").

    Args:
        text: Original user input text.
        text_lower: Lowercased user input.

    Returns:
        ParsedItemEntry with item_type="by_pound" if matched, None otherwise.
    """
    weight_unit, product_name = _extract_by_pound_info(text_lower)
    if not weight_unit:
        return None

    by_weight_items = menu_cache.get_menu_items_by_unit_type("by_weight")
    matched_item = None
    for name in by_weight_items:
        name_lower = name.lower()
        if product_name in name_lower or any(
            word in name_lower for word in product_name.split() if len(word) > 3
        ):
            if weight_unit.replace(" ", "") in name_lower.replace(" ", ""):
                matched_item = name
                break

    return ParsedItemEntry(
        item_type="by_pound",
        item_name=matched_item or product_name,
        quantity=1,
        weight_unit=weight_unit,
        original_text=text,
    )


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
    """
    text_lower = text.lower()

    # Check for by-pound pattern first
    by_pound_result = _parse_by_pound_item(text, text_lower)
    if by_pound_result:
        return by_pound_result

    # Auto-detect item type if not provided
    if not item_type:
        item_type, detected_name = _detect_item_type(text_lower)
        if not item_type:
            return None
        if not item_name:
            item_name = detected_name

    # Try to resolve item_name to a specific menu item name within this item type.
    # This handles cases where item_name is a trigger word (e.g., 'latte') that could
    # resolve to a specific menu item (e.g., 'Hot Latte') based on context in the text.
    # Always try resolution when we have an item_type, as the text may contain
    # disambiguating context (like "hot" vs "iced") that _match_menu_item_name_for_type can use.
    if item_type:
        resolved_name = _match_menu_item_name_for_type(text, item_type)
        if resolved_name:
            item_name = resolved_name

    # Extract quantity from text
    quantity = 1
    item_qty_span = None
    qty_match = re.match(r'^(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+dozen|half\s+a\s+dozen|a\s+couple(?:\s+of)?|a\s+few|few)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1).strip()
        extracted_qty = _extract_quantity(qty_str)
        if extracted_qty is not None:
            quantity = extracted_qty
            # Capture span of item-level quantity word to prevent attribute-level re-consumption
            if quantity > 1:
                item_qty_span = (qty_match.start(1), qty_match.end(1))

    # Compute the span of the matched menu item name in the text so we can exclude it
    # from modifier extraction. Without this, words within composite item names
    # (e.g., "kalamata olive" in "Kalamata Olive Feta Cream Cheese Sandwich") get falsely
    # extracted as modifiers/selections, causing incorrect pricing.
    # NOTE: We only exclude the item name span from MODIFIER extraction, not attribute
    # extraction. Short item names like "Bagel" may overlap with attribute option triggers
    # (e.g., "bagel" → bread type), so excluding from attributes would break detection.
    matched_item_span: tuple[int, int] | None = None
    if item_name:
        item_name_lower = item_name.lower()
        pos = text_lower.find(item_name_lower)
        if pos != -1:
            matched_item_span = (pos, pos + len(item_name_lower))

    # Extract all attributes for this item type using database config
    # This handles all attribute types (single_select, multi_select, boolean)
    # including combined attributes like milk_sweetener_syrup
    # Pass item_qty_span as exclude_span to prevent the item quantity word
    # (e.g., "two" in "two large iced lattes") from being re-consumed as
    # an attribute-level quantity (which would make size="2 Larges" instead of "Large")
    from .pipeline import get_pipeline
    from .result_types import TextSpan
    exclude_spans_for_attrs = None
    if item_qty_span:
        exclude_spans_for_attrs = [TextSpan(start=item_qty_span[0], end=item_qty_span[1])]
    attr_result = get_pipeline().extract_attributes(text, item_type, exclude_spans=exclude_spans_for_attrs)
    attr_matched_spans = [(s.start, s.end) for s in attr_result.matched_spans]

    # Extract food modifiers (proteins, spreads, toppings, etc.)
    # Beverage modifiers (sweeteners, syrups, milk) are handled via attr_result
    # Pass exclude_spans to avoid double-extraction of text already matched as attributes
    # Also include matched_item_span to prevent extracting ingredients from the item name
    modifier_exclude_spans = list(attr_matched_spans)
    if matched_item_span:
        modifier_exclude_spans.append(matched_item_span)
    food_modifiers = get_pipeline().extract_modifiers_raw(text_lower, item_type, exclude_spans=modifier_exclude_spans)

    # Check if this item has default ingredients (used for populating defaults)
    has_defaults = False
    if item_name:
        items_with_defaults = get_items_with_defaults_aliases()
        # Check if the menu item name matches any item with default ingredients
        name_lower = item_name.lower()
        if name_lower in items_with_defaults or item_name in items_with_defaults.values():
            has_defaults = True

    # Build food modifiers list with category from database
    # Extract quantity for each modifier (e.g., "extra bacon" -> quantity=2)
    modifier_selections: list[Selection] = []
    for mod in food_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        mod_quantity = extract_quantity_for_pattern(text_lower, mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=mod_quantity
        ))

    # Extract item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions = get_pipeline().extract_special_instructions(text).instructions

    return build_parsed_item(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attr_result=attr_result,
        modifiers=modifier_selections,
        original_text=text,
        special_instructions=special_instructions,
    )


# =============================================================================
# Configurable Item Parsing (Data-Driven)
# =============================================================================

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
                from .tokenization import _has_item_indicator
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


def _handle_partial_modifier_split(
    text: str,
    text_lower: str,
    detected_item_type: str,
    item_name: str,
    quantity: int,
    has_defaults: bool,
    special_instructions: list[str],
) -> OpenInputResponse | None:
    """Check for and handle partial-modifier split patterns.

    Detects patterns like "4 coffees 2 with milk" where a subset of items should
    have modifiers applied (2 with milk, 2 plain).

    Returns:
        OpenInputResponse with split items if a split was detected, None otherwise.
    """
    # Try to find the item name in text. Item name like "Hot Coffee" may appear as "coffees".
    # First try full name match, then try individual words.
    item_name_lower = item_name.lower()
    item_name_match = re.search(rf'\b{re.escape(item_name_lower)}s?\b', text_lower)
    if not item_name_match:
        # Try matching individual words (e.g., "coffee" from "Hot Coffee")
        for word in item_name_lower.split():
            if len(word) >= 3:  # Skip short words like "a", "an", "the"
                item_name_match = re.search(rf'\b{re.escape(word)}s?\b', text_lower)
                if item_name_match:
                    break
    if not item_name_match:
        return None

    text_after_item = text_lower[item_name_match.end():]
    split_result = _detect_partial_modifier_split(text_after_item, quantity)
    if not split_result:
        return None

    split_qty, modifier_text = split_result
    remaining_qty = quantity - split_qty

    logger.info(
        "PARTIAL_SPLIT: detected %d with '%s', %d unmodified",
        split_qty, modifier_text, remaining_qty
    )

    # Extract BASE attributes from text BEFORE the split point
    # e.g., "4 large hot coffees 2 with milk" -> base text is "4 large hot coffees"
    from .pipeline import get_pipeline
    text_before_split = text_lower[:item_name_match.end()]
    base_attr_result = get_pipeline().extract_attributes(text_before_split, detected_item_type)

    # Also extract any attribute values from modifier text
    split_attr_result = get_pipeline().extract_attributes(modifier_text, detected_item_type)
    split_matched_spans = [(s.start, s.end) for s in split_attr_result.matched_spans]

    # Extract modifiers from "with X" portion only
    # Pass exclude_spans to avoid double-extraction of attributes
    split_modifiers = get_pipeline().extract_modifiers_raw(modifier_text, detected_item_type, exclude_spans=split_matched_spans)
    modifier_selections_split: list[Selection] = []
    for mod in split_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        mod_qty = extract_quantity_for_pattern(modifier_text, mod)
        modifier_selections_split.append(Selection(
            slug=mod, category=category, quantity=mod_qty
        ))

    # Merge base + split attributes: split overrides base
    merged_attr_result = base_attr_result.merge_with(split_attr_result)

    # Build items WITH modifiers
    items_with_mods = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=split_qty,
        attr_result=merged_attr_result,
        modifiers=modifier_selections_split,
        original_text=text,
        special_instructions=special_instructions,
    )

    # Build items WITHOUT modifiers (plain)
    items_plain = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=remaining_qty,
        attr_result=base_attr_result,
        modifiers=[],
        original_text=text,
        special_instructions=[],
    )

    return OpenInputResponse(parsed_items=[items_with_mods, items_plain])


def _filter_duplicate_instructions(
    special_instructions: list[str],
    attr_result,
    modifier_selections: list[Selection],
) -> list[str]:
    """Filter out special instructions already captured as attribute or modifier selections.

    For example, if "shot" is in attr_result.values, the instruction "extra shot" is
    redundant and should be removed.

    Returns:
        Filtered list of special instructions with duplicates removed.
    """
    # Build set of all selection slugs from attr_result.values and modifiers
    captured_slugs: set[str] = set()
    for attr_key, attr_val in attr_result.values.items():
        if isinstance(attr_val, list):
            # Multi-select: extract slugs from list items
            for item in attr_val:
                if isinstance(item, dict) and item.get("slug"):
                    captured_slugs.add(item["slug"].lower())
        elif isinstance(attr_val, str):
            captured_slugs.add(attr_val.lower())
    for sel in modifier_selections:
        captured_slugs.add(sel.slug.lower())

    # Filter instructions: remove if the item word matches a captured slug
    # "extra shot" -> check if "shot" is captured
    # "light cream cheese" -> check if "cream cheese" is captured
    filtered_instructions = []
    for instr in special_instructions:
        # Extract the item part from instruction (e.g., "extra shot" -> "shot")
        instr_lower = instr.lower()
        item_word = instr_lower
        for prefix in ["extra ", "light ", "no ", "heavy "]:
            if instr_lower.startswith(prefix):
                item_word = instr_lower[len(prefix):].strip()
                break
        # Check if suffix is a position qualifier (e.g., "on the side") and remove
        # These are loaded from the database via modifier_qualifiers table
        for pattern in menu_cache.get_qualifier_patterns():
            qualifier_info = menu_cache.get_qualifier_info(pattern)
            if qualifier_info and qualifier_info.get("category") == "position":
                suffix = f" {pattern}"
                if item_word.endswith(suffix):
                    item_word = item_word[:-len(suffix)].strip()
                    break

        # If item_word is already captured as a selection, skip this instruction
        # Also check suffix match (e.g., "cheese" matches "blueberry_cream_cheese")
        if item_word in captured_slugs or any(s.endswith(f"_{item_word}") for s in captured_slugs):
            logger.debug("Filtering duplicate instruction '%s' - already captured as selection", instr)
            continue
        filtered_instructions.append(instr)
    return filtered_instructions


def _attach_position_qualifiers(parsed_item: ParsedItemEntry, text_lower: str) -> None:
    """Attach position qualifiers (e.g., 'on the side') to matching selections.

    When a user says 'blueberry cream cheese on the side', the qualifier should
    attach to the spread selection rather than creating a separate instruction.

    Mutates parsed_item in place: updates selection display_name and removes
    redundant special instructions.

    Args:
        parsed_item: The parsed item entry to modify
        text_lower: Lowercased original user input text
    """
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    for pattern in qualifier_patterns:
        qualifier_info = menu_cache.get_qualifier_info(pattern)
        if not qualifier_info or qualifier_info.get("category") != "position":
            continue

        # Check if this qualifier appears in the text at all
        if pattern not in text_lower:
            continue

        normalized_form = qualifier_info.get("normalized_form", pattern)

        # For each selection, check if "{slug_as_words} {qualifier}" appears in text
        for sel in parsed_item.selections:
            slug_words = sel.slug.replace("_", " ")
            words = slug_words.split()
            # Try full slug, then progressively shorter suffixes
            # e.g., "whole milk" -> try "whole milk", then "milk"
            matched = False
            for i in range(len(words)):
                suffix = " ".join(words[i:])
                combined = rf'\b{re.escape(suffix)}\s+{re.escape(pattern)}\b'
                if re.search(combined, text_lower):
                    matched = True
                    break
            if not matched:
                continue

            # Match found - attach qualifier to this selection's display_name
            display_name = sel.display_name
            if not display_name:
                display_name = menu_cache.get_global_option_display_name(
                    sel.category, sel.slug
                )
            if not display_name:
                display_name = sel.slug.replace("_", " ").title()

            sel.display_name = f"{display_name} ({normalized_form})"

            # Remove redundant special instructions whose base word is part
            # of the matched slug (e.g., "cheese on the side" where "cheese"
            # is a component of "blueberry_cream_cheese")
            slug_parts = sel.slug.lower().split("_")
            kept = []
            for instr in parsed_item.special_instructions:
                instr_lower = instr.lower()
                if pattern in instr_lower:
                    base_word = instr_lower.replace(pattern, "").strip()
                    if base_word in slug_parts:
                        logger.debug(
                            "Removing redundant instruction '%s' - covered by '%s'",
                            instr, sel.display_name,
                        )
                        continue
                kept.append(instr)
            parsed_item.special_instructions = kept

            logger.debug(
                "Attached qualifier '%s' to selection '%s' -> '%s'",
                normalized_form, sel.slug, sel.display_name,
            )


def _attach_amount_qualifiers(parsed_item: ParsedItemEntry, text_lower: str) -> None:
    """Attach amount qualifiers (e.g., 'extra', 'light') to matching selections.

    When a user says 'coffee with extra milk', the qualifier should attach to the
    milk selection rather than creating a separate instruction. Amount qualifiers
    appear BEFORE the modifier (e.g., "extra milk") unlike position qualifiers
    which appear after ("milk on the side").

    Mutates parsed_item in place: updates selection display_name and removes
    redundant special instructions.

    Args:
        parsed_item: The parsed item entry to modify
        text_lower: Lowercased original user input text
    """
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    for pattern in qualifier_patterns:
        qualifier_info = menu_cache.get_qualifier_info(pattern)
        if not qualifier_info or qualifier_info.get("category") == "position":
            continue  # Only handle non-position (amount) qualifiers

        if pattern not in text_lower:
            continue

        normalized_form = qualifier_info.get("normalized_form", pattern)

        for sel in parsed_item.selections:
            slug_words = sel.slug.replace("_", " ")
            words = slug_words.split()
            matched = False
            for i in range(len(words)):
                suffix = " ".join(words[i:])
                # Amount qualifiers come BEFORE the modifier: "extra milk", "lots of milk"
                # Allow optional filler words between qualifier and modifier
                combined = rf'\b{re.escape(pattern)}\s+(?:\w+\s+)*?{re.escape(suffix)}\b'
                if re.search(combined, text_lower):
                    matched = True
                    break
            if not matched:
                continue

            # Attach qualifier to display_name
            display_name = sel.display_name
            if not display_name:
                display_name = menu_cache.get_global_option_display_name(
                    sel.category, sel.slug
                )
            if not display_name:
                display_name = sel.slug.replace("_", " ").title()

            sel.display_name = f"{display_name} ({normalized_form})"

            # Remove redundant special instructions whose base word is part
            # of the matched slug (e.g., "extra milk" where "milk" is in slug_parts)
            slug_parts = sel.slug.lower().split("_")
            kept = []
            for instr in parsed_item.special_instructions:
                instr_lower = instr.lower()
                if normalized_form in instr_lower or pattern in instr_lower:
                    base_word = instr_lower
                    for prefix in [f"{normalized_form} ", f"{pattern} "]:
                        if base_word.startswith(prefix):
                            base_word = base_word[len(prefix):].strip()
                            break
                    if base_word in slug_parts:
                        logger.debug(
                            "Removing redundant instruction '%s' - covered by '%s'",
                            instr, sel.display_name,
                        )
                        continue
                kept.append(instr)
            parsed_item.special_instructions = kept

            logger.debug(
                "Attached amount qualifier '%s' to selection '%s' -> '%s'",
                normalized_form, sel.slug, sel.display_name,
            )


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

    # Detect unrecognized ingredients (tokens not consumed by attributes or modifiers)
    from .extraction import _detect_unrecognized_ingredients
    modifier_spans = [(text_lower.find(s.slug), text_lower.find(s.slug) + len(s.slug))
                      for s in modifier_selections if text_lower.find(s.slug) != -1]
    all_consumed_spans = list(attr_matched_spans or []) + modifier_spans
    unrecognized_ingredients = _detect_unrecognized_ingredients(text_lower, all_consumed_spans)

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, mods=%s, has_defaults=%s, instructions=%s, unrecognized=%s",
        detected_item_type, quantity, item_name, list(attr_result.values.keys()), [s.slug for s in modifier_selections], has_defaults, special_instructions,
        [u["token"] for u in unrecognized_ingredients] if unrecognized_ingredients else []
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
        unrecognized_ingredients=unrecognized_ingredients,
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
    text_lower = text.lower().strip()

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
        r"^(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
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


# =============================================================================
# Split-Quantity Parsing (delegated to split_quantity_parsing.py)
# =============================================================================

def _parse_split_quantity_items(text: str) -> OpenInputResponse | None:
    """
    Parse orders with multiple configurable items that have different configurations.

    Delegates to split_quantity_parsing module with appropriate function callbacks.

    Detects patterns like:
        - "two plain bagels one with scallion cream cheese one with lox"
        - "2 lattes, one iced, one hot"
        - "three teas one with sugar one with honey one plain"

    Returns:
        OpenInputResponse with parsed_items populated, or None if not a split-quantity order.
    """
    return _parse_split_quantity_items_impl(
        text,
        detect_configurable_item_type_func=_detect_configurable_item_type,
        match_menu_item_name_for_type_func=_match_menu_item_name_for_type,
    )
