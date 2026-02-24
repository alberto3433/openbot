"""
Item Order Parsing Functions.

This module contains the core item parsing logic for generic items,
by-pound items, and split-quantity orders. Configurable item parsing
and qualifier attachment have been extracted to separate modules.

Main entry points:
- _parse_configurable_item() (re-exported from configurable_item_parsing)
- _parse_item_generic()
- _parse_split_quantity_items()

Sub-modules:
- item_type_detection: Item type detection via triggers and option aliases
- menu_item_matching: Menu item name matching and resolution
- configurable_item_parsing: Configurable item parsing entry point and orchestration
- qualifier_attachment: Post-parse qualifier attachment and duplicate filtering
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

# Re-exports from configurable_item_parsing for backward compatibility
from .configurable_item_parsing import (  # noqa: F401
    _should_defer_to_multi_item_parser,
    _try_parse_inline_specs,
    _extract_attributes_with_exclusions,
    _extract_and_build_configurable_item,
    _parse_configurable_item,
)

# Re-exports from qualifier_attachment for backward compatibility
from .qualifier_attachment import (  # noqa: F401
    _filter_duplicate_instructions,
    _attach_position_qualifiers,
    _attach_amount_qualifiers,
    _handle_partial_modifier_split,
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
        else:
            # No specific menu item matched from text — try type default
            # e.g., "early gray tea" with type "tea" → "Hot Tea"
            default_name = _get_default_menu_item_for_type(item_type)
            if default_name:
                item_name = default_name

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
    # (e.g., "bagel" -> bread type), so excluding from attributes would break detection.
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
