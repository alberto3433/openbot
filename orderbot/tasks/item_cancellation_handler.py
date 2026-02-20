"""
Item Cancellation Handler.

This module handles item and modifier cancellation operations including:
- Modifier removal: "remove the bacon", "no cheese"
- Last item removal: "cancel that", "remove it"
- All items removal: "cancel everything", "remove all"
- Reduce to one: "just one bagel", "only one"
- Ordinal removal: "remove the second bagel"
- Name-based removal: "cancel the coke", "remove the bagel"

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OpenInputResponse
from .handler_utils import check_has_active_items, build_removal_response
from .utils.text import normalize_text
from .item_removal_operations import ItemRemovalOperations

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


def extract_ordinal_reference(cancel_desc: str) -> tuple[int | None, str]:
    """Extract ordinal reference from cancellation description.

    Examples:
        "second bagel" -> (2, "bagel")
        "3rd coffee" -> (3, "coffee")
        "bagel 2" -> (2, "bagel")
        "coffee #3" -> (3, "coffee")
        "the bagel" -> (None, "bagel")

    Returns:
        Tuple of (ordinal_index, item_type_keyword).
        ordinal_index is 1-based (1st, 2nd, etc.) or None if no ordinal found.
    """
    import re
    from .parsers.selection_patterns import ORDINAL_WORDS

    desc_lower = normalize_text(cancel_desc)
    words = desc_lower.split()

    ordinal_index = None
    item_keyword = desc_lower

    for i, word in enumerate(words):
        # Check word-based ordinals (first, second, etc.)
        if word in ORDINAL_WORDS:
            ordinal_index = ORDINAL_WORDS[word]
            item_keyword = " ".join(words[i + 1:]) if i + 1 < len(words) else ""
            break

        # Check numeric ordinals (1st, 2nd, 3rd, etc.)
        ordinal_match = re.match(r"(\d+)(?:st|nd|rd|th)", word)
        if ordinal_match:
            ordinal_index = int(ordinal_match.group(1))
            item_keyword = " ".join(words[i + 1:]) if i + 1 < len(words) else ""
            break

    # Check for trailing number patterns: "bagel 2" or "coffee #3"
    if ordinal_index is None and len(words) >= 2:
        last_word = words[-1]
        # Match plain number or #number at end
        trailing_match = re.match(r"#?(\d+)$", last_word)
        if trailing_match:
            ordinal_index = int(trailing_match.group(1))
            item_keyword = " ".join(words[:-1])

    return ordinal_index, item_keyword.strip()


def find_nth_item_of_type(
    active_items: list,
    item_type_keyword: str,
    ordinal_index: int,
) -> tuple | None:
    """Find the Nth item of a specific type in the cart.

    Args:
        active_items: List of active items in the cart
        item_type_keyword: The type of item to find (e.g., "bagel", "coffee")
        ordinal_index: 1-based index (1 = first, 2 = second, etc.)

    Returns:
        Tuple of (item, actual_index) if found, None otherwise.
    """
    keyword_lower = item_type_keyword.lower()
    variants = get_singular_plural_variants(keyword_lower)

    # Also check if keyword maps to an item type
    mapped_type = None
    for variant in variants:
        category_mapping = menu_cache.get_category_keyword_mapping(variant)
        if category_mapping:
            mapped_type = category_mapping.get("slug")
            break

    count = 0
    for idx, item in enumerate(active_items):
        item_summary = item.get_summary().lower()
        item_name = (item.menu_item_name if isinstance(item, MenuItemTask) else '') or ''
        item_name_lower = item_name.lower()
        menu_item_type = (item.menu_item_type if isinstance(item, MenuItemTask) else '') or ''

        # Check for matches
        matches = False
        if any(v in item_summary for v in variants):
            matches = True
        elif item_name_lower and any(v in item_name_lower for v in variants):
            matches = True
        elif menu_item_type and any(v == menu_item_type for v in variants):
            matches = True
        elif mapped_type and menu_item_type == mapped_type:
            matches = True
        # Generic "item" or "one" matches any item
        elif keyword_lower in ("item", "items", "one", "thing", "things"):
            matches = True

        if matches:
            count += 1
            if count == ordinal_index:
                return (item, idx)

    return None


class ItemCancellationHandler:
    """
    Handles item and modifier cancellation operations.

    Manages removal of items and modifiers from the cart based on
    various user patterns like "cancel that", "remove the bacon", etc.
    """

    def __init__(
        self,
        pricing: "PricingEngine",
        configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the item cancellation handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
            configure_next_incomplete_item: Callback to get config question for incomplete items.
        """
        self.pricing = pricing
        self._configure_next_incomplete_item = configure_next_incomplete_item
        self._ops = ItemRemovalOperations(self)

    def _build_removal_response(
        self,
        order: OrderTask,
        removed_name: str,
        has_remaining_items: bool,
    ) -> StateMachineResult:
        """Build response after item removal, continuing config if needed."""
        return build_removal_response(
            order, removed_name, self._configure_next_incomplete_item
        )

    def handle_item_cancellation(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle item/modifier cancellation: 'cancel the coke', 'remove bacon', etc.

        Handles:
        - Modifier removal: "remove the bacon", "no cheese"
        - Last item removal: "cancel that", "remove it"
        - All items removal: "cancel everything", "remove all"
        - Reduce to one: "just one bagel", "only one"
        - Ordinal removal: "remove the second bagel"
        - Name-based removal: "cancel the coke", "remove the bagel"

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.cancel_item:
            return None

        active_items = order.items.get_active_items()

        # First, try modifier removal: "remove the bacon", "no cheese", etc.
        result = self._ops._try_modifier_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__last_item__" value for "cancel that", "remove it", etc.
        result = self._ops._try_last_item_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__all_items__" value for "remove all", "cancel everything", etc.
        result = self._ops._try_all_items_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__last_n_items_N__" value for "remove the last 2", etc.
        result = self._ops._try_last_n_items_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__reduce_to_one__" value for "just one bagel", "only one", etc.
        result = self._ops._try_reduce_to_one(parsed, order, active_items)
        if result:
            return result

        # Normal item cancellation by description
        if not active_items:
            logger.info("Cancellation requested but no items in cart")
            _, error = check_has_active_items(order)
            return error

        # Check for ordinal reference (e.g., "second bagel", "3rd coffee")
        result = self._ops._try_ordinal_removal(parsed, order, active_items)
        if result:
            return result

        # Name-based removal: "cancel the coke", "remove the bagel"
        return self._ops._try_name_based_removal(parsed, order, active_items)
