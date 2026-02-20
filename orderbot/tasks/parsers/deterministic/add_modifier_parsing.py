"""
Add-Modifier-to-Item Pattern Detection Pipeline.

Functions for detecting requests to add modifiers to an existing item,
e.g. "add bacon", "extra cheese", "put mayo on it".
"""
from __future__ import annotations

import re
import logging

from orderbot.cache import menu_cache

from ...schemas import (
    OpenInputResponse,
    QualifierConflict,
)

from .extraction import extract_modifiers_with_qualifiers

logger = logging.getLogger(__name__)


def _match_modifier_before_target(text_lower: str) -> tuple[str | None, str | None]:
    """Match "add/put MODIFIER to/on the TARGET" patterns.

    Returns (modifier_text, target_item) or (None, None) if no match.
    """
    target_patterns = [
        # "add bacon to the bagel" / "add bacon to the plain bagel"
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the|my)\s+(.+?)$",
        # "add milk to tea" - single-word target, no article required
        # Using (\w+)$ to capture only single-word targets, avoiding false positives
        # like "add milk to my order". Excludes "it" which is handled by implicit patterns.
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?!it\b)(\w+)$",
    ]

    for pattern in target_patterns:
        match = re.match(pattern, text_lower)
        if match:
            return match.group(1).strip(), match.group(2).strip()

    return None, None


def _match_modifier_no_target(text_lower: str) -> str | None:
    """Match "add/extra/more MODIFIER" patterns with no explicit target.

    Returns modifier_text or None if no match.
    """
    no_target_patterns = [
        # "add bacon" / "add bacon and cheese"
        r"^(?:add|put)\s+(.+?)(?:\s+please)?$",
        # "extra bacon" / "extra cheese"
        r"^extra\s+(.+?)(?:\s+please)?$",
        # "more bacon" / "more cheese"
        r"^more\s+(.+?)(?:\s+please)?$",
    ]

    for pattern in no_target_patterns:
        match = re.match(pattern, text_lower)
        if match:
            return match.group(1).strip()

    return None


def _match_modifier_implicit_target(text_lower: str) -> str | None:
    """Match "put MODIFIER on it" patterns with implicit target.

    Returns modifier_text or None if no match.
    """
    match = re.match(r"^put\s+(.+?)\s+on\s+it(?:\s+please)?$", text_lower)
    if match:
        return match.group(1).strip()
    return None


def _parse_add_modifier_to_item(text: str) -> OpenInputResponse | None:
    """Detect requests to add modifiers to an existing item.

    Catches patterns like:
    - "add X" - add single modifier to current/last item
    - "add X and Y" - add multiple modifiers
    - "add X to the Y" - add modifier to specific item
    - "extra X" / "more X" - alternative action words
    - "put X on it" - implicit target

    Does NOT catch patterns where the modifier text matches a known menu item
    (e.g., if "bacon egg and cheese" is a menu item alias, "add bacon egg and cheese"
    will be treated as a menu item order, not a modifier-add request).

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    # Get known modifiers from all ingredient categories (database-driven)
    # Include both food and beverage modifiers (milk, sugar, syrup, etc.)
    all_modifiers: set[str] = set()
    for category in menu_cache.get_all_ingredient_categories():
        ingredients = menu_cache.get_ingredients(category)
        all_modifiers.update(ingredients)

    # Try each pattern group in order: modifier-before-target, no-target, implicit-target
    modifier_text, target_item = _match_modifier_before_target(text_lower)

    if not modifier_text:
        modifier_text = _match_modifier_no_target(text_lower)
        target_item = None

    if not modifier_text:
        modifier_text = _match_modifier_implicit_target(text_lower)
        target_item = None

    # No pattern matched
    if not modifier_text:
        return None

    # Check if modifier_text matches a known menu item (e.g., "bacon egg and cheese")
    # If so, this is likely a menu item order, not a modifier-add request.
    # Only skip if the menu item match covers most of the modifier_text - we don't want
    # to skip "add bacon and cheese" just because "bacon" is also a menu item.
    if len(modifier_text.split()) > 1:
        from .modification_parsing import _extract_menu_item_from_text
        menu_item, _, _ = _extract_menu_item_from_text(modifier_text)
        if menu_item:
            # Only skip if the menu item name covers most of the modifier text
            # This prevents "bacon and cheese" from being skipped because "bacon" matches
            menu_item_lower = menu_item.lower()
            modifier_text_lower = modifier_text.lower()
            # Check if menu item name is a significant portion of the modifier text
            if len(menu_item_lower) >= len(modifier_text_lower) * 0.7:
                logger.debug("ADD MODIFIER: '%s' matches menu item '%s', skipping", modifier_text, menu_item)
                return None

    # Check if modifier_text contains an item type trigger (e.g., "a latte with milk")
    # If so, this is a new item order, not a modifier-add request.
    # BUT: only skip if the trigger word is NOT also a known modifier (e.g., "bacon"
    # is both an omelette trigger and a valid modifier to add to items).
    # Import here to avoid circular imports
    from .item_parsing import _detect_item_type
    detected_item_type, detected_trigger = _detect_item_type(modifier_text)
    # Get all ingredient categories (used below and later for category name matching)
    all_categories = menu_cache.get_all_ingredient_categories()
    if detected_item_type and detected_trigger:
        # Only treat as new item if the trigger word is NOT a known modifier
        # AND is NOT an ingredient category name (e.g., "cheese" is both an item type
        # and a modifier category - should be treated as modifier request)
        trigger_lower = detected_trigger.lower()
        if trigger_lower not in all_modifiers and trigger_lower not in all_categories:
            logger.debug(
                "ADD MODIFIER: '%s' contains item type '%s' (trigger='%s'), treating as new item order",
                modifier_text, detected_item_type, detected_trigger
            )
            return None

    # === Parse modifier_text to extract individual modifiers with qualifiers ===
    # Handle "extra bacon and cheese on the side", "bacon, cheese, and tomato", etc.

    # Extract modifiers with qualifiers (e.g., "extra mayo" -> "mayo (extra)")
    modifiers_found, conflicts = extract_modifiers_with_qualifiers(
        modifier_text.lower(),
        all_modifiers
    )

    # Also check for category names (e.g., "cheese" in "add bacon and cheese")
    # This handles cases where "cheese" is a category name, not a specific ingredient
    # (all_categories was loaded earlier, includes food + beverage categories like "milk")
    modifier_words = modifier_text.lower().split()
    for word in modifier_words:
        word_clean = word.strip(",;").strip()
        if word_clean in all_categories:
            # Found a category name - add it to modifiers if not already there
            category_title = word_clean.title()
            if category_title not in modifiers_found:
                modifiers_found.append(category_title)
                logger.debug("ADD MODIFIER: added category '%s' to modifiers", category_title)

    # If no known modifiers found (including categories), this isn't a modify request
    if not modifiers_found:
        return None

    # Clean up target_item if present (remove trailing "please", "thanks", etc.)
    if target_item:
        target_item = re.sub(r"\s*(please|thanks|thank you)$", "", target_item).strip()

    logger.info(
        "ADD MODIFIER TO ITEM: '%s' -> modifiers=%s, target=%s, conflicts=%s",
        text[:50], modifiers_found, target_item, conflicts
    )

    # Convert conflict tuples to QualifierConflict objects
    conflict_objects = None
    if conflicts:
        conflict_objects = [
            QualifierConflict(modifier=mod, qualifier1=q1, qualifier2=q2)
            for mod, q1, q2 in conflicts
        ]

    return OpenInputResponse(
        modify_existing_item=True,
        modify_target_description=target_item,
        modify_add_modifiers=modifiers_found,
        modify_qualifier_conflicts=conflict_objects,
    )
