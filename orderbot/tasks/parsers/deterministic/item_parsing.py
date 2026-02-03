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
    extract_attribute_values,
    _extract_modifiers_generic,
    _extract_quantity,
    _extract_by_pound_info,
)
from .instructions_extraction import extract_special_instructions_from_input
from ..quantity_utils import extract_quantity_for_pattern

# Import from specialized modules
from .item_building import build_parsed_item
from .split_quantity_parsing import _parse_split_quantity_items as _parse_split_quantity_items_impl

logger = logging.getLogger(__name__)


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
            # Find all occurrences using word boundary matching to prevent
            # partial matches (e.g., "hot" matching inside "shot")
            pattern = rf'\b{re.escape(keyword_lower)}\b'
            for match in re.finditer(pattern, text_lower):
                idx = match.start()
                end_pos = match.end()
                # Check if this match is in the "end region" (last 20% of text or last 15 chars)
                text_len = len(text_lower)
                end_region_start = max(text_len - 15, int(text_len * 0.8))
                is_at_end = end_pos >= end_region_start
                # Prefer item types where the slug matches the trigger
                slug_matches = keyword_lower == item_type_slug or keyword_lower.rstrip("s") == item_type_slug
                matches.append((item_type_slug, keyword, len(keyword_lower), end_pos, is_at_end, slug_matches))

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
    special_instructions = extract_special_instructions_from_input(text)

    return build_parsed_item(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attribute_values=attribute_values,
        modifiers=modifier_selections,
        is_signature=has_defaults,  # Items with defaults need default ingredient population
        original_text=text,
        special_instructions=special_instructions,
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

    # 1a. Check for multi-item patterns that should be handled by _parse_multi_item_order
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
                    logger.debug("CONFIGURABLE_ITEM: skipping multi-item pattern (qty on both sides with item trigger '%s'), delegating to multi-item parser: '%s'", following_word, text[:50])
                    return None

                # Also check if after_and (minus the quantity) is a menu item or item with defaults
                # This handles "one bagel and one classic BEC" where "classic BEC" has default ingredients
                # Strip the leading quantity from after_and to get the item part
                after_and_item_part = re.sub(rf'^{qty_words}\s+', '', after_and, count=1)
                # Late import to avoid circular dependency
                from .tokenization import _has_item_indicator
                has_item, _, _ = _has_item_indicator(after_and_item_part)
                if has_item:
                    logger.debug("CONFIGURABLE_ITEM: skipping multi-item pattern (qty on both sides, right side '%s' is item indicator), delegating to multi-item parser: '%s'", after_and_item_part, text[:50])
                    return None

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
                            "CONFIGURABLE_ITEM: skipping multi-item pattern (trigger '%s' on both sides), "
                            "delegating to multi-item parser: '%s'",
                            trigger, text[:50]
                        )
                        return None

    # 1b. Check for items with default ingredients FIRST - they take precedence over trigger-based detection
    # This prevents "The Classic BEC on a wheat bagel" from matching "bagel" item type
    # due to the "bagel" trigger word. Items with defaults should be detected by their aliases.
    matched_item_name: str | None = None
    matched_item_type: str | None = None
    items_with_defaults_aliases = get_items_with_defaults_aliases()
    # Sort aliases by length (longest first) for most specific match
    sorted_aliases = sorted(items_with_defaults_aliases.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        # Allow optional plural suffix (s, es) to match "classic becs" with alias "classic bec"
        if re.search(rf'\b{re.escape(alias)}(?:e?s)?\b', text_lower):
            matched_item_name = items_with_defaults_aliases[alias]
            # Look up the item type for this item
            matched_item_type = menu_cache.get_item_type_for_menu_item(matched_item_name)
            if matched_item_type:
                logger.info("CONFIGURABLE_ITEM: item with defaults '%s' detected -> type '%s'", matched_item_name, matched_item_type)
                break

    # 2. Detect which configurable item type this text matches
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()
    detected_item_type: str | None = matched_item_type  # Use matched item type if found

    # Only do trigger-based detection if no item with defaults was found
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
            # Sort by: (1) slug_matches (True first), (2) is_at_end (True first), (3) length (longer first)
            # This ensures "bagel" wins over "egg" in "everything bagel with bacon and egg"
            matches.sort(key=lambda x: (not x[5], not x[4], -x[2]))
            detected_item_type = matches[0][0]

    if not detected_item_type:
        return None

    # 2b. Check if the user's text matches more specific menu items
    # e.g., "bagel chips" should NOT trigger configurable bagel flow if there are
    # specific menu items like "Bagel Chips - Salt", "Bagel Chips - BBQ", etc.
    more_specific_matches = menu_cache.find_items_by_word_match(text_lower)
    if more_specific_matches:
        # Check if ANY of the specific matches are from a DIFFERENT item type than detected
        # This indicates the user likely wants a specific menu item, not a configurable one
        specific_item_types = {m.get("item_type") for m in more_specific_matches if m.get("item_type")}
        if specific_item_types and detected_item_type not in specific_item_types:
            logger.info(
                "CONFIGURABLE_ITEM: skipping '%s' - found %d more specific menu items with types %s (detected: %s)",
                text[:50], len(more_specific_matches), specific_item_types, detected_item_type
            )
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
    # If we already found an item with defaults, use that name; otherwise try to match
    item_name = matched_item_name or _match_menu_item_name_for_type(text, detected_item_type)

    # Check if this item has default ingredients (used for populating defaults)
    has_defaults = False
    if item_name:
        items_with_defaults = get_items_with_defaults_aliases()
        name_lower = item_name.lower()
        if name_lower in items_with_defaults or item_name in items_with_defaults.values():
            has_defaults = True

    # 5b. Extract item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions = extract_special_instructions_from_input(text)

    # 5c. Extract food modifiers (proteins, spreads, toppings, etc.)
    # These are ingredients not handled via attribute_values (which handles items that
    # overlap with attribute options like bread types, egg styles, etc.)
    food_modifiers = _extract_modifiers_generic(text_lower, detected_item_type)
    modifier_selections: list[Selection] = []
    for mod in food_modifiers:
        category = menu_cache.get_ingredient_category(mod)
        quantity = extract_quantity_for_pattern(text_lower, mod)
        modifier_selections.append(Selection(
            slug=mod, category=category, quantity=quantity
        ))

    # 5d. Filter out special instructions that are already captured as selections
    # e.g., if "shot" is in attr_values, don't keep "extra shot" as an instruction
    # Build set of all selection slugs from attribute_values and modifiers
    captured_slugs: set[str] = set()
    for attr_key, attr_val in attr_values.items():
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
        # Check if suffix like " on the side" and remove
        for suffix in [" on the side"]:
            if item_word.endswith(suffix):
                item_word = item_word[:-len(suffix)].strip()

        # If item_word is already captured as a selection, skip this instruction
        if item_word in captured_slugs:
            logger.debug("Filtering duplicate instruction '%s' - already captured as selection", instr)
            continue
        filtered_instructions.append(instr)
    special_instructions = filtered_instructions

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, mods=%s, has_defaults=%s, instructions=%s",
        detected_item_type, quantity, item_name, list(attr_values.keys()), [s.slug for s in modifier_selections], has_defaults, special_instructions
    )

    # 6. Build ParsedItemEntry using build_parsed_item (converts attr_values to selections)
    # Create single entry with full quantity - ItemAdderHandler handles threshold logic
    parsed_item = build_parsed_item(
        item_type=detected_item_type,
        item_name=item_name,
        quantity=quantity,
        attribute_values=attr_values.copy(),
        modifiers=modifier_selections,
        original_text=text,
        is_signature=has_defaults,  # Items with defaults need default ingredient population
        special_instructions=special_instructions,
    )

    return OpenInputResponse(parsed_items=[parsed_item])


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
