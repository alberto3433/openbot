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
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache
from orderbot.cache.base import singularize, get_singular_plural_variants

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OpenInputResponse
from .checkout_messages import ok_removed_anything_else
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


def extract_ordinal_reference(cancel_desc: str) -> tuple[int | None, str]:
    """Extract ordinal reference from cancellation description.

    Examples:
        "second bagel" -> (2, "bagel")
        "3rd coffee" -> (3, "coffee")
        "the bagel" -> (None, "bagel")

    Returns:
        Tuple of (ordinal_index, item_type_keyword).
        ordinal_index is 1-based (1st, 2nd, etc.) or None if no ordinal found.
    """
    from .parsers.constants import ORDINAL_WORDS

    desc_lower = cancel_desc.lower().strip()
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
        import re
        ordinal_match = re.match(r"(\d+)(?:st|nd|rd|th)", word)
        if ordinal_match:
            ordinal_index = int(ordinal_match.group(1))
            item_keyword = " ".join(words[i + 1:]) if i + 1 < len(words) else ""
            break

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
        item_name = getattr(item, 'menu_item_name', '') or ''
        item_name_lower = item_name.lower()
        menu_item_type = getattr(item, 'menu_item_type', '') or ''

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

    def __init__(self, pricing: "PricingEngine"):
        """
        Initialize the item cancellation handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
        """
        self.pricing = pricing

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
        result = self._try_modifier_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__last_item__" value for "cancel that", "remove it", etc.
        result = self._try_last_item_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__all_items__" value for "remove all", "cancel everything", etc.
        result = self._try_all_items_removal(parsed, order, active_items)
        if result:
            return result

        # Handle special "__reduce_to_one__" value for "just one bagel", "only one", etc.
        result = self._try_reduce_to_one(parsed, order, active_items)
        if result:
            return result

        # Normal item cancellation by description
        if not active_items:
            logger.info("Cancellation requested but no items in cart")
            return StateMachineResult(
                message="There's nothing in your order yet. What can I get for you?",
                order=order,
            )

        # Check for ordinal reference (e.g., "second bagel", "3rd coffee")
        result = self._try_ordinal_removal(parsed, order, active_items)
        if result:
            return result

        # Name-based removal: "cancel the coke", "remove the bagel"
        return self._try_name_based_removal(parsed, order, active_items)

    def _try_modifier_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Try to remove a modifier from an item."""
        if not active_items:
            return None

        modifier_match = find_modifier_on_any_item(active_items, parsed.cancel_item)
        if modifier_match:
            result = remove_modifier_from_item(modifier_match.item, modifier_match)
            if result.success:
                try:
                    self.pricing.recalculate_item_price(modifier_match.item)
                except ValueError:
                    pass  # Price lookup failed - item may not have pricing data

                updated_summary = modifier_match.item.get_summary()
                return StateMachineResult(
                    message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                    order=order,
                )
        else:
            # Check if it's a default ingredient of a signature/menu item
            default_match = find_default_ingredient_on_any_item(active_items, parsed.cancel_item)
            if default_match:
                result = remove_default_ingredient_from_item(default_match.item, default_match)
                if result.success:
                    updated_summary = default_match.item.get_summary()
                    return StateMachineResult(
                        message=f"{result.message} Your order is now {updated_summary}. Anything else?",
                        order=order,
                    )

        return None

    def _try_last_item_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'cancel that', 'remove it', etc."""
        if parsed.cancel_item != "__last_item__" or not active_items:
            return None

        last_item = active_items[-1]
        removed_name = last_item.get_summary()
        idx = order.items.items.index(last_item)
        order.items.remove_item(idx)
        logger.info("Cancellation: removed last item from cart: %s", removed_name)

        remaining_items = order.items.get_active_items()
        if remaining_items:
            return StateMachineResult(
                message=ok_removed_anything_else(removed_name),
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"OK, I've removed the {removed_name}. What would you like to order?",
                order=order,
            )

    def _try_all_items_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove all', 'cancel everything', etc."""
        if parsed.cancel_item != "__all_items__":
            return None

        if active_items:
            num_items = len(active_items)
            for item in active_items:
                idx = order.items.items.index(item)
                order.items.remove_item(idx)
            logger.info("Cancellation: removed ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, I've cleared your order. What would you like to order?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="Your order is already empty. What would you like to order?",
                order=order,
            )

    def _try_reduce_to_one(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'just one bagel', 'only one', etc."""
        if not parsed.cancel_item.startswith("__reduce_to_one"):
            return None

        if not active_items:
            return StateMachineResult(
                message="Your order is empty. What would you like to order?",
                order=order,
            )

        item_type = None
        if parsed.cancel_item != "__reduce_to_one__":
            parts = parsed.cancel_item.replace("__", "").replace("reduce_to_one_", "")
            if parts:
                item_type = parts.strip()

        items_to_check = active_items
        if item_type:
            type_attrs = menu_cache.get_item_type_attributes(item_type)
            if type_attrs:
                primary_attr = type_attrs[0] if type_attrs else None
                if primary_attr:
                    items_to_check = [
                        i for i in active_items
                        if isinstance(i, MenuItemTask) and i.has_attribute(primary_attr)
                    ]
                else:
                    items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]
            else:
                items_to_check = [i for i in active_items if isinstance(i, MenuItemTask)]

        if len(items_to_check) > 1:
            items_to_remove = items_to_check[1:]
            removed_count = 0
            removed_names = []
            for item in items_to_remove:
                removed_name = item.get_summary()
                idx = order.items.items.index(item)
                order.items.remove_item(idx)
                removed_count += 1
                removed_names.append(removed_name)

            kept_item = items_to_check[0].get_summary()
            logger.info(
                "Reduce to one: kept '%s', removed %d items: %s",
                kept_item, removed_count, removed_names
            )

            if removed_count == 1:
                return StateMachineResult(
                    message=f"OK, I've removed the extra {item_type or 'item'}. You have {kept_item}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_count} items. You have {kept_item}. Anything else?",
                    order=order,
                )
        elif len(items_to_check) == 1:
            kept_item = items_to_check[0].get_summary()
            return StateMachineResult(
                message=f"You already have just one {item_type or 'item'}: {kept_item}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"I don't see any {item_type or 'items'} in your order. What would you like?",
                order=order,
            )

    def _try_ordinal_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove the second bagel', '3rd coffee', etc."""
        cancel_item_desc = parsed.cancel_item.lower()
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_item_desc)

        if ordinal_index is None or not item_type_keyword:
            return None

        result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
        if result:
            item_to_remove, _ = result
            removed_name = item_to_remove.get_summary()
            idx = order.items.items.index(item_to_remove)
            order.items.remove_item(idx)

            logger.info(
                "Cancellation: removed %s #%d from cart: %s",
                item_type_keyword, ordinal_index, removed_name
            )

            remaining_items = order.items.get_active_items()
            if remaining_items:
                return StateMachineResult(
                    message=ok_removed_anything_else(removed_name),
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed the {removed_name}. What would you like to order?",
                    order=order,
                )
        else:
            logger.info(
                "Cancellation: couldn't find %s #%d in cart",
                item_type_keyword, ordinal_index
            )
            if item_type_keyword.lower() in ("item", "items", "one", "thing"):
                not_found_msg = f"I couldn't find item #{ordinal_index} in your order."
            else:
                not_found_msg = f"I couldn't find a {item_type_keyword} #{ordinal_index} in your order."
            return StateMachineResult(
                message=f"{not_found_msg} What would you like to do?",
                order=order,
            )

    def _try_name_based_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult:
        """Handle name-based removal: 'cancel the coke', 'remove the bagel'."""
        cancel_item_desc = parsed.cancel_item.lower()

        # Check if plural removal (e.g., "coffees", "bagels")
        singular_desc = singularize(cancel_item_desc)
        is_plural = singular_desc != cancel_item_desc.lower()

        # Get all variants for matching
        cancel_variants = get_singular_plural_variants(cancel_item_desc)

        # Map user category terms to item_type via database
        mapped_item_type = None
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping:
                mapped_item_type = category_mapping.get("slug")
                break

        # Resolve aliases to canonical names
        resolved_name, _ = menu_cache.resolve_alias(singular_desc)
        canonical_name_lower = resolved_name.lower() if resolved_name else None

        # Find matching items
        items_to_remove = []
        for item in reversed(active_items):
            item_summary = item.get_summary().lower()
            item_name = getattr(item, 'menu_item_name', '') or ''
            item_name_lower = item_name.lower()
            item_type = getattr(item, 'item_type', '') or ''
            menu_item_type = getattr(item, 'menu_item_type', '') or ''

            # Check for matches using all variants
            matches = False
            if any(v in item_summary for v in cancel_variants):
                matches = True
            elif item_name_lower and any(v in item_name_lower for v in cancel_variants):
                matches = True
            elif item_name_lower and item_name_lower in cancel_item_desc:
                matches = True
            elif item_type and any(v == item_type for v in cancel_variants):
                matches = True
            elif menu_item_type and any(v == menu_item_type for v in cancel_variants):
                matches = True
            elif mapped_item_type and menu_item_type == mapped_item_type:
                matches = True
            elif any(word in item_summary for word in cancel_item_desc.split() if word):
                matches = True
            elif canonical_name_lower and canonical_name_lower == item_name_lower:
                matches = True

            if matches:
                items_to_remove.append(item)
                if not is_plural:
                    break

        if items_to_remove:
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                idx = order.items.items.index(item)
                order.items.remove_item(idx)

            if len(removed_names) == 1:
                removed_str = f"the {removed_names[0]}"
            else:
                removed_str = f"the {len(removed_names)} {singular_desc}s"

            logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

            remaining_items = order.items.get_active_items()
            if remaining_items:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. Anything else?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"OK, I've removed {removed_str}. What would you like to order?",
                    order=order,
                )
        else:
            logger.info("Cancellation: couldn't find item matching '%s'", cancel_item_desc)
            return StateMachineResult(
                message=f"I couldn't find {parsed.cancel_item} in your order. What would you like to do?",
                order=order,
            )
