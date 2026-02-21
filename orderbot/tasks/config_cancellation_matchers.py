from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .parsers import CANCEL_ITEM_PATTERN, strip_conversational_fillers
from .modifier_resolver import TRAILING_FILLERS
from .models.utilities import parse_pending_field
from .utils.text import normalize_text
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants

if TYPE_CHECKING:
    from .models import OrderTask, MenuItemTask

logger = logging.getLogger(__name__)

# Pattern for "start over" / "start fresh" - clears entire order
START_OVER_PATTERN = re.compile(
    r"^(?:"
    r"start\s*over"
    r"|start\s*fresh"
    r"|let(?:'?s)?\s+start\s*over"
    r"|(?:can\s+)?(?:i|we)\s+start\s*over"
    r"|begin\s*again"
    r"|from\s+the\s+(?:beginning|start)"
    r")[\s!.,?]*$",
    re.IGNORECASE
)

# Pattern for standalone cancellation phrases (no target specified)
# During CONFIGURING_ITEM phase, these mean "cancel the current item being configured"
STANDALONE_CANCEL_PATTERN = re.compile(
    r"^(?:"
    r"cancel"
    r"|never\s*mind"
    r"|nevermind"
    r"|forget\s*it"
    r"|skip\s*(?:this|it)?"
    r"|(?:i\s+)?changed?\s*my\s*mind(?:,?\s*cancel)?"
    r"|(?:i\s+)?don'?t\s+want\s+(?:it|this)(?:\s+anymore)?"
    r")[\s!.,?]*$",
    re.IGNORECASE
)

# Pattern for abandoning the entire order during TAKING_ITEMS phase.
# These phrases express whole-order cancellation intent (not single-item removal).
# Matches: "I changed my mind", "never mind", "forget it", "cancel", etc.
CANCEL_ORDER_PATTERN = re.compile(
    r"^(?:"
    r"(?:i\s+)?changed?\s*my\s*mind(?:,?\s*(?:cancel|never\s*mind|nevermind))?"
    r"|never\s*mind(?:,?\s*cancel)?"
    r"|nevermind(?:,?\s*cancel)?"
    r"|forget\s*(?:it|about\s+it)"
    r"|cancel"
    r"|(?:i\s+)?don'?t\s+want\s+(?:anything|to\s+order)(?:\s+(?:anymore|any\s*more))?"
    r")[\s!.,?]*$",
    re.IGNORECASE
)


def _extract_modifier_and_item_reference(cancel_desc: str) -> tuple[str, str] | None:
    """Extract modifier and item reference from phrases like 'onions on the leo'.

    Patterns handled:
    - "X on the Y" / "X on Y"
    - "X from the Y" / "X from Y"
    - "X off the Y" / "X off Y"
    - "X off of the Y" / "X off of Y"

    Returns:
        Tuple of (modifier, item_reference) if pattern matches, None otherwise
    """
    # Pattern: modifier + separator + optional "the"/"my" + item reference
    pattern = r'^(.+?)\s+(?:on|from|off(?:\s+of)?)\s+(?:the\s+|my\s+)?(.+)$'
    match = re.match(pattern, cancel_desc, re.IGNORECASE)
    if match:
        modifier = match.group(1).strip()
        item_ref = match.group(2).strip()
        # Ensure both parts are non-empty
        if modifier and item_ref:
            return (modifier, item_ref)
    return None


def _get_removable_modifiers() -> set[str]:
    """Get the set of removable modifier names from the database.

    Uses the ingredient_categories table to determine which ingredient categories
    are "food" modifiers, then combines all ingredients from those categories.
    This is fully data-driven - no hardcoded category names.

    Raises:
        MenuDataNotLoadedError: If menu cache is not loaded or no food categories
            are configured in ingredient_categories table.
    """
    from orderbot.exceptions import MenuDataNotLoadedError

    modifiers: set[str] = set()

    # Get all food modifier ingredient categories from database
    # This is data-driven: ingredient_categories table defines which categories
    # are "food" modifiers (protein, topping, sauce, cheese, spread, etc.)
    food_categories = menu_cache.get_ingredient_categories_by_modifier_type("food")

    if not food_categories:
        raise MenuDataNotLoadedError(
            "No food modifier categories found in database. "
            "Check that ingredient_categories table has entries with modifier_type='food'."
        )

    # Combine all ingredients from food modifier categories
    for category in food_categories:
        modifiers.update(menu_cache.get_ingredients(category))

    # Also include all modifier aliases from the database
    # This covers variations like "egg" vs "eggs", "mayo" vs "mayonnaise", etc.
    modifiers.update(menu_cache.get_all_modifier_words())

    return modifiers


def _item_matches(
    item: "MenuItemTask",
    cancel_variants: list[str],
    cancel_desc: str,
    mapped_item_type: str | None,
) -> bool:
    """Check if an item matches the cancellation description."""
    item_summary = item.get_summary().lower()
    item_name = item.menu_item_name or ''
    item_name_lower = item_name.lower()
    item_type = item.item_type or ''
    menu_item_type = item.menu_item_type or ''

    if any(v in item_summary for v in cancel_variants):
        return True
    if item_name_lower and any(v in item_name_lower for v in cancel_variants):
        return True
    if item_name_lower and item_name_lower in cancel_desc:
        return True
    if item_type and any(v == item_type for v in cancel_variants):
        return True
    if menu_item_type and any(v == menu_item_type for v in cancel_variants):
        return True
    if mapped_item_type and menu_item_type == mapped_item_type:
        return True
    return False


def _extract_cancel_description(user_input_stripped: str) -> str | None:
    """Extract the cancel target from user input.

    Matches STANDALONE_CANCEL_PATTERN (-> "this") or CANCEL_ITEM_PATTERN
    (-> extracted description). Returns None if no cancel intent detected.
    """
    if STANDALONE_CANCEL_PATTERN.match(user_input_stripped):
        logger.info("Standalone cancel during config: '%s'", user_input_stripped)
        return "this"

    cancel_match = CANCEL_ITEM_PATTERN.match(user_input_stripped)
    if not cancel_match:
        return None

    cancel_desc = None
    for group in cancel_match.groups():
        if group:
            cancel_desc = normalize_text(group)
            break
    if not cancel_desc:
        return None

    # Strip trailing pleasantries ("thank you", "thanks", "please")
    for filler in TRAILING_FILLERS:
        if cancel_desc.endswith(filler.strip()):
            cancel_desc = cancel_desc[:-len(filler.strip())].strip()
            break

    return cancel_desc


def _should_defer_to_attribute_handler(cancel_desc: str, order: "OrderTask") -> bool:
    """Check if cancel_desc matches the pending attribute slug.

    If so, this is a decline/skip ("no cheese" during cheese config means
    "I don't want cheese"), not an item removal. Returns True to defer.
    """
    _, pending_attr_slug = parse_pending_field(order.pending_field)
    if not pending_attr_slug:
        return False

    cancel_variants = get_singular_plural_variants(cancel_desc)
    # Check if cancel_desc words overlap with the slug's word components
    # (e.g., "shots" matches "espresso_shots" via the "shots" component)
    attr_slug_parts = set(pending_attr_slug.split("_"))
    if (pending_attr_slug in cancel_variants
            or cancel_desc == pending_attr_slug
            or set(cancel_variants) & attr_slug_parts):
        logger.info(
            "Cancel during config: '%s' matches pending attribute '%s' - "
            "deferring to attribute handler",
            cancel_desc, pending_attr_slug,
        )
        return True
    return False


def _cancel_matches_item_or_type(
    cancel_desc: str, order: "OrderTask",
) -> tuple[bool, bool]:
    """Check if cancel_desc matches an item type name or an item's base name.

    Returns (matches_item_type, matches_item_in_order). When either is True,
    modifier removal should be skipped -- the user wants to remove items.
    """
    from .models import MenuItemTask

    cancel_variants = get_singular_plural_variants(cancel_desc)

    matches_item_type = False
    for variant in cancel_variants:
        category_mapping = menu_cache.get_category_keyword_mapping(variant)
        if category_mapping:
            matches_item_type = True
            logger.info(
                "Cancel during config: '%s' matches item type '%s' - skipping modifier removal",
                cancel_desc, category_mapping.get("slug")
            )
            break

    # Check against item BASE NAMES only (not full summary which includes modifiers)
    matches_item_in_order = False
    cancel_desc_lower = cancel_desc.lower()
    for item in order.items.get_active_items():
        if not isinstance(item, MenuItemTask):
            continue
        item_name = (item.menu_item_name or "").lower()
        if item_name and (cancel_desc_lower in item_name or item_name in cancel_desc_lower):
            matches_item_in_order = True
            logger.info(
                "Cancel during config: '%s' matches item name '%s' - skipping modifier removal",
                cancel_desc, item_name
            )
            break

    return matches_item_type, matches_item_in_order
