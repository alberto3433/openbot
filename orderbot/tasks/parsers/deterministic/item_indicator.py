"""
Item Indicator Detection Pipeline.

Detects whether text references a menu item by checking aliases, word boundary
matches, and item type triggers. Also includes modifier-only detection.

Extracted from tokenization.py during decomposition refactoring.
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ..quantity_utils import extract_leading_quantity as _extract_leading_quantity
from ...utils.text import normalize_text

from .item_parsing import (
    _detect_item_type,
    _find_trigger_matches,
)
from .item_type_detection import _HIGH_COVERAGE_THRESHOLD

logger = logging.getLogger(__name__)

# Import consolidated skip words from constants
from orderbot.tasks.parsers.constants import (
    TOKENIZATION_SKIP_WORDS as _SKIP_WORDS,
    ORDERING_PREFIXES,
    ARTICLES,
)

# Trailing politeness words that should be stripped before menu item matching
_TRAILING_STRIP_WORDS = {"please", "thanks", "thank you", "ok", "okay", "alright", "pls", "thx"}


def _strip_trailing_words(text: str) -> str:
    """Strip trailing politeness words from text for menu item matching."""
    words = text.split()
    while words and words[-1].lower().rstrip(".,!?") in _TRAILING_STRIP_WORDS:
        words.pop()
    return " ".join(words)


def _strip_ordering_prefix(text: str) -> str:
    """Strip ordering prefixes and following articles from text.

    Handles phrases like "I'd like an egg and cheese sandwich" -> "egg and cheese sandwich"

    Args:
        text: Text to strip

    Returns:
        Text with ordering prefix and article stripped
    """
    text_lower = normalize_text(text)

    # Strip ordering prefixes (sorted by length, longest first)
    for prefix in sorted(ORDERING_PREFIXES, key=len, reverse=True):
        if text_lower.startswith(prefix):
            # Check for word boundary
            if len(text_lower) > len(prefix) and text_lower[len(prefix)].isalnum():
                continue
            text_lower = text_lower[len(prefix):].strip()
            break

    # Strip leading articles (a, an, the)
    for article in sorted(ARTICLES, key=len, reverse=True):
        if text_lower.startswith(article + " "):
            text_lower = text_lower[len(article):].strip()
            break

    return text_lower


# =============================================================================
# Item Indicator Detection
# =============================================================================

def _try_menu_item_alias_match(
    text_for_matching: str, text_singularized: str, text_lower: str
) -> tuple[bool, str | None, str | None]:
    """Try to match the full text against menu item aliases.

    Checks both original and singularized forms against the alias registry.
    """
    resolved = menu_cache.resolve_menu_item_alias(text_for_matching)
    if not resolved and text_singularized != text_for_matching:
        resolved = menu_cache.resolve_menu_item_alias(text_singularized)
    if resolved:
        # Get the item type from the resolved menu item (not from text triggers)
        # This ensures "egg and cheese" → "Egg and Cheese Sandwich" → "egg_sandwich"
        item_type = menu_cache.get_item_type_for_menu_item(resolved)
        if not item_type:
            # Fallback to trigger-based detection if menu item lookup fails
            item_type, _ = _detect_item_type(text_lower)
        return True, item_type, resolved
    return False, None, None


def _try_word_boundary_match(
    text_for_matching: str,
) -> tuple[bool, str | None, str | None]:
    """Try to match text against menu items using word boundary matching.

    Handles ambiguous cases like "the classic" which matches multiple items.
    Returns True to indicate an item indicator even if disambiguation is needed later.
    """
    word_matches = menu_cache.find_items_by_word_match(text_for_matching)
    if not word_matches and " " in text_for_matching:
        # Multi-word phrase not found in primary cache - try ALL menu items
        word_matches = menu_cache.find_all_items_by_word_match(text_for_matching)
    if word_matches:
        # Multiple matches - pick the first one's item_type (disambiguation happens later)
        first_match = word_matches[0]
        item_type = first_match.get("item_type")
        # Use the search term as resolved_name since we don't have a single match
        return True, item_type, text_for_matching
    return False, None, None


def _collect_trigger_matches(
    text_for_matching: str, text_singularized: str, texts_to_try: list[str]
) -> list[tuple[int, int, str, str]]:
    """Collect all trigger matches from explicit triggers and implicit item type names.

    Returns list of (position, length, item_type_slug, trigger) tuples.
    """
    # Collect explicit trigger matches, deduplicate to first occurrence
    raw_matches = _find_trigger_matches(text_for_matching)
    if text_singularized != text_for_matching:
        raw_matches.extend(_find_trigger_matches(text_singularized))

    seen_triggers: set[tuple[str, str]] = set()
    matches: list[tuple[int, int, str, str]] = []
    for item_type_slug, keyword, m in raw_matches:
        key = (item_type_slug, keyword.lower())
        if key in seen_triggers:
            continue
        seen_triggers.add(key)
        matches.append((m.start(), len(keyword.lower()), item_type_slug, keyword))

    # Add implicit triggers for item type names themselves
    # This handles cases where "bagel" type doesn't have "bagel" as explicit trigger
    # Use get_configurable_item_types() to include all item types, not just those with triggers
    all_item_types = menu_cache.get_configurable_item_types()
    for item_type_slug in all_item_types:
        # Check for the item type name (with underscores replaced by spaces)
        type_variants = [
            item_type_slug.lower(),
            item_type_slug.lower().replace("_", " "),
        ]
        for variant in type_variants:
            # Use word boundary matching to prevent partial matches
            pattern = rf'\b{re.escape(variant)}\b'
            for try_text in texts_to_try:
                match = re.search(pattern, try_text)
                if match:
                    pos = match.start()
                    # Only add if not already matched at this position
                    existing = [(m[0], m[2]) for m in matches]
                    if (pos, item_type_slug) not in existing:
                        matches.append((pos, len(variant), item_type_slug, variant))
                    break  # Found in one form, no need to try singularized

    return matches


def _select_best_trigger_match(
    matches: list[tuple[int, int, str, str]],
    all_item_types: set[str],
    text_length: int = 0,
) -> tuple[bool, str | None, str | None]:
    """Select the best match from collected trigger matches using priority scoring.

    Adds implicit item-type matches for triggers that are item type names,
    then applies priority and position scoring to select the best match.
    """
    # Get modifiers and attribute options for deprioritizing modifier-based triggers
    all_modifiers = menu_cache.get_all_modifier_words()
    all_attr_options = menu_cache.get_all_attribute_option_words()
    generic_types = menu_cache.get_generic_item_types()

    # Item type priority: prefer specific types over generic ones
    # When trigger is the same word for multiple types, prefer the type
    # that matches the trigger word itself (e.g., "bagel" -> bagel type)
    def _type_priority(item_type: str, trigger: str) -> int:
        """Return priority score (lower = better)."""
        trigger_lower = trigger.lower()
        # Best: item type matches the trigger word (bagel -> bagel)
        if item_type.lower() == trigger_lower:
            return 0
        # Also best: trigger is a known item name for this specific item_type
        # e.g., "latte" is in sized_beverage's item names, so sized_beverage gets high priority
        # This is fully data-driven - works for any item type, not just beverages
        item_type_names = menu_cache.get_item_names(item_type)
        if trigger_lower in {n.lower() for n in item_type_names}:
            return 1
        # Also best: trigger matches another item type name exactly
        # This means the trigger is likely targeting that specific type, not this one
        # e.g., "bagel" trigger for "side" type should yield to "bagel" type if it exists
        if trigger_lower in all_item_types or trigger_lower.replace(" ", "_") in all_item_types:
            # This item_type doesn't match the trigger, but another type does
            # Demote this match significantly
            return 6
        # Deprioritize triggers that are actually modifiers/attributes (but not coffee types)
        # e.g., "large" is a size, not an item indicator
        if trigger_lower in all_modifiers or trigger_lower in all_attr_options:
            return 5
        # Good: item type contains the trigger word (e.g., "egg_sandwich" contains "egg")
        if trigger_lower in item_type.lower():
            return 1
        # Generic types have lower priority (loaded from DB)
        if item_type in generic_types:
            return 4
        return 2

    # Check if any trigger word matches an item type name
    # Add implicit match for that item type (with position from the trigger location)
    for pos, length, item_type, trigger in list(matches):
        trigger_lower = trigger.lower()
        if trigger_lower in all_item_types and trigger_lower != item_type:
            # The trigger word is an item type name, add it as a match
            matches.append((pos, length, trigger_lower, trigger))
        trigger_underscore = trigger_lower.replace(" ", "_")
        if trigger_underscore in all_item_types and trigger_underscore != item_type:
            matches.append((pos, length, trigger_underscore, trigger))

    # High-coverage pre-check: if any trigger covers >= 60% of the input,
    # prefer the longest such trigger regardless of slug/priority scoring.
    if text_length > 0:
        high_cov = [
            m for m in matches
            if m[1] >= text_length * _HIGH_COVERAGE_THRESHOLD
        ]
        if high_cov:
            high_cov.sort(key=lambda x: -x[1])  # longest first
            best = high_cov[0]
            return True, best[2], best[3]

    # PRIORITY RULES:
    # 1. Priority 0 matches (trigger == item_type, e.g., "bagel" -> bagel) always win
    # 2. Among same-priority matches, prefer earlier position
    # 3. For position < 15, prefer that match unless priority 0 exists elsewhere

    # First, check if any match has priority 0 (trigger matches item type)
    priority_0_matches = [
        m for m in matches
        if _type_priority(m[2], m[3]) == 0
    ]

    if priority_0_matches:
        # Among priority-0 matches, prefer configurable types over non-configurable.
        # This prevents "breakfast" (non-configurable slug match) from beating
        # "tea" (configurable slug match) in "english breakfast tea".
        configurable_slugs = menu_cache.get_configurable_item_type_slugs()
        configurable_p0 = [m for m in priority_0_matches if m[2] in configurable_slugs]
        p0_to_sort = configurable_p0 if configurable_p0 else priority_0_matches
        # Sort by position, then length
        p0_to_sort.sort(key=lambda x: (x[0], -x[1]))
        best = p0_to_sort[0]
        return True, best[2], best[3]

    # No priority 0 matches - use priority + position logic
    # Sort by priority first, then position (within first 30 chars), then length
    def _match_score(m):
        pos, length, item_type, trigger = m
        priority = _type_priority(item_type, trigger)
        # Group positions: early (<=15), mid (16-30), late (>30)
        pos_group = 0 if pos <= 15 else (1 if pos <= 30 else 2)
        return (priority, pos_group, pos, -length)

    matches.sort(key=_match_score)

    best = matches[0]
    return True, best[2], best[3]


def _has_item_indicator(text: str) -> tuple[bool, str | None, str | None]:
    """Check if text contains an item type trigger or matches a menu item.

    Prioritizes item triggers that appear early in the text (especially after
    articles like "a", "an") over longer triggers that appear later. This
    correctly identifies "a bagel with cream cheese" as a bagel, not cream cheese.

    Args:
        text: Text to check

    Returns:
        (has_indicator, item_type, resolved_name)
        - (True, "sized_beverage", "Latte") if triggers coffee
        - (True, "egg_sandwich", "The Classic BEC") if matches menu item
        - (False, None, None) if no item indicator

    Examples:
        >>> _has_item_indicator("large iced latte")
        (True, "sized_beverage", "latte")
        >>> _has_item_indicator("bacon egg and cheese")
        (True, "egg_sandwich", "The Classic BEC")  # if alias exists
        >>> _has_item_indicator("cream cheese")
        (False, None, None)
    """
    text_lower = normalize_text(text)

    # Strip trailing politeness words (please, thanks, etc.) before matching
    text_for_matching = _strip_trailing_words(text_lower)

    # Strip trailing position qualifiers (e.g., "on the side") before item matching
    for qual_pattern in menu_cache.get_qualifier_patterns():
        qual_info = menu_cache.get_qualifier_info(qual_pattern)
        if qual_info and qual_info.get("category") == "position":
            if text_for_matching.endswith(" " + qual_pattern):
                text_for_matching = text_for_matching[: -(len(qual_pattern) + 1)].strip()
                break  # Only strip one trailing qualifier

    # Also prepare singularized version for matching plurals like "coffees" -> "coffee"
    # Singularize each word to handle "three coffees" -> "three coffee"
    words = text_for_matching.split()
    singularized_words = [singularize(w) for w in words]
    text_singularized = " ".join(singularized_words)

    # Strategy 1: Direct menu item alias match
    result = _try_menu_item_alias_match(text_for_matching, text_singularized, text_lower)
    if result[0]:
        return result

    # Strategy 2: Word boundary match (for ambiguous cases like "the classic")
    result = _try_word_boundary_match(text_for_matching)
    if result[0]:
        return result

    # Strategy 3: Collect trigger matches (explicit triggers + implicit item type names)
    texts_to_try = [text_for_matching]
    if text_singularized != text_for_matching:
        texts_to_try.append(text_singularized)

    matches = _collect_trigger_matches(text_for_matching, text_singularized, texts_to_try)
    if not matches:
        return False, None, None

    # Strategy 4: Score and select best trigger match
    all_item_types = menu_cache.get_configurable_item_types()
    return _select_best_trigger_match(matches, all_item_types, text_length=len(text_for_matching))


# =============================================================================
# Modifier-Only Detection
# =============================================================================

def _is_modifier_only(text: str) -> tuple[bool, list[str]]:
    """Check if text contains ONLY modifiers (no item triggers).

    Modifiers include:
    - Known ingredients (bacon, cheese, cream cheese, lox)
    - Known attribute options (large, medium, iced, hot)
    - Quantity words are skipped

    Args:
        text: Text to check

    Returns:
        (is_modifier_only, list_of_modifiers)
        - (True, ["cream cheese"]) if only modifiers
        - (False, []) if contains item trigger or unknown words

    Examples:
        >>> _is_modifier_only("cream cheese")
        (True, ["Cream Cheese"])
        >>> _is_modifier_only("bacon and cheese")
        (True, ["Bacon", "American Cheese"])
        >>> _is_modifier_only("large iced latte")
        (False, [])  # "latte" is an item trigger
    """
    text_lower = normalize_text(text)

    # Remove quantity prefix
    _, remaining = _extract_leading_quantity(text_lower)
    if not remaining:
        return False, []

    # Check if this has any item indicators
    has_item, _, _ = _has_item_indicator(remaining)
    if has_item:
        return False, []

    # Get lookup data
    all_modifiers = menu_cache.get_all_modifier_words()
    attr_options = menu_cache.get_all_attribute_option_words()

    # Tokenize and check each word/phrase
    # First try to match multi-word modifiers (e.g., "cream cheese")
    found_modifiers = []
    remaining_to_check = remaining

    # Try to match known multi-word modifiers first
    for modifier in sorted(all_modifiers, key=len, reverse=True):
        if modifier in remaining_to_check:
            normalized = menu_cache.normalize_modifier(modifier)
            found_modifiers.append(normalized)
            remaining_to_check = remaining_to_check.replace(modifier, " ").strip()

    # Check remaining words
    words = remaining_to_check.split()
    for word in words:
        word = normalize_text(word)
        if not word:
            continue

        # Skip common words
        if word in _SKIP_WORDS:
            continue

        # Skip "and" separator
        if word == "and":
            continue

        # Check if it's a known modifier
        if word in all_modifiers:
            normalized = menu_cache.normalize_modifier(word)
            if normalized not in found_modifiers:
                found_modifiers.append(normalized)
            continue

        # Check if it's a known attribute option
        if word in attr_options:
            continue

        # Unknown word - this is NOT modifier-only
        return False, []

    return True, found_modifiers
