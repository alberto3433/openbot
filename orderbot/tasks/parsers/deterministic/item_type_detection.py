"""
Item Type Detection Functions.

This module contains functions for detecting item types from user input text
using database-driven trigger keywords and option aliases.

Functions:
- _find_trigger_matches: Core trigger matching logic shared by detection functions
- _detect_item_type: Detect item type from text (all types)
- _is_modifier_chain: Check if text is a single item with modifier chain
- _detect_type_by_triggers: Detect configurable item type by trigger keywords
- _try_option_alias_fallback: Infer item type from attribute option aliases
- _detect_configurable_item_type: Detect configurable item type with smart matching
"""

import re
import logging

from orderbot.cache import menu_cache
from ..quantity_utils import QTY_WORDS_RE

logger = logging.getLogger(__name__)

_NEGATION_WORDS = {"no", "without", "skip", "not"}


def _is_preceded_by_negation(text_lower: str, position: int) -> bool:
    """Check if the word at *position* is immediately preceded by a negation word."""
    if position <= 0:
        return False
    text_before = text_lower[:position].rstrip()
    if not text_before:
        return False
    last_word = text_before.split()[-1]
    return last_word in _NEGATION_WORDS


# Common words that should not be treated as item triggers.
# Shared by _detect_item_type, _detect_configurable_item_type, and _has_item_indicator.
_SKIP_TRIGGER_WORDS = {
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
}

# If any trigger covers >= 60% of the input text, prefer the longest such trigger
# regardless of slug_matches priority. This prevents partial slug matches like
# "breakfast" (41% of "english breakfast tea") from beating full-text matches
# like "english breakfast tea" (100%).
_HIGH_COVERAGE_THRESHOLD = 0.6


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
        if _is_preceded_by_negation(text_lower, idx):
            continue
        # Check if this match is in the "end region" (last 20% of text or last 15 chars)
        text_len = len(text_lower)
        end_region_start = max(text_len - 15, int(text_len * 0.8))
        is_at_end = end_pos >= end_region_start
        slug_matches = keyword_lower == item_type_slug or keyword_lower.rstrip("s") == item_type_slug
        matches.append((item_type_slug, keyword, len(keyword_lower), end_pos, is_at_end, slug_matches))

    if not matches:
        return None, None

    # High-coverage pre-check: if any trigger covers >= 60% of the input,
    # prefer the longest such trigger regardless of slug_matches priority.
    text_len = len(text_lower)
    if text_len > 0:
        high_cov = [m for m in matches if m[2] >= text_len * _HIGH_COVERAGE_THRESHOLD]
        if high_cov:
            high_cov.sort(key=lambda x: -x[2])  # longest first
            best = high_cov[0]
            return best[0], best[1]

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
    quantity_pattern = rf'^(\d+|{QTY_WORDS_RE})\s+'
    after_and_stripped = re.sub(quantity_pattern, '', after_and, flags=re.IGNORECASE)

    # Check if the stripped text (without quantity) matches an item keyword
    item_type, _ = _detect_item_type(after_and_stripped)
    if item_type:
        # Contains an item keyword - it's multi-item, not modifier chain
        return False

    # If no item keyword found, it's likely a modifier chain
    return True


def _detect_type_by_triggers(
    text_lower: str,
    configurable_slugs: set[str],
) -> str | None:
    """Detect item type by matching configurable item type trigger keywords.

    Collects all trigger matches with position info and selects the best one using
    sorting heuristics that prefer triggers before "with", slug matches, longer
    triggers, and later positions.

    Args:
        text_lower: Lowercased user input text
        configurable_slugs: Set of configurable item type slugs

    Returns:
        The best-matching item type slug, or None if no match found
    """
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

                # Skip triggers preceded by negation words ("no spread" = modifier negation)
                if _is_preceded_by_negation(text_lower, start_pos):
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
        # High-coverage pre-check: if any trigger before "with" covers >= 60% of the
        # input, prefer the longest such trigger regardless of slug_matches priority.
        text_len = len(text_lower)
        if text_len > 0:
            high_cov = [
                m for m in matches
                if m[4] and m[2] >= text_len * _HIGH_COVERAGE_THRESHOLD  # is_before_with AND high coverage
            ]
            if high_cov:
                high_cov.sort(key=lambda x: -x[2])  # longest first
                return high_cov[0][0]

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
        return matches[0][0]

    return None


def _try_option_alias_fallback(
    text_lower: str,
) -> tuple[str, dict] | None:
    """Try to infer item type from attribute option aliases.

    Handles cases like "earl grey" -> tea with tea_flavor=earl_gray, where the
    input doesn't match any trigger but does match an option alias.

    Args:
        text_lower: Lowercased user input text

    Returns:
        (detected_item_type, inferred_attr_values) or None if no match
    """
    cleaned_input = text_lower.strip()
    option_match = menu_cache.get_item_type_from_option_alias(cleaned_input)
    if option_match:
        detected_item_type, inferred_attr_slug, inferred_option_slug = option_match
        logger.info(
            "CONFIGURABLE_ITEM: inferred type '%s' from option alias '%s' (%s=%s)",
            detected_item_type, cleaned_input, inferred_attr_slug, inferred_option_slug
        )
        inferred_attr_values = {inferred_attr_slug: inferred_option_slug}
        return detected_item_type, inferred_attr_values
    return None


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

    # Deduplicate to first match per (item_type, trigger) pair -- _find_trigger_matches
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
        item_names = menu_cache.get_item_names(item_type_slug)
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
