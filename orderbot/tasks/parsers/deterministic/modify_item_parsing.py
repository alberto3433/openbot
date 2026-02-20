"""
Modify-Existing-Item Pattern Detection Pipeline.

Functions for detecting requests to modify an existing cart item with a modifier,
e.g. "can I have cream cheese on the cinnamon raisin bagel".
"""
from __future__ import annotations

import functools
import re
import logging

from orderbot.cache import menu_cache

from ...schemas import (
    OpenInputResponse,
)

from ..constants import (
    SKIP_WORDS_BASIC,
    SKIP_WORDS_PREPOSITIONS,
)

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _get_attribute_terminators_pattern() -> str:
    """Build regex alternation of all attribute option words from database.

    These words act as terminators for 'with X' patterns, e.g.:
    - "with butter toasted" -> butter is the modifier, toasted terminates
    - "with cream cheese scooped" -> cream cheese is the modifier, scooped terminates

    Returns:
        Regex alternation string like "toasted|scooped|iced|hot|large|medium|..."
    """
    # Get all attribute option words from database
    attr_words = menu_cache.get_all_attribute_option_words()

    # Filter to reasonable terminators (2+ chars, not common words)
    filter_words = SKIP_WORDS_BASIC | SKIP_WORDS_PREPOSITIONS | {'no', 'yes'}
    terminators = {word for word in attr_words.keys()
                   if len(word) >= 2 and word not in filter_words}

    # Sort by length descending (longer matches first)
    sorted_terminators = sorted(terminators, key=len, reverse=True)

    return "|".join(re.escape(t) for t in sorted_terminators)


def _match_modifier_before_target_type(
    text_lower: str, item_type_pattern: str,
) -> tuple[str | None, str | None]:
    """Match patterns where modifier appears BEFORE the target item type.

    Catches: "can I have X on the Y {item_type}", "put X on the Y {item_type}", etc.

    Returns (modifier_part, target_description) or (None, None).
    """
    patterns = [
        # "can I have X on the Y {item_type}"
        rf"(?:can\s+i\s+(?:have|get)|i(?:'d|\s+would)\s+like)\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
        # "put X on the Y {item_type}"
        rf"(?:put|add)\s+(.+?)\s+(?:on|to)\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
        # "X on the Y {item_type}" (simple form)
        rf"^(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}$",
        # "i want X on the Y {item_type}"
        rf"i\s+want\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*{item_type_pattern}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, None


def _match_target_with_modifier(
    text_lower: str, item_type_pattern: str,
) -> tuple[str | None, str | None]:
    """Match 'make the Y {item_type} with X' — target BEFORE modifier.

    Returns (modifier_part, target_description) or (None, None).
    """
    pattern = rf"make\s+(?:the|my)\s+(.+?)\s+{item_type_pattern}\s+with\s+(.+?)(?:\s+(?:please|thanks))?$"
    match = re.search(pattern, text_lower)
    if match:
        return match.group(2).strip(), match.group(1).strip()
    return None, None


def _match_implicit_target_modifier(
    text_lower: str, item_type_pattern: str,
) -> tuple[str | None, str | None]:
    """Match implicit-target patterns — 'make it with X', 'make the {item_type} with X', 'put X on it'.

    target_description is always None (caller should find last/any item).

    Returns (modifier_part, None) or (None, None).
    """
    # First try patterns with generic item type (no specific description)
    generic_pattern = rf"make\s+(?:the|my)\s+{item_type_pattern}\s+with\s+(.+?)(?:\s+(?:please|thanks))?$"
    match = re.search(generic_pattern, text_lower)
    if match:
        return match.group(1).strip(), None

    # Then try implicit "it" patterns
    it_patterns = [
        # "make it with X"
        r"make\s+it\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
        # "can you make it with X" / "could you make it with X instead"
        r"(?:can|could|would)\s+you\s+(?:make|have|do)\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\s+(?:please|thanks))?$",
        # "put X on it"
        r"(?:put|add)\s+(.+?)\s+(?:on|to)\s+it\b",
        # "i want X on it"
        r"i\s+want\s+(.+?)\s+(?:on|to)\s+it\b",
        # "can I have X on it"
        r"(?:can\s+i\s+(?:have|get))\s+(.+?)\s+(?:on|to)\s+it\b",
    ]
    for pattern in it_patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(1).strip(), None
    return None, None


def _parse_modify_existing_item(text: str) -> OpenInputResponse | None:
    """Detect requests to modify an existing cart item with a modifier.

    Catches patterns like:
    - "can I have cream cheese on the cinnamon raisin bagel"
    - "put butter on the plain bagel"
    - "add mayo to the sandwich"
    - "make the bagel with scallion cream cheese"
    - "make it with butter"

    Item type names are loaded dynamically from the database, so this function
    works with any item types.

    This must be called BEFORE menu item matching to prevent modifiers like
    "scallion cream cheese" from being matched to menu items.

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    # Build dynamic item type pattern from database
    item_type_names = menu_cache.get_item_type_names_for_regex()
    if not item_type_names:
        return None

    # Build regex alternation:
    # Names are sorted by length (longest first) so "deli sandwich" matches before "sandwich"
    item_type_pattern = "(?:" + "|".join(re.escape(name) for name in item_type_names) + ")"

    # Try each pattern group in priority order
    modifier_part, target_description = _match_modifier_before_target_type(text_lower, item_type_pattern)
    if not modifier_part:
        modifier_part, target_description = _match_target_with_modifier(text_lower, item_type_pattern)
    if not modifier_part:
        modifier_part, target_description = _match_implicit_target_modifier(text_lower, item_type_pattern)

    if not modifier_part:
        return None

    # Clean up modifier_part - remove trailing "please/thanks"
    modifier_part = re.sub(r"\s+(?:please|thanks)$", "", modifier_part).strip()

    # Skip if modifier_part is empty or too short
    if not modifier_part or len(modifier_part) < 2:
        return None

    logger.info(
        "MODIFY EXISTING ITEM: '%s' -> modifier=%s, target=%s",
        text[:50], modifier_part, target_description
    )

    return OpenInputResponse(
        modify_existing_item=True,
        modify_target_description=target_description,
        modify_add_modifiers=[modifier_part],
    )
