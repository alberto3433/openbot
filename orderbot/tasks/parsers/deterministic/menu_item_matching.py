"""
Menu Item Matching Functions.

This module contains functions for matching user input text to specific menu items,
resolving item types combined with menu item names, and handling default/fallback
menu item selection.

Functions:
- _match_item_with_defaults: Match text against items with default ingredients
- _check_more_specific_menu_items: Check if text matches more specific menu items
- _resolve_item_type_and_menu_item: Full resolution pipeline for item type + menu item
- _has_unrecognized_item_text: Check for unrecognized words in item text
- _get_default_menu_item_for_type: Get default menu item for an item type
- _match_menu_item_name_for_type_with_span: Match menu item name with text span
- _match_menu_item_name_for_type: Match menu item name (without span)
"""

import re
import logging

from orderbot.cache import menu_cache

from ..constants import get_items_with_defaults_aliases
from .item_type_detection import (
    _detect_type_by_triggers,
    _try_option_alias_fallback,
)

logger = logging.getLogger(__name__)


def _search_aliases_in_text(
    text: str,
    sorted_aliases: list[str],
    alias_map: dict[str, str],
) -> tuple[str, str, tuple[int, int]] | None:
    """Search for item-with-defaults aliases in text, return first match.

    Args:
        text: Text to search within (lowercased).
        sorted_aliases: Alias strings sorted by length (longest first).
        alias_map: Mapping from alias to canonical menu item name.

    Returns:
        (item_type, item_name, span) if found, None otherwise.
    """
    for alias in sorted_aliases:
        match = re.search(rf'\b{re.escape(alias)}(?:e?s)?\b', text)
        if match:
            matched_item_name = alias_map[alias]
            matched_item_type = menu_cache.get_item_type_for_menu_item(matched_item_name)
            if matched_item_type:
                return matched_item_type, matched_item_name, (match.start(), match.end())
    return None


def _match_item_with_defaults(
    text_lower: str,
) -> tuple[str | None, str | None, tuple[int, int] | None]:
    """Match text against items with default ingredients (e.g., "The Classic BEC").

    Items with defaults take precedence over trigger-based detection to prevent
    cases like "The Classic BEC on a wheat bagel" from matching "bagel" item type
    due to the "bagel" trigger word.

    Uses a two-phase search when "with" is present in the text:
    - Phase 1: Search only text BEFORE "with" (the head/item zone)
    - Phase 2: Search full text (fallback)

    This prevents modifier text after "with" from hijacking the item match.
    E.g., "the mulberry with extra baked salmon salad" matches "The Mulberry",
    not "Baked Salmon Salad Sandwich".

    Args:
        text_lower: Lowercased user input text

    Returns:
        (matched_item_type, matched_item_name, matched_item_span) or (None, None, None)
    """
    alias_map = get_items_with_defaults_aliases()
    sorted_aliases = sorted(alias_map.keys(), key=len, reverse=True)

    with_pos = text_lower.find(" with ")

    # Phase 1: If "with" present, prefer matches BEFORE "with" (head position)
    if with_pos != -1:
        result = _search_aliases_in_text(text_lower[:with_pos], sorted_aliases, alias_map)
        if result:
            matched_item_type, matched_item_name, matched_item_span = result
            logger.info("CONFIGURABLE_ITEM: item with defaults '%s' detected (before 'with') -> type '%s'", matched_item_name, matched_item_type)
            return matched_item_type, matched_item_name, matched_item_span

    # Phase 2: Search full text (fallback when no "with", or nothing found before it)
    result = _search_aliases_in_text(text_lower, sorted_aliases, alias_map)
    if result:
        matched_item_type, matched_item_name, matched_item_span = result
        logger.info("CONFIGURABLE_ITEM: item with defaults '%s' detected -> type '%s'", matched_item_name, matched_item_type)
        return matched_item_type, matched_item_name, matched_item_span

    return None, None, None


def _has_trigger_outside_span(
    text: str,
    match_start: int,
    match_end: int,
    triggers: list[str],
) -> bool:
    """Check whether any of the type's triggers exist outside the matched menu item span.

    If no single-word trigger is found outside the span, falls back to checking
    multi-word triggers against the full text (since they may straddle the span boundary).

    Args:
        text: Full lowercased input text.
        match_start: Start index of the menu item match span.
        match_end: End index of the menu item match span.
        triggers: Trigger strings for the detected item type.

    Returns:
        True if a trigger is confirmed outside the span, False otherwise.
    """
    text_outside = text[:match_start] + " " + text[match_end:]
    if any(
        re.search(rf'\b{re.escape(t.lower())}\b', text_outside)
        for t in triggers
    ):
        return True

    # No trigger found outside — check if a multi-word trigger matches the full text.
    # Multi-word triggers like "bagel package" can span both inside and outside the
    # menu item match, so checking only outside the span misses them.
    if any(
        re.search(rf'\b{re.escape(t.lower())}\b', text)
        for t in triggers
        if ' ' in t
    ):
        return True

    return False


def _find_different_type_menu_item(
    text: str,
    text_cleaned_lower: str,
    detected_item_type: str,
    configurable_slugs: set[str],
    detected_type_attr_options: set[str],
) -> str | None | bool:
    """Check if a menu item of a different type matches the user input more specifically.

    Scans all menu items for word-boundary matches in the cleaned input text.
    Skips items that appear after "with" (likely modifiers) and items whose
    names are attribute options for the detected type.

    Args:
        text: Original user input (for logging).
        text_cleaned_lower: Lowercased, cleaned input text.
        detected_item_type: Currently detected item type slug.
        configurable_slugs: Set of configurable item type slugs.
        detected_type_attr_options: Attribute option slugs for detected type.

    Returns:
        New item type slug to switch to, None to reject parsing, or True
        if no match found (caller should continue with other checks).
    """
    def is_attribute_option_word(word: str) -> bool:
        word_lower = word.lower()
        for opt in detected_type_attr_options:
            if word_lower == opt or word_lower in opt.split('_') or word_lower in opt.split():
                return True
        return False

    with_pos = text_cleaned_lower.find(" with ")

    for item_name, item_info in menu_cache.iter_all_menu_items().items():
        item_type = item_info.get("item_type")
        if not item_type or item_type == detected_item_type:
            continue
        item_name_lower = item_name.lower()
        if is_attribute_option_word(item_name_lower):
            continue
        match = re.search(rf'\b{re.escape(item_name_lower)}\b', text_cleaned_lower)
        if match:
            if with_pos != -1 and match.start() > with_pos:
                continue

            # Check if the detected type's triggers exist OUTSIDE the matched menu item span.
            # If not, the trigger word came from this menu item's name (false positive) — allow switch.
            # e.g., "One Applewood Chicken Sausage" — "sausage" trigger is inside the match span,
            # so the egg_sandwich detection was a false positive; switch to the side item type.
            triggers_for_detected = menu_cache.get_item_type_triggers(detected_item_type)

            if not _has_trigger_outside_span(
                text_cleaned_lower, match.start(), match.end(), triggers_for_detected
            ):
                # Trigger only existed within the menu item name — switch types
                if item_type in configurable_slugs:
                    logger.info(
                        "CONFIGURABLE_ITEM: switching type '%s' -> '%s' - trigger only inside "
                        "menu item '%s' span in '%s'",
                        detected_item_type, item_type, item_name, text[:50],
                    )
                    return item_type
                else:
                    logger.info(
                        "CONFIGURABLE_ITEM: rejecting '%s' - trigger only inside non-configurable "
                        "menu item '%s' of type '%s'",
                        text[:50], item_name, item_type,
                    )
                    return None

            # Trigger found outside match span. Check if the matched menu item
            # name is part of a multi-word trigger for the detected type.
            # If so, the detected type legitimately "owns" this word — don't switch.
            # e.g., "bagel" in "bagel package" trigger → don't switch from bagel_package.
            item_in_detected_trigger = any(
                re.search(rf'\b{re.escape(item_name_lower)}\b', t.lower())
                for t in triggers_for_detected
                if ' ' in t
            )
            if item_in_detected_trigger:
                continue

            # Don't switch types if the matching menu item name is a known modifier
            # e.g., "muenster cheese" in "muenster cheese omelette" should be treated
            # as a modifier for omelette, not a type switch to "cheese"
            _filler_words = {'a', 'an', 'the', 'of', 'and', 'or', 'with', 'for'}
            content_words = [w for w in item_name_lower.split() if w not in _filler_words]
            all_words_are_modifiers = (
                content_words and all(menu_cache.is_known_modifier(w) for w in content_words)
            )
            if menu_cache.is_known_modifier(item_name_lower) or all_words_are_modifiers:
                logger.info(
                    "CONFIGURABLE_ITEM: skipping type switch '%s' -> '%s' - "
                    "'%s' is a known modifier for '%s'",
                    detected_item_type, item_type, item_name, detected_item_type,
                )
                continue
            if item_type in configurable_slugs:
                logger.info(
                    "CONFIGURABLE_ITEM: switching type '%s' -> '%s' based on menu item '%s' in '%s'",
                    detected_item_type, item_type, item_name, text[:50]
                )
                return item_type
            else:
                logger.info(
                    "CONFIGURABLE_ITEM: skipping '%s' - found non-configurable menu item '%s' of type '%s'",
                    text[:50], item_name, item_type
                )
                return None

    return True  # No match found, continue checking


def _has_extra_word_specificity(
    text: str,
    text_lower: str,
    detected_item_type: str,
    more_specific_matches: list[dict],
) -> bool:
    """Check if user input has extra words that match a more specific menu item.

    Compares input words against the type's trigger words. If extra words
    appear in any matching menu item name, the input is too specific for
    the generic configurable parser.

    Args:
        text: Original user input (for logging).
        text_lower: Lowercased user input.
        detected_item_type: Currently detected item type slug.
        more_specific_matches: Menu items matched by word-boundary search.

    Returns:
        True if extra specificity found (caller should reject), False otherwise.
    """
    filler_words = {
        'a', 'an', 'the', 'i', 'id', 'want', 'like', 'get', 'can', 'have', 'need',
        'please', 'would', 'could', 'some', 'of', 'with', 'and', 'or', 'for', 'me',
    }
    input_words = set(re.findall(r'\b[a-z]+\b', text_lower))
    type_words = set(re.findall(r'\b[a-z]+\b', detected_item_type.lower()))
    triggers = menu_cache.get_item_type_triggers().get(detected_item_type, [])
    for trigger in triggers:
        if len(trigger.split()) <= 2:
            type_words.update(re.findall(r'\b[a-z]+\b', trigger.lower()))
    extra_words = input_words - type_words - filler_words

    if extra_words:
        for match in more_specific_matches:
            match_name_lower = match.get("name", "").lower()
            matching_extra = [w for w in extra_words if w in match_name_lower]
            if matching_extra:
                logger.info(
                    "CONFIGURABLE_ITEM: skipping '%s' - extra words %s found in menu item '%s'",
                    text[:50], matching_extra, match.get("name")
                )
                return True

    return False


def _check_more_specific_menu_items(
    text: str,
    text_lower: str,
    text_cleaned: str,
    detected_item_type: str,
    configurable_slugs: set[str],
) -> str | None:
    """Check if user text matches more specific menu items of a different type.

    This prevents false positives like "bagel chips" triggering configurable bagel
    flow when there are specific menu items like "Bagel Chips - Salt". Also catches
    cases like "hot chai tea" where "chai tea" is a complete menu item of type
    "chai_drink" but trigger word "tea" detected the "tea" type.

    Returns:
        Updated item type slug if type was kept or switched to a more specific
        configurable type. None to signal that parsing should be rejected.
    """
    more_specific_matches = menu_cache.find_items_by_word_match(text_cleaned)
    text_cleaned_lower = text_cleaned.lower()
    detected_type_attr_options = menu_cache.get_all_attribute_option_slugs_for_item_type(detected_item_type)

    # Phase 1: Check if a menu item of a different type matches more specifically
    phase1_result = _find_different_type_menu_item(
        text, text_cleaned_lower, detected_item_type,
        configurable_slugs, detected_type_attr_options,
    )
    if phase1_result is not True:
        return phase1_result  # type: ignore[return-value]

    # Phase 2: Check if extra words in input match a more specific menu item
    if more_specific_matches and _has_extra_word_specificity(
        text, text_lower, detected_item_type, more_specific_matches,
    ):
        return None

    return detected_item_type


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

    # 1. Check for items with default ingredients FIRST
    matched_item_type, matched_item_name, matched_item_span = _match_item_with_defaults(text_lower)

    # 2. Detect which configurable item type this text matches
    detected_item_type: str | None = matched_item_type

    # Only do trigger-based detection if no item with defaults was found
    if not detected_item_type:
        detected_item_type = _detect_type_by_triggers(text_lower, configurable_slugs)

    # 3. Option alias fallback if no type detected yet
    inferred_attr_values: dict = {}
    if not detected_item_type:
        fallback = _try_option_alias_fallback(text_lower)
        if fallback:
            detected_item_type, inferred_attr_values = fallback
        else:
            return None

    # 4. Check if the user's text matches more specific menu items
    resolved_type = _check_more_specific_menu_items(
        text, text_lower, text_cleaned, detected_item_type, configurable_slugs
    )
    if resolved_type is None:
        return None
    detected_item_type = resolved_type

    return (detected_item_type, matched_item_name, matched_item_span, inferred_attr_values)


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
    item_names = list(menu_cache.get_item_names(item_type_slug))
    if not item_names:
        return None

    if len(item_names) == 1:
        return item_names[0].title()

    # Look for item name ending with the type slug word
    # Only use as default if exactly one item matches (otherwise disambiguation needed)
    type_display = item_type_slug.replace('_', ' ')
    matching = [name for name in item_names if name.lower().endswith(type_display)]
    if len(matching) == 1:
        return matching[0].title()

    # Multiple items, no clear default — return None so disambiguation can handle it
    return None


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
    item_names = menu_cache.get_item_names(item_type_slug)
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
