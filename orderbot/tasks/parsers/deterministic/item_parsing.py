"""
Item Order Parsing Functions.

This module contains the core item parsing logic for configurable items.
Specialized parsers for sodas, by-pound items, and split-quantity orders
are in separate modules.

Main entry point: _parse_configurable_item()
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

logger = logging.getLogger(__name__)


def _get_pipeline():
    """Get the shared extraction pipeline (lazy import to avoid circular dependency)."""
    from .pipeline import get_pipeline
    return get_pipeline()


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
# Shared Trigger Matching
# =============================================================================

# Common words that should not be treated as item triggers.
# Shared by _detect_item_type, _detect_configurable_item_type, and _has_item_indicator.
_SKIP_TRIGGER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
}


def _find_trigger_matches(
    text: str,
    *,
    configurable_only: bool = False,
    allow_plural: bool = False,
) -> list[tuple[str, str, re.Match]]:
    """Find item type trigger matches in text using word-boundary regex.

    Core matching logic shared by all item type detection functions.
    Iterates triggers from menu_cache, skips common words, applies
    word-boundary matching.

    Args:
        text: Lowercased user input text
        configurable_only: Only check configurable item types
        allow_plural: Also match trigger + trailing 's'

    Returns:
        List of (item_type_slug, trigger_keyword, regex_match) tuples.
        Caller is responsible for filtering, enrichment, and sorting.
    """
    all_triggers = menu_cache.get_item_type_triggers()
    if configurable_only:
        configurable_slugs = menu_cache.get_configurable_item_type_slugs()
        all_triggers = {k: v for k, v in all_triggers.items() if k in configurable_slugs}

    results: list[tuple[str, str, re.Match]] = []
    for item_type_slug, triggers in all_triggers.items():
        for keyword in triggers:
            if keyword.lower() in _SKIP_TRIGGER_WORDS:
                continue
            keyword_lower = keyword.lower()
            suffix = r's?' if allow_plural else r''
            pattern = rf'\b{re.escape(keyword_lower)}{suffix}\b'
            for match in re.finditer(pattern, text):
                results.append((item_type_slug, keyword, match))
    return results


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
    raw_matches = _find_trigger_matches(text_lower)

    # Enrich with position-based metadata and filter negated triggers
    # Format: (item_type, keyword, match_length, end_position, is_at_end_region, slug_matches)
    matches: list[tuple[str, str, int, int, bool, bool]] = []

    for item_type_slug, keyword, match in raw_matches:
        idx = match.start()
        end_pos = match.end()
        keyword_lower = keyword.lower()
        # Skip triggers preceded by negation words ("no", "without", "skip", "not")
        if idx > 0:
            text_before = text_lower[:idx].rstrip()
            if text_before:
                last_word = text_before.split()[-1] if text_before.split() else ""
                if last_word in {"no", "without", "skip", "not"}:
                    continue
        # Check if this match is in the "end region" (last 20% of text or last 15 chars)
        text_len = len(text_lower)
        end_region_start = max(text_len - 15, int(text_len * 0.8))
        is_at_end = end_pos >= end_region_start
        slug_matches = keyword_lower == item_type_slug or keyword_lower.rstrip("s") == item_type_slug
        matches.append((item_type_slug, keyword, len(keyword_lower), end_pos, is_at_end, slug_matches))

    if not matches:
        return None, None

    # Sort by: (1) is_at_end_region (True first), (2) slug_matches (True first), (3) match_length (longer first)
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

    # Strip leading quantity (number or word) - it's likely a modifier phrase
    # "2 sugars" -> "sugars", "two sugars" -> "sugars"
    quantity_pattern = r'^(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+'
    after_and_stripped = re.sub(quantity_pattern, '', after_and, flags=re.IGNORECASE)

    # Check if the stripped text (without quantity) matches an item keyword
    item_type, _ = _detect_item_type(after_and_stripped)
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
                       selections=[Selection(slug="large", category="size"), ...])
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

    # Extract all attributes for this item type using database config
    # This handles all attribute types (single_select, multi_select, boolean)
    # including combined attributes like milk_sweetener_syrup
    # Pass item_qty_span as exclude_span to prevent the item quantity word
    # (e.g., "two" in "two large iced lattes") from being re-consumed as
    # an attribute-level quantity (which would make size="2 Larges" instead of "Large")
    from .result_types import TextSpan
    exclude_spans_for_attrs = None
    if item_qty_span:
        exclude_spans_for_attrs = [TextSpan(start=item_qty_span[0], end=item_qty_span[1])]
    attr_result = _get_pipeline().extract_attributes(text, item_type, exclude_spans=exclude_spans_for_attrs)
    attr_matched_spans = [(s.start, s.end) for s in attr_result.matched_spans]

    # Extract food modifiers (proteins, spreads, toppings, etc.)
    # Beverage modifiers (sweeteners, syrups, milk) are handled via attr_result
    # Pass exclude_spans to avoid double-extraction of text already matched as attributes
    food_modifiers = _get_pipeline().extract_modifiers_raw(text_lower, item_type, exclude_spans=attr_matched_spans)

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
        quantity = extract_quantity_for_pattern(text_lower, mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=quantity
        ))

    # Extract item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions = _get_pipeline().extract_special_instructions(text).instructions

    return build_parsed_item(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attr_result=attr_result,
        modifiers=modifier_selections,
        is_signature=has_defaults,  # Items with defaults need default ingredient population
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
                # get_item_type_triggers() returns dict[slug -> set[triggers]], flatten to set
                all_triggers_dict = menu_cache.get_item_type_triggers()
                all_triggers: set[str] = set()
                for trigger_set in all_triggers_dict.values():
                    all_triggers.update(t.lower() for t in trigger_set)
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


def _resolve_item_type_and_menu_item(
    text: str,
    text_lower: str,
    text_cleaned: str,
) -> tuple[str, str | None, tuple[int, int] | None, dict] | None:
    """Resolve the item type and optional menu item from user text.

    Checks (in order):
    1. Items with default ingredients (e.g., "The Classic BEC") - by alias matching
    2. Trigger-based item type detection (e.g., "bagel", "coffee", "latte")
    3. Option alias fallback (e.g., "earl grey" -> tea with tea_flavor=earl_gray)
    4. More-specific menu item checks to avoid false positives

    Args:
        text: Original user input text
        text_lower: Lowercased user input text
        text_cleaned: Lowercased text with ordering phrases stripped

    Returns:
        (detected_item_type, matched_item_name, matched_item_span, inferred_attr_values)
        or None if no configurable item type was detected
    """
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()

    # 1b. Check for items with default ingredients FIRST - they take precedence over trigger-based detection
    # This prevents "The Classic BEC on a wheat bagel" from matching "bagel" item type
    # due to the "bagel" trigger word. Items with defaults should be detected by their aliases.
    matched_item_name: str | None = None
    matched_item_type: str | None = None
    matched_item_span: tuple[int, int] | None = None  # Track span to exclude from attribute extraction
    items_with_defaults_aliases = get_items_with_defaults_aliases()
    # Sort aliases by length (longest first) for most specific match
    sorted_aliases = sorted(items_with_defaults_aliases.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        # Allow optional plural suffix (s, es) to match "classic becs" with alias "classic bec"
        match = re.search(rf'\b{re.escape(alias)}(?:e?s)?\b', text_lower)
        if match:
            matched_item_name = items_with_defaults_aliases[alias]
            matched_item_span = (match.start(), match.end())
            # Look up the item type for this item
            matched_item_type = menu_cache.get_item_type_for_menu_item(matched_item_name)
            if matched_item_type:
                logger.info("CONFIGURABLE_ITEM: item with defaults '%s' detected -> type '%s'", matched_item_name, matched_item_type)
                break

    # 2. Detect which configurable item type this text matches
    detected_item_type: str | None = matched_item_type  # Use matched item type if found

    # Only do trigger-based detection if no item with defaults was found
    if not detected_item_type:
        # Find position of " with " to detect modifier patterns
        # In "everything bagel with cream cheese", triggers after "with" are modifiers, not main items
        with_pos = text_lower.find(" with ")

        # Get all known modifier phrases (including multi-word ones like "cream cheese")
        # Used to skip triggers that are part of a larger modifier phrase
        all_modifiers = menu_cache.get_all_modifier_words()

        # Collect all matches with position info for smarter selection
        # Format: (item_type, trigger, length, start_pos, is_before_with, slug_matches)
        matches: list[tuple[str, str, int, int, bool, bool]] = []

        for item_type_slug in configurable_slugs:
            triggers = menu_cache.get_item_type_triggers(item_type_slug)
            for trigger in triggers:
                # Skip common words that appear as triggers from menu item names
                if trigger.lower() in _SKIP_TRIGGER_WORDS:
                    continue
                # Check for word boundary match
                pattern = rf'\b{re.escape(trigger)}s?\b'
                match = re.search(pattern, text_lower)
                if match:
                    start_pos = match.start()
                    end_pos = match.end()
                    trigger_lower = trigger.lower()

                    # Skip triggers preceded by negation words ("no", "without", "skip", "not")
                    # "no spread" is a modifier negation, not an item type reference
                    if start_pos > 0:
                        text_before = text_lower[:start_pos].rstrip()
                        if text_before:
                            last_word = text_before.split()[-1] if text_before.split() else ""
                            if last_word in {"no", "without", "skip", "not"}:
                                continue

                    # Skip if this trigger is part of a known compound modifier phrase
                    # that belongs to an UNRELATED category
                    # e.g., "cream cheese" is a "spread" - skip for "cheese" item type
                    # But "plain bagel" is "bread" - don't skip for "bagel" because bread
                    # is an attribute of the bagel item type
                    is_part_of_modifier = False
                    if start_pos > 0:
                        # Get the word immediately before this trigger
                        text_before = text_lower[:start_pos].rstrip()
                        if text_before:
                            words_before = text_before.split()
                            if words_before:
                                prev_word = words_before[-1]
                                compound = f"{prev_word} {trigger_lower}"
                                # Check if this compound is a known modifier
                                if compound in all_modifiers:
                                    # Check what category this modifier belongs to
                                    compound_category = menu_cache.get_ingredient_category(compound)
                                    if compound_category:
                                        # Get attributes for this item type
                                        item_attrs = menu_cache.get_item_type_attributes(item_type_slug)
                                        # Skip if the compound's category is NOT an attribute of this item type
                                        # e.g., "spread" is not an attribute of "cheese" item type
                                        # But "bread" IS an attribute of "bagel" item type
                                        if compound_category not in item_attrs:
                                            is_part_of_modifier = True
                    if is_part_of_modifier:
                        continue

                    # Triggers BEFORE "with" are main items; triggers AFTER are modifiers
                    # If no "with" in text, all triggers are considered main items
                    is_before_with = with_pos == -1 or start_pos < with_pos
                    # Prefer item types where slug matches trigger
                    slug_matches = trigger.lower() == item_type_slug or trigger.lower().rstrip("s") == item_type_slug
                    matches.append((item_type_slug, trigger, len(trigger), start_pos, is_before_with, slug_matches))

        if matches:
            # Sort by:
            # (1) is_before_with (True first) - triggers before "with" are main items
            # (2) slug_matches (True first) - prefer when trigger matches item type slug
            # (3) length (LONGER first) - prefer specific item names over short adjectives
            # (4) start_pos (LATER first) - among equal-length triggers, prefer nouns at end
            # This ensures:
            # - "bagel" wins over "cheese" in "everything bagel with cream cheese" (via rule 1)
            # - "latte" wins over "hot" in "hot latte please" (via rule 3/4)
            # - "coffee" wins over "iced" in "large coffee iced" (via rule 3)
            matches.sort(key=lambda x: (not x[4], not x[5], -x[2], -x[3]))
            detected_item_type = matches[0][0]

    if not detected_item_type:
        # Fallback: check if input matches an attribute option alias
        # This handles "earl grey" -> tea with tea_flavor=earl_gray
        cleaned_input = text_lower.strip()
        option_match = menu_cache.get_item_type_from_option_alias(cleaned_input)
        if option_match:
            detected_item_type, inferred_attr_slug, inferred_option_slug = option_match
            logger.info(
                "CONFIGURABLE_ITEM: inferred type '%s' from option alias '%s' (%s=%s)",
                detected_item_type, cleaned_input, inferred_attr_slug, inferred_option_slug
            )
            # Pre-fill the attribute value - will be merged with extracted values later
            # Store in a variable to merge after attr_values is populated
            inferred_attr_values = {inferred_attr_slug: inferred_option_slug}
        else:
            return None
    else:
        inferred_attr_values = {}

    # 2b. Check if the user's text matches more specific menu items
    # e.g., "bagel chips" should NOT trigger configurable bagel flow if there are
    # specific menu items like "Bagel Chips - Salt", "Bagel Chips - BBQ", etc.
    # Use text_cleaned (ordering phrases stripped) for more accurate matching
    more_specific_matches = menu_cache.find_items_by_word_match(text_cleaned)

    # Also check if any complete menu item name (from a different type) appears as a
    # phrase in the user's input. This catches cases like "hot chai tea" where "chai tea"
    # is a complete menu item (type: chai_drink) but the trigger word "tea" detected
    # the "tea" type. We want to defer to the more specific match.
    # BUT: Skip this check if the menu item name is also an attribute option for the
    # detected item type (e.g., "bagel" in "ham egg and cheese bagel" is the bread choice,
    # not a reference to a standalone bagel item).
    text_cleaned_lower = text_cleaned.lower()
    detected_type_attr_options = menu_cache.get_all_attribute_option_slugs_for_item_type(detected_item_type)

    def is_attribute_option_word(word: str) -> bool:
        """Check if a word appears in any attribute option for the detected type."""
        word_lower = word.lower()
        for opt in detected_type_attr_options:
            # Check if word is the option or appears as a word within the option
            if word_lower == opt or word_lower in opt.split('_') or word_lower in opt.split():
                return True
        return False

    # Find " with " position to detect modifier patterns
    # In "everything bagel with scallion cream cheese", items after "with" are modifiers
    with_pos_for_menu_check = text_cleaned_lower.find(" with ")

    for item_name, item_info in menu_cache._menu_items.items():
        item_type = item_info.get("item_type")
        if item_type and item_type != detected_item_type:
            item_name_lower = item_name.lower()
            # Skip if this menu item name is also an attribute option for the detected type
            # (e.g., "bagel" as a bread option for egg_sandwich - options are "plain_bagel", etc.)
            if is_attribute_option_word(item_name_lower):
                continue
            # Check if this menu item name appears as a word-boundary phrase in input
            match = re.search(rf'\b{re.escape(item_name_lower)}\b', text_cleaned_lower)
            if match:
                # Skip if this menu item appears AFTER "with" - it's likely a modifier on the main item
                # e.g., "everything bagel with scallion cream cheese" - cream cheese is a modifier
                if with_pos_for_menu_check != -1 and match.start() > with_pos_for_menu_check:
                    continue
                # Found a complete menu item of a different type - use its type instead
                # e.g., "large iced tea" detected type "tea" but "iced tea" is type "iced_tea"
                # Switch to the correct type so configurable item parsing continues
                if item_type in configurable_slugs:
                    logger.info(
                        "CONFIGURABLE_ITEM: switching type '%s' -> '%s' based on menu item '%s' in '%s'",
                        detected_item_type, item_type, item_name, text[:50]
                    )
                    detected_item_type = item_type
                    break
                else:
                    # Non-configurable item - defer to menu item lookup
                    logger.info(
                        "CONFIGURABLE_ITEM: skipping '%s' - found non-configurable menu item '%s' of type '%s'",
                        text[:50], item_name, item_type
                    )
                    return None

    if more_specific_matches:
        # Check if user's input has extra specificity beyond the item type word
        # e.g., "bagel package" has "package" beyond "bagel", and if "package" appears
        # in matching menu items like "3 Bagel Package", defer to menu item lookup
        filler_words = {
            'a', 'an', 'the', 'i', 'id', 'want', 'like', 'get', 'can', 'have', 'need',
            'please', 'would', 'could', 'some', 'of', 'with', 'and', 'or', 'for', 'me',
        }
        input_words = set(re.findall(r'\b[a-z]+\b', text_lower))
        # Include both the item type slug words AND the SHORT trigger words that detected this type
        # e.g., for "coffee", type_words should include "coffee" (the trigger), not just "sized"/"beverage"
        # But we only include triggers with 2 or fewer words - longer ones are menu item names
        # (e.g., "3 bagel package" is a menu item, not a type trigger)
        type_words = set(re.findall(r'\b[a-z]+\b', detected_item_type.lower()))
        # Add short trigger words for this item type (e.g., "coffee", "latte", "iced coffee")
        triggers = menu_cache.get_item_type_triggers().get(detected_item_type, [])
        for trigger in triggers:
            trigger_word_count = len(trigger.split())
            if trigger_word_count <= 2:  # Only short triggers (like "coffee", "iced coffee")
                type_words.update(re.findall(r'\b[a-z]+\b', trigger.lower()))
        extra_words = input_words - type_words - filler_words

        if extra_words:
            # Check if any matching menu item name contains these extra words
            for match in more_specific_matches:
                match_name_lower = match.get("name", "").lower()
                matching_extra = [w for w in extra_words if w in match_name_lower]
                if matching_extra:
                    logger.info(
                        "CONFIGURABLE_ITEM: skipping '%s' - extra words %s found in menu item '%s'",
                        text[:50], matching_extra, match.get("name")
                    )
                    return None

    return (detected_item_type, matched_item_name, matched_item_span, inferred_attr_values)


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
                            is_signature=False,
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
                            is_signature=False,
                        )
                        parsed_items.append(unspecified_entry)

                    logger.info(
                        "INLINE_SPEC: Created %d items from inline specs: %s",
                        len(parsed_items),
                        [(p.quantity, list(s.slug for s in p.selections)) for p in parsed_items]
                    )
                    return OpenInputResponse(parsed_items=parsed_items)

    return None


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

    Handles:
    - Menu item name matching (if not already matched)
    - Attribute extraction via pipeline
    - Inferred attribute merging
    - Unrecognized item text guard
    - Default menu item fallback
    - Partial modifier split detection
    - Food modifier extraction
    - Special instruction extraction and filtering
    - Final ParsedItemEntry building

    Args:
        text: Original user input text
        text_lower: Lowercased user input text
        detected_item_type: The detected item type slug
        matched_item_name: The matched menu item name (if any)
        matched_item_span: The span of the matched item name in text_lower (if any)
        inferred_attr_values: Pre-filled attribute values from option alias fallback
        quantity: The extracted quantity

    Returns:
        OpenInputResponse with parsed_items, or None if unrecognized item text detected
    """
    # 2e. Early menu item name matching
    # This finds the specific menu item within the item type (e.g., "Hot Coffee" for coffee).
    # NOTE: We do NOT use the span from this match for exclusion because menu item NAMES
    # like "Bagel" are short and don't contain modifier words. The span exclusion is only
    # needed for ALIASES matched in step 1b (e.g., "ham egg and cheese" contains "cheese"
    # which shouldn't trigger cheese attribute matching).
    if not matched_item_name:
        matched_item_name = _match_menu_item_name_for_type(text, detected_item_type)

    # 4. Extract attribute values using data-driven extraction
    # This returns all attributes as {slug: value} where value can be:
    # - string for single_select
    # - list[{slug, quantity, ...}] for multi_select
    # - bool for boolean
    # Also returns matched_spans to pass to modifier extraction to avoid double-extraction
    #
    # Build exclude_spans from the matched menu item name to prevent attribute extraction
    # from matching words within the menu item name. E.g., "ham egg and cheese bagel with
    # pepper" - the word "cheese" is part of the menu item name "Ham Egg and Cheese Sandwich",
    # not a request for a specific cheese type.
    from .result_types import TextSpan
    exclude_spans_for_attrs: list[TextSpan] = []
    if matched_item_span:
        exclude_spans_for_attrs.append(TextSpan(start=matched_item_span[0], end=matched_item_span[1]))
    if item_qty_span:
        exclude_spans_for_attrs.append(TextSpan(start=item_qty_span[0], end=item_qty_span[1]))

    attr_result = _get_pipeline().extract_attributes(text, detected_item_type, exclude_spans=exclude_spans_for_attrs if exclude_spans_for_attrs else None)
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

    # 5. Use the menu item name found earlier (from step 1b or 2c)
    # matched_item_name was already set by:
    # - Step 1b: items_with_defaults_aliases matching
    # - Step 2c: early menu item name matching via _match_menu_item_name_for_type_with_span
    item_name = matched_item_name

    # 5a. Guard against creating generic items from partial trigger matches
    # If we detected an item type but no specific menu item matched,
    # check if there's unrecognized text that could be a missing menu item.
    # E.g., "iced mocha" - "iced" triggers coffee_based_beverage but "mocha" is unrecognized.
    # E.g., "large iced mocha" - "large" extracts size, "iced" triggers, but "mocha" is unrecognized.
    # We check this BEFORE assigning a default, so unrecognized items get proper error handling.
    if not item_name:
        if _has_unrecognized_item_text(text, detected_item_type):
            logger.info(
                "CONFIGURABLE_ITEM: rejecting generic parse - unrecognized text in '%s' for type '%s'",
                text[:50], detected_item_type
            )
            return None

    # 5b. If no specific menu item matched (and no unrecognized text), try to pick a default
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

    # 5b. Extract item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions = _get_pipeline().extract_special_instructions(text).instructions

    # 5b-split. Check for partial-modifier split (e.g., "4 coffees 2 with milk")
    # This handles cases like "4 large hot coffees 2 with milk and sugar" -> 2 with modifiers, 2 plain
    if quantity > 1 and item_name:
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
        if item_name_match:
            text_after_item = text_lower[item_name_match.end():]
            split_result = _detect_partial_modifier_split(text_after_item, quantity)

            if split_result:
                split_qty, modifier_text = split_result
                remaining_qty = quantity - split_qty

                logger.info(
                    "PARTIAL_SPLIT: detected %d with '%s', %d unmodified",
                    split_qty, modifier_text, remaining_qty
                )

                # Extract BASE attributes from text BEFORE the split point
                # e.g., "4 large hot coffees 2 with milk" -> base text is "4 large hot coffees"
                text_before_split = text_lower[:item_name_match.end()]
                base_attr_result = _get_pipeline().extract_attributes(text_before_split, detected_item_type)

                # Also extract any attribute values from modifier text
                split_attr_result = _get_pipeline().extract_attributes(modifier_text, detected_item_type)
                split_matched_spans = [(s.start, s.end) for s in split_attr_result.matched_spans]

                # Extract modifiers from "with X" portion only
                # Pass exclude_spans to avoid double-extraction of attributes
                split_modifiers = _get_pipeline().extract_modifiers_raw(modifier_text, detected_item_type, exclude_spans=split_matched_spans)
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
                    is_signature=has_defaults,
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
                    is_signature=has_defaults,
                    special_instructions=[],
                )

                return OpenInputResponse(parsed_items=[items_with_mods, items_plain])

    # 5c. Extract food modifiers (proteins, spreads, toppings, etc.)
    # These are ingredients not handled via attribute_values (which handles items that
    # overlap with attribute options like bread types, egg styles, etc.)
    # Pass exclude_spans to avoid double-extraction of text already matched as attributes
    food_modifiers = _get_pipeline().extract_modifiers_raw(text_lower, detected_item_type, exclude_spans=attr_matched_spans)
    modifier_selections: list[Selection] = []
    for mod in food_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        quantity = extract_quantity_for_pattern(text_lower, mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=quantity
        ))

    # 5d. Filter out special instructions that are already captured as selections
    # e.g., if "shot" is in attr_result.values, don't keep "extra shot" as an instruction
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
        if item_word in captured_slugs:
            logger.debug("Filtering duplicate instruction '%s' - already captured as selection", instr)
            continue
        filtered_instructions.append(instr)
    special_instructions = filtered_instructions

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, mods=%s, has_defaults=%s, instructions=%s",
        detected_item_type, quantity, item_name, list(attr_result.values.keys()), [s.slug for s in modifier_selections], has_defaults, special_instructions
    )

    # 6. Build ParsedItemEntry using build_parsed_item (converts attr_result to selections)
    # Create single entry with full quantity - ItemAdderHandler handles threshold logic
    parsed_item = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=quantity,
        attr_result=attr_result,
        modifiers=modifier_selections,
        original_text=text,
        is_signature=has_defaults,  # Items with defaults need default ingredient population
        special_instructions=special_instructions,
    )

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
    # This is a cleaned version for menu item matching - original text_lower is still used
    # for other matching that might need the full context
    # Note: "i like" is NOT stripped - it's a statement, not an ordering phrase
    text_cleaned = re.sub(
        r'^(i\s+want\s+|i\s+would\s+like\s+|i\'?d\s+like\s+|i\'?ll\s+have\s+|i\s+will\s+have\s+|'
        r'can\s+i\s+(get|have)\s+|give\s+me\s+|let\s+me\s+(get|have)\s+|add\s+)',
        '', text_lower
    )
    text_cleaned = re.sub(r'^(a|an|the)\s+', '', text_cleaned)

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
        r")?\s*"
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
            item_names = menu_cache.get_item_names_by_type(detected_item_type)
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


def _has_unrecognized_item_text(text: str, item_type_slug: str) -> bool:
    """Check if text contains words that look like an unrecognized menu item.

    Used to detect cases like "iced mocha" where "iced" triggers espresso_based_beverage
    but "mocha" is not a recognized item. In such cases, we should reject the
    generic parse and let the unrecognized item handler provide better suggestions.

    Args:
        text: User input text
        item_type_slug: The detected item type

    Returns:
        True if there are unrecognized words that could be a missing menu item
    """
    text_lower = text.lower()

    # Check for multi-word option aliases (e.g., "earl grey", "oat milk")
    # If the text contains such an alias, extract the words covered by it
    option_aliases = menu_cache.get_all_option_aliases()
    words_in_option_aliases: set[str] = set()
    text_stripped = text_lower.strip()

    # If the entire text matches an option alias, it's fully recognized
    if text_stripped in option_aliases:
        return False

    # Check for multi-word aliases contained within the text
    for alias in option_aliases:
        if " " in alias and alias in text_stripped:
            # This multi-word alias is found in the text
            # Mark all its words as recognized
            words_in_option_aliases.update(alias.split())

    # Words that are common ordering phrases (not potential item names)
    # NOTE: Domain-specific words (sizes, temperatures, cooking terms) are loaded
    # from the database via all_attr_options below - do NOT hardcode them here.
    common_ordering_words = {
        # Articles/prepositions
        "a", "an", "the", "some", "with", "and", "or", "on", "in", "of", "to", "for",
        # Ordering verbs/phrases
        "i", "want", "would", "like", "need", "get", "have", "take", "give", "me",
        "can", "could", "may", "please", "order", "add", "make", "it", "that",
        # Numbers
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        # Generic quantity/intensity words (not food-specific)
        "extra", "half", "double", "triple", "regular",
        "little", "bit", "touch", "splash", "dash", "drop",
        "just", "only", "light", "lightly",
        # Generic negation/exclusion words
        "no", "without", "hold",
    }

    # Get recognized vocabulary for this item type
    triggers = menu_cache.get_item_type_triggers(item_type_slug)
    triggers_lower = {t.lower() for t in triggers}

    # Also get known modifiers and attribute options (data-driven)
    all_modifiers = menu_cache.get_all_modifier_words()
    all_attr_options = menu_cache.get_all_attribute_option_words()

    # Extract words from text
    words = re.findall(r'\b[a-z]+\b', text_lower)

    # Check if any words are unrecognized (not common words, not triggers, not modifiers)
    for word in words:
        if word in common_ordering_words:
            continue
        if word in triggers_lower:
            continue
        # Check if word is part of a multi-word trigger (e.g., "cream" in "cream cheese")
        if any(word in trigger for trigger in triggers_lower):
            continue
        # Check if word is a known modifier or attribute option
        if word in all_modifiers or word in all_attr_options:
            continue
        # Check if word is part of a multi-word attribute option
        # (e.g., "milk" appears in "whole milk", "oat milk", etc.)
        if any(' ' in opt and re.search(rf'\b{re.escape(word)}\b', opt) for opt in all_attr_options):
            continue
        # Check if word is part of a multi-word modifier
        # (e.g., "cheese" in "cream cheese")
        if any(' ' in mod and re.search(rf'\b{re.escape(word)}\b', mod) for mod in all_modifiers):
            continue
        # Check if word is part of a multi-word option alias found in the text
        if word in words_in_option_aliases:
            continue
        # This word is unrecognized - could be a missing menu item like "mocha"
        logger.debug(
            "Unrecognized word '%s' in text '%s' for type '%s'",
            word, text[:50], item_type_slug
        )
        return True

    return False


def _get_default_menu_item_for_type(item_type_slug: str) -> str | None:
    """Get a default menu item name for an item type when no specific match is found.

    Used when a user orders generically (e.g., "tea with milk") without specifying
    which specific menu item they want (e.g., "Hot Tea" vs "Green Tea").

    The default is selected by:
    1. Looking for item name ending with the type (e.g., "Chai Tea" for "tea")
    2. Falling back to the first item alphabetically

    Args:
        item_type_slug: The item type slug

    Returns:
        The default menu item name, or None if no items exist for this type
    """
    item_names = list(menu_cache.get_item_names_by_type(item_type_slug))
    if not item_names:
        return None

    if len(item_names) == 1:
        return item_names[0].title()

    # Look for item name ending with the type slug word
    type_display = item_type_slug.replace('_', ' ')
    for name in item_names:
        if name.lower().endswith(type_display):
            return name.title()

    # Fallback: return first item (sorted alphabetically for consistency)
    return sorted(item_names)[0].title()


def _match_menu_item_name_for_type_with_span(
    text: str,
    item_type_slug: str
) -> tuple[str | None, tuple[int, int] | None]:
    """
    Try to match a specific menu item name within an item type, returning the span.

    For example, for sized_beverage, this would try to match "Iced Latte",
    "Hot Coffee", "Chai Tea", etc.

    Args:
        text: User input text
        item_type_slug: The item type slug to search within

    Returns:
        Tuple of (canonical_name, (start, end)) if found, (None, None) otherwise
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
        match = re.search(pattern, text_lower)
        if match:
            # Return canonical name and span
            canonical_name = alias_to_canonical.get(name, name.title())
            return canonical_name, (match.start(), match.end())

    return None, None


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
    name, _ = _match_menu_item_name_for_type_with_span(text, item_type_slug)
    return name


def _detect_configurable_item_type(text: str) -> tuple[str | None, str | None]:
    """
    Detect configurable item type from text using database-driven keywords.

    Uses smart matching to prefer:
    1. Triggers that are menu item names/aliases (more specific matches)
    2. Triggers that match the item type slug
    3. Triggers that appear at the start of the text
    4. Longer triggers (as tiebreaker)

    Args:
        text: User input text (lowercase)

    Returns:
        (item_type_slug, matched_trigger) or (None, None) if no match
    """
    text_lower = text.lower()
    raw_matches = _find_trigger_matches(text_lower, configurable_only=True, allow_plural=True)

    # Deduplicate to first match per (item_type, trigger) pair — _find_trigger_matches
    # uses finditer so may return multiple positions, but this function only needs the first
    seen: set[tuple[str, str]] = set()

    # Enrich with configurable-item-specific metadata
    # Format: (item_type, trigger, length, start_pos, slug_matches, is_complete_item_name)
    matches: list[tuple[str, str, int, int, bool, bool]] = []

    for item_type_slug, keyword, match in raw_matches:
        key = (item_type_slug, keyword.lower())
        if key in seen:
            continue
        seen.add(key)
        start_pos = match.start()
        trigger_lower = keyword.lower()
        slug_matches = trigger_lower == item_type_slug or trigger_lower.rstrip("s") == item_type_slug
        item_names = menu_cache.get_item_names_by_type(item_type_slug)
        is_complete_item_name = trigger_lower in item_names
        matches.append((item_type_slug, keyword, len(keyword), start_pos, slug_matches, is_complete_item_name))

    if not matches:
        return None, None

    # Sort by:
    # (1) is_complete_item_name (True first) - complete item names are most specific
    # (2) For complete item names: prefer earlier position, then longer
    # (3) For partial triggers: prefer slug_matches, then earlier position, then longer
    def sort_key(x):
        item_type, trigger, length, start_pos, slug_matches, is_complete_item_name = x
        if is_complete_item_name:
            return (0, start_pos, -length)
        else:
            return (1, not slug_matches, start_pos, -length)
    matches.sort(key=sort_key)
    return matches[0][0], matches[0][1]


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
