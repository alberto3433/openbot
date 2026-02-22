"""
Inapplicable Modifier and Attribute Detection.

This module detects modifiers and attribute options that the user mentioned
but that don't apply to the matched item type, enabling helpful feedback
like "Heads up, that item only comes in one size."
"""

import re
import logging

from orderbot.cache import menu_cache

logger = logging.getLogger(__name__)


def _detect_inapplicable_modifiers(text_lower: str) -> list[dict]:
    """Detect globally-known modifiers in 'with X' phrases that weren't matched for an item.

    Used for non-configurable items where item-type-specific modification extraction
    found nothing. Checks if there are 'with X' phrases where X is a known modifier
    globally (e.g., 'hazelnut syrup' on Deviled Eggs).

    Args:
        text_lower: Lowercase user input.

    Returns:
        List of dicts with token and display_name for each inapplicable modifier.
    """
    with_match = re.search(r'\bwith\s+(.+?)(?:\s*(?:please|thanks)|\s*$)', text_lower)
    if not with_match:
        return []

    modifier_text = with_match.group(1).strip()
    if not modifier_text:
        return []

    results: list[dict] = []
    candidates = [modifier_text]
    for part in re.split(r'\s+and\s+|\s*,\s*', modifier_text):
        part = part.strip()
        if part and part != modifier_text:
            candidates.append(part)

    for candidate in candidates:
        canonical = menu_cache.normalize_modifier(candidate)
        if canonical != candidate:
            results.append({
                "token": candidate,
                "display_name": canonical,
            })
            return results

        if " " in candidate:
            for word in candidate.split():
                word = word.strip()
                if len(word) < 3:
                    continue
                if menu_cache.is_known_modifier(word):
                    canonical = menu_cache.normalize_modifier(word)
                    results.append({
                        "token": candidate,
                        "display_name": canonical if canonical != word else candidate.title(),
                    })
                    return results

    return results


def _detect_inapplicable_attributes(
    text_lower: str,
    menu_item: str,
    menu_item_span: tuple[int, int] | None,
    item_type_slug: str | None,
) -> list[dict]:
    """Detect attribute option words in input that don't apply to the matched item type.

    Scans text outside the menu item name span for words that are known attribute
    option values (e.g., "small", "iced") but map to attributes the item type
    doesn't have. This lets us notify the user: "Heads up, only comes in one size."

    Args:
        text_lower: Lowercase user input.
        menu_item: The matched menu item name.
        menu_item_span: (start, end) character span of the item name in text_lower.
        item_type_slug: The item type slug (e.g., "sandwich", "sized_beverage").

    Returns:
        List of {word, attribute_slug} for each inapplicable attribute word found.
    """
    if not item_type_slug:
        return []

    # Get all known attribute option words -> attribute slug mapping
    all_option_words = menu_cache.get_all_attribute_option_words()
    if not all_option_words:
        return []

    # Get the attributes this item type actually has
    item_attrs = menu_cache.get_item_type_attributes(item_type_slug)
    item_attr_slugs = set(item_attrs.keys()) if item_attrs else set()

    # Build set of words that are part of the menu item name (to exclude)
    item_name_words = set(menu_item.lower().split())

    # Get the text outside the menu item span
    if menu_item_span:
        outside_text = text_lower[:menu_item_span[0]] + " " + text_lower[menu_item_span[1]:]
    else:
        outside_text = text_lower

    # Tokenize the outside text
    words = outside_text.split()

    results: list[dict] = []
    seen_attrs: set[str] = set()
    for word in words:
        word_clean = word.strip(",.!?;:'\"")
        if not word_clean or len(word_clean) < 2:
            continue
        # Skip words that are part of the item name
        if word_clean in item_name_words:
            continue
        # Check if this word is a known attribute option
        if word_clean in all_option_words:
            attr_slug = all_option_words[word_clean]
            # Only flag if the item type does NOT have this attribute
            if attr_slug not in item_attr_slugs and attr_slug not in seen_attrs:
                seen_attrs.add(attr_slug)
                results.append({"word": word_clean, "attribute_slug": attr_slug})

    logger.info(
        "INAPPLICABLE_DETECT: text='%s', item_type=%s, outside='%s', "
        "item_attrs=%s, results=%s",
        text_lower[:50], item_type_slug, outside_text.strip()[:50],
        item_attr_slugs, results,
    )
    return results
