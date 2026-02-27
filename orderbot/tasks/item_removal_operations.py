"""
Item Removal Operations.

Concrete removal strategy methods extracted from ItemCancellationHandler.
Handles modifier removal, last item removal, all items removal,
reduce to one, ordinal removal, and name-based removal.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize, get_singular_plural_variants

from .models import OrderTask, MenuItemTask, TaskStatus
from .schemas import StateMachineResult, OpenInputResponse
from .checkout_messages import ok_removed_anything_else, ErrorMessages, item_not_found_in_order
from .handler_utils import (
    check_has_active_items,
    get_last_item,
    remove_item_from_order,
)
from .utils.text import normalize_text, strip_leading_article
from .modifier_operations import (
    find_modifier_on_any_item,
    remove_modifier_from_item,
    find_default_ingredient_on_any_item,
    remove_default_ingredient_from_item,
)
from .config.attribute_resolver import get_mandatory_attributes
from .utils.pricing_utils import safe_recalculate_price
from .parsers.quantity_utils import extract_leading_quantity
from .parsers.constants import (
    CANCEL_LAST_ITEM,
    CANCEL_ALL_ITEMS,
    REDUCE_TO_ONE,
    REDUCE_TO_ONE_PREFIX,
    parse_last_n_sentinel,
    parse_reduce_to_one_sentinel,
)

if TYPE_CHECKING:
    from .item_cancellation_handler import ItemCancellationHandler

logger = logging.getLogger(__name__)


class ItemRemovalOperations:
    """Concrete removal strategy methods for item cancellation."""

    def __init__(self, parent: "ItemCancellationHandler"):
        self._parent = parent

    def _try_modifier_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Try to remove a modifier from an item.

        Skip modifier removal if the cancel term matches an ITEM TYPE (e.g., "bagel").
        This prevents "remove the bagel" from removing the "plain_bagel" bread modifier
        instead of removing the bagel item from the cart.
        """
        if not active_items:
            return None

        # Check if cancel term matches an item type - if so, skip modifier removal
        # User wants to remove an item, not a modifier
        # Only skip if lookup_type is "item_type" (e.g., "bagel", "coffee")
        # Don't skip for lookup_type="category" (e.g., "cheese") - those should attempt modifier removal
        cancel_variants = get_singular_plural_variants(parsed.cancel_item)
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping and category_mapping.get("lookup_type") == "item_type":
                # Before skipping, check if any active item has a modifier matching
                # this term. E.g. "cheese" is an item_type, but if the cart has a
                # sandwich with cheese as a modifier, prefer modifier removal.
                if find_modifier_on_any_item(active_items, parsed.cancel_item):
                    break  # Don't skip — let modifier removal proceed below
                logger.info(
                    "Cancellation: '%s' matches item type '%s' - skipping modifier removal",
                    parsed.cancel_item, category_mapping.get("slug")
                )
                return None  # No modifier match — skip modifier removal

        # Check if cancel term matches a cart item's menu_item_name — if so, skip modifier
        # removal. Prevents "Remove the Ham Egg and Cheese Sandwich" from stripping "ham"
        # as a modifier instead of removing the whole item.
        cancel_lower = normalize_text(parsed.cancel_item)
        for item in active_items:
            item_name = (item.menu_item_name if isinstance(item, MenuItemTask) else '') or ''
            if item_name and item_name.lower() == cancel_lower:
                logger.info(
                    "Cancellation: '%s' matches cart item name '%s' - skipping modifier removal",
                    parsed.cancel_item, item_name,
                )
                return None

        # Check if cancel term matches a modifier CATEGORY (like "cream cheese" → spreads)
        # This handles "remove cream cheese" when the stored value is "blueberry" (the flavor)
        cancel_term_lower = normalize_text(parsed.cancel_item)
        # Normalize multiple spaces to single space (common voice transcription artifact)
        cancel_term_lower = ' '.join(cancel_term_lower.split())
        # Strip leading "the " if present
        cancel_term_lower = strip_leading_article(cancel_term_lower)

        modifier_category_slug = menu_cache.get_modifier_category_by_alias(cancel_term_lower)
        if modifier_category_slug:
            # Map modifier_category slug to attribute category
            # "spreads" → "spread" (remove trailing 's')
            attr_category = modifier_category_slug.rstrip('s') if modifier_category_slug.endswith('s') else modifier_category_slug

            for item in active_items:
                if isinstance(item, MenuItemTask) and item.get(attr_category):
                    removed_value = item.get(attr_category)
                    item.remove_selection(attr_category)
                    safe_recalculate_price(self._parent.pricing, item, "after removing category")

                    # Format display name from slug
                    from .normalization import format_slug_for_display
                    display_name = format_slug_for_display(str(removed_value), check_cache=False)
                    updated_summary = item.get_summary()
                    logger.info(
                        "Cancellation: removed %s category '%s' (value: '%s') via alias '%s'",
                        attr_category, modifier_category_slug, removed_value, cancel_term_lower
                    )
                    return StateMachineResult(
                        message=f"OK, I've removed the {display_name}. Your order is now {updated_summary}. Anything else?",
                        order=order,
                    )
            # No items had that category
            logger.debug("Cancellation: category '%s' matched but no items have that category", attr_category)

        modifier_match = find_modifier_on_any_item(active_items, parsed.cancel_item)
        if modifier_match:
            # If the match is on a required attribute and removing it would leave
            # the item with no filled mandatory attributes, the user is referring
            # to the item by its attribute (e.g., "remove one pound" means remove
            # the 1-lb item, not strip the weight attribute).
            if modifier_match.attribute_key and isinstance(modifier_match.item, MenuItemTask):
                item_type = modifier_match.item.menu_item_type
                if item_type:
                    mandatory_attrs = get_mandatory_attributes(item_type)
                    mandatory_slugs = {attr['slug'] for attr in mandatory_attrs}
                    if modifier_match.attribute_key in mandatory_slugs:
                        attr_values = modifier_match.item.attribute_values or {}
                        filled_mandatory = sum(
                            1 for slug in mandatory_slugs if slug in attr_values
                        )
                        if filled_mandatory <= 1:
                            removed_name = modifier_match.item.get_summary()
                            remove_item_from_order(order, modifier_match.item)
                            remaining = order.items.get_active_items()
                            logger.info(
                                "Cancellation: '%s' matched required attr '%s' on '%s' "
                                "- removing entire item (only %d mandatory filled)",
                                parsed.cancel_item, modifier_match.attribute_key,
                                removed_name, filled_mandatory,
                            )
                            return self._parent._build_removal_response(
                                order, removed_name, bool(remaining)
                            )

            result = remove_modifier_from_item(modifier_match.item, modifier_match)
            if result.success:
                safe_recalculate_price(self._parent.pricing, modifier_match.item, "after removing modifier")

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
        if parsed.cancel_item != CANCEL_LAST_ITEM or not active_items:
            return None

        last_item = get_last_item(active_items)
        removed_name = last_item.get_summary()
        remove_item_from_order(order, last_item)
        logger.info("Cancellation: removed last item from cart: %s", removed_name)

        remaining_items = order.items.get_active_items()
        return self._parent._build_removal_response(order, removed_name, bool(remaining_items))

    def _try_all_items_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove all', 'cancel everything', etc."""
        if parsed.cancel_item != CANCEL_ALL_ITEMS:
            return None

        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
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

    def _try_last_n_items_removal(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'remove the last 2', 'cancel last three items', etc."""
        count = parse_last_n_sentinel(parsed.cancel_item)
        if count is None:
            return None

        if not active_items:
            return StateMachineResult(
                message="Your order is empty. What would you like to order?",
                order=order,
            )

        # Can only remove up to the number of items we have
        actual_count = min(count, len(active_items))

        # Remove the last N items (from the end of the list)
        items_to_remove = active_items[-actual_count:]
        removed_names = []
        for item in items_to_remove:
            removed_names.append(item.get_summary())
            remove_item_from_order(order, item)

        logger.info("Cancellation: removed last %d items from cart: %s", actual_count, removed_names)

        remaining_items = order.items.get_active_items()

        if actual_count == 1:
            return self._parent._build_removal_response(order, removed_names[0], bool(remaining_items))

        if remaining_items:
            return StateMachineResult(
                message=f"OK, I've removed the last {actual_count} items. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"OK, I've removed the last {actual_count} items. What would you like to order?",
                order=order,
            )

    def _try_reduce_to_one(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        active_items: list,
    ) -> StateMachineResult | None:
        """Handle 'just one bagel', 'only one', etc."""
        if not parsed.cancel_item.startswith(REDUCE_TO_ONE_PREFIX):
            return None

        if not active_items:
            return StateMachineResult(
                message="Your order is empty. What would you like to order?",
                order=order,
            )

        item_type = None
        if parsed.cancel_item != REDUCE_TO_ONE:
            item_type = parse_reduce_to_one_sentinel(parsed.cancel_item)

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
                remove_item_from_order(order, item)
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
        from .item_cancellation_handler import extract_ordinal_reference, find_nth_item_of_type

        cancel_item_desc = parsed.cancel_item.lower()
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_item_desc)

        if ordinal_index is None or not item_type_keyword:
            return None

        result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
        if result:
            item_to_remove, _ = result
            removed_name = item_to_remove.get_summary()
            remove_item_from_order(order, item_to_remove)

            logger.info(
                "Cancellation: removed %s #%d from cart: %s",
                item_type_keyword, ordinal_index, removed_name
            )

            remaining_items = order.items.get_active_items()
            return self._parent._build_removal_response(order, removed_name, bool(remaining_items))
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

        # Check for leading quantity: "one iced latte" → decrement by 1
        is_decrement = False
        leading_qty, remainder = extract_leading_quantity(cancel_item_desc)
        if leading_qty == 1 and remainder:
            is_decrement = True
            cancel_item_desc = remainder

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
            item_name = (item.menu_item_name if isinstance(item, MenuItemTask) else '') or ''
            item_name_lower = item_name.lower()
            item_type = item.item_type or ''
            menu_item_type = (item.menu_item_type if isinstance(item, MenuItemTask) else '') or ''

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
            elif canonical_name_lower and canonical_name_lower == item_name_lower:
                matches = True
            else:
                # Fallback: check if ALL significant words from cancel description
                # appear in item summary. This is more restrictive than "any word"
                # to prevent "cinnamon babka" from matching "Chocolate Babka" (shares "babka").
                filler_words = {"the", "a", "an", "my", "that", "this"}
                significant_words = [
                    w for w in cancel_item_desc.split()
                    if w and w not in filler_words
                ]
                if significant_words and all(word in item_summary for word in significant_words):
                    matches = True

            if matches:
                items_to_remove.append(item)
                if not is_plural:
                    break

        if items_to_remove:
            # Quantity decrement: "Remove one X" with qty > 1 → just decrease quantity
            if is_decrement and len(items_to_remove) == 1:
                item = items_to_remove[0]
                if item.quantity > 1:
                    item.quantity -= 1
                    item_name = item.get_summary()
                    logger.info("Cancellation: decremented qty of '%s' to %d", item_name, item.quantity)
                    return StateMachineResult(
                        message=f"OK, removed one {item_name}. Anything else?",
                        order=order,
                    )
                # qty == 1: fall through to full removal below

            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                remove_item_from_order(order, item)

            logger.info("Cancellation: removed %d item(s) from cart: %s", len(removed_names), removed_names)

            remaining_items = order.items.get_active_items()

            # For single item removal, use helper to potentially continue configuration
            if len(removed_names) == 1:
                return self._parent._build_removal_response(order, removed_names[0], bool(remaining_items))

            # For multiple items, build message manually but still check for incomplete items
            removed_str = f"the {len(removed_names)} {singular_desc}s"
            if remaining_items and self._parent._configure_next_incomplete_item:
                for item in remaining_items:
                    if isinstance(item, MenuItemTask) and item.status == TaskStatus.IN_PROGRESS:
                        config_result = self._parent._configure_next_incomplete_item(order)
                        return StateMachineResult(
                            message=f"OK, I've removed {removed_str}. {config_result.message}",
                            order=order,
                        )

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
                message=item_not_found_in_order(parsed.cancel_item),
                order=order,
            )
