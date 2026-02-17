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


def _match_item_with_defaults(
    text_lower: str,
) -> tuple[str | None, str | None, tuple[int, int] | None]:
    """Match text against items with default ingredients (e.g., "The Classic BEC").

    Items with defaults take precedence over trigger-based detection to prevent
    cases like "The Classic BEC on a wheat bagel" from matching "bagel" item type
    due to the "bagel" trigger word.

    Args:
        text_lower: Lowercased user input text

    Returns:
        (matched_item_type, matched_item_name, matched_item_span) or (None, None, None)
    """
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
                return matched_item_type, matched_item_name, matched_item_span
    return None, None, None


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

    Args:
        text: Original user input text
        text_lower: Lowercased user input text
        text_cleaned: Lowercased text with ordering phrases stripped
        detected_item_type: The currently detected item type slug
        configurable_slugs: Set of configurable item type slugs

    Returns:
        Updated item type slug if type was kept or switched to a more specific
        configurable type. None to signal that parsing should be rejected
        (non-configurable match or extra-word specificity match found).
    """
    more_specific_matches = menu_cache.find_items_by_word_match(text_cleaned)

    text_cleaned_lower = text_cleaned.lower()
    detected_type_attr_options = menu_cache.get_all_attribute_option_slugs_for_item_type(detected_item_type)

    def is_attribute_option_word(word: str) -> bool:
        """Check if a word appears in any attribute option for the detected type."""
        word_lower = word.lower()
        for opt in detected_type_attr_options:
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
                    return item_type
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

    # Return the original type unchanged
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
