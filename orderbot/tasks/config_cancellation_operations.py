from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import OrderPhase, StateMachineResult
from .handler_utils import check_has_active_items, remove_item_from_order, build_removal_response
from .item_cancellation_handler import extract_ordinal_reference, find_nth_item_of_type
from .modifier_operations import (
    find_modifier_match,
    remove_modifier_from_item,
    find_default_ingredient_match,
    remove_default_ingredient_from_item,
)
from .normalization import format_slug_for_display
from .parsers.quantity_utils import extract_leading_quantity
from orderbot.cache import menu_cache
from orderbot.cache.base import get_singular_plural_variants, singularize
from orderbot.exceptions import MenuDataNotLoadedError
from .checkout_messages import ok_removed_anything_else, item_not_found_in_order
from .utils.pricing_utils import safe_recalculate_price
from .utils.text import name_with_prefix
from .config_cancellation_matchers import (
    _extract_modifier_and_item_reference,
    _get_removable_modifiers,
    _item_matches,
)

if TYPE_CHECKING:
    from .config_cancellation_handler import ConfigCancellationHandler

logger = logging.getLogger(__name__)


class ConfigCancellationOperations:

    def __init__(self, parent: 'ConfigCancellationHandler') -> None:
        self._parent = parent

    def _handle_start_over(self, order: OrderTask) -> StateMachineResult:
        """Clear all items and return to TAKING_ITEMS phase."""
        active_items = order.items.get_active_items()
        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            logger.info("Start over: cleared ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, let's start over. What would you like to order?",
                order=order,
            )
        return StateMachineResult(
            message="Your order is already empty. What would you like to order?",
            order=order,
        )

    def _try_remove_attribute_by_name(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        *,
        defer_if_unset: bool = False,
    ) -> StateMachineResult | None:
        """Try to match cancel_desc to an attribute name and remove its value.

        Args:
            cancel_desc: Normalized cancellation description.
            current_item: The item currently being configured.
            order: The current order task.
            defer_if_unset: If True and attribute matches but has no value,
                return None (defer to another handler). Used at customization checkpoint.

        Returns:
            StateMachineResult if attribute was removed, None to continue.
        """
        item_type_attrs = menu_cache.get_item_type_attributes(current_item.menu_item_type)
        cancel_variants = get_singular_plural_variants(cancel_desc)
        for attr_slug, attr_data in item_type_attrs.items():
            attr_display_lower = (attr_data.get("display_name") or "").lower()
            if attr_slug in cancel_variants or attr_display_lower in cancel_variants:
                current_value = current_item.attribute_values.get(attr_slug)
                if current_value is not None:
                    current_item[attr_slug] = None
                    safe_recalculate_price(
                        self._parent.pricing, current_item, "after attribute removal via cancel"
                    )
                    display_name = (
                        attr_data.get("display_name") or format_slug_for_display(attr_slug)
                    )
                    logger.info(
                        "Removed attribute '%s' from %s during config",
                        attr_slug, current_item.menu_item_name,
                    )
                    return self._config_removal_response(
                        f"OK, I've removed the {display_name}.",
                        order, current_item,
                        ok_removed_anything_else(display_name),
                    )
                if defer_if_unset:
                    logger.info(
                        "Cancel during config: '%s' matches attribute '%s' at customization "
                        "checkpoint - deferring to checkpoint handler",
                        cancel_desc, attr_slug,
                    )
                    return None
        return None

    def _try_cancel_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'cancel this/it/that' -- remove the current item."""
        if cancel_desc not in ("this", "it", "that", "this one", "that one"):
            return None

        item_name = current_item.get_summary()
        current_item.mark_skipped()
        order.clear_pending()
        order.set_phase(OrderPhase.TAKING_ITEMS)
        return build_removal_response(
            order, item_name, self._parent._configure_next_incomplete_item
        )

    def _try_cancel_all_items(
        self,
        cancel_desc: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'cancel everything/all' -- clear entire order."""
        all_items_phrases = {
            "all", "everything", "all of it", "the order", "my order",
            "the whole order", "my whole order", "all items", "all the items",
            "the whole thing", "it all", "them all",
            "order", "whole order", "whole thing"
        }
        if cancel_desc.lower() not in all_items_phrases:
            return None

        active_items = order.items.get_active_items()
        if active_items:
            num_items = len(active_items)
            for item in active_items:
                remove_item_from_order(order, item)
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)
            logger.info("Cancel during config: cleared ALL %d items from cart", num_items)
            return StateMachineResult(
                message="OK, I've cleared your order. What would you like to order?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="Your order is already empty. What would you like to order?",
                order=order,
            )

    def _try_remove_modifier_by_reference(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Try to remove a modifier using "X on/from Y" pattern.

        Handles phrases like "remove onions from the leo" by parsing the modifier
        and item reference, finding the target item, and attempting modifier removal
        followed by default ingredient removal.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.

        Returns:
            StateMachineResult if modifier was removed, None to continue with
            other checks.
        """
        # First, try to parse "modifier on/from item" pattern (e.g., "onions on the leo")
        modifier_item_parsed = _extract_modifier_and_item_reference(cancel_desc)
        if modifier_item_parsed:
            modifier_part, item_ref = modifier_item_parsed
            logger.info(
                "Parsed modifier removal: modifier='%s', item_ref='%s'",
                modifier_part, item_ref
            )

            # Find the referenced item in the order
            target_item = None
            active_items = order.items.get_active_items()
            item_ref_lower = item_ref.lower()

            for item in active_items:
                if not isinstance(item, MenuItemTask):
                    continue
                item_name = (item.menu_item_name or "").lower()
                item_summary = item.get_summary().lower()
                # Match if item_ref appears in item name or summary
                if item_ref_lower in item_name or item_ref_lower in item_summary:
                    target_item = item
                    break

            if target_item:
                # Try modifier removal on the target item
                try:
                    modifier_match = find_modifier_match(target_item, modifier_part)
                    if modifier_match:
                        removal_result = remove_modifier_from_item(target_item, modifier_match)
                        if removal_result.success:
                            # Recalculate price after modifier removal
                            safe_recalculate_price(
                                self._parent.pricing, target_item, "after modifier removal via X on Y pattern"
                            )
                            removed_name = format_slug_for_display(removal_result.removed_value or modifier_part)
                            logger.info(
                                "Removed '%s' from '%s' via 'X on Y' pattern",
                                removed_name, target_item.menu_item_name
                            )
                            item_with_prefix = name_with_prefix("your", target_item.menu_item_name)
                            return self._config_removal_response(
                                f"OK, I've removed the {removed_name} from {item_with_prefix}.",
                                order, current_item,
                                f"OK, I've removed the {removed_name} from {item_with_prefix}. Anything else?",
                            )
                except MenuDataNotLoadedError:
                    pass  # Fall through to try default ingredient removal

                # Also try default ingredient removal for the modifier part
                default_match = find_default_ingredient_match(target_item, modifier_part)
                if default_match:
                    removal_result = remove_default_ingredient_from_item(target_item, default_match)
                    if removal_result.success:
                        # Note: Default ingredient removal doesn't affect price (already included)
                        removed_name = format_slug_for_display(removal_result.removed_value or modifier_part)
                        logger.info(
                            "Removed default ingredient '%s' from '%s' via 'X on Y' pattern",
                            removed_name, target_item.menu_item_name
                        )
                        item_with_prefix = name_with_prefix("your", target_item.menu_item_name)
                        return self._config_removal_response(
                            f"OK, I've removed the {removed_name} from {item_with_prefix}.",
                            order, current_item,
                            f"OK, I've removed the {removed_name} from {item_with_prefix}. Anything else?",
                        )
            # If pattern matched but no item found or no modifier found, fall through to existing logic

        return None

    def _try_remove_modifier_on_current_item(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
        matches_item_type: bool,
        matches_item_in_order: bool,
    ) -> StateMachineResult | None:
        """Try to remove a modifier from the current item being configured.

        Uses unified modifier_operations for consistent handling, with a legacy
        fallback using the removable_modifiers set. Supports quantity-aware
        removal (e.g., "remove 1 shot" decrements by 1).

        Skipped entirely if cancel_desc matches an item type or item name in the
        order, since the user likely wants to remove the item itself, not a modifier.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.
            matches_item_type: Whether cancel_desc matches a known item type.
            matches_item_in_order: Whether cancel_desc matches an item name in order.

        Returns:
            StateMachineResult if modifier was removed, None to continue with
            other checks.
        """
        # Check if this is a modifier removal on the current item being configured
        # Use unified modifier_operations for consistent handling
        # But SKIP if cancel_desc matches an item type or item in order (user wants to remove items, not modifiers)
        if isinstance(current_item, MenuItemTask) and not matches_item_type and not matches_item_in_order:
            # Extract leading quantity from cancel_desc (e.g., "1 shot" -> (1, "shot"))
            # This enables quantity-aware removal: "remove 1 shot" decrements by 1
            removal_qty, modifier_term = extract_leading_quantity(cancel_desc)
            # If no quantity found, use the full cancel_desc for matching
            if removal_qty is None:
                modifier_term = cancel_desc

            try:
                modifier_match = find_modifier_match(current_item, modifier_term)
                # If direct match fails, resolve via ingredient DB lookup
                # (e.g., "jalapeno spread" -> "Jalapeno Cream Cheese" -> match on item)
                if not modifier_match:
                    ingredient_matches = menu_cache.find_matching_ingredients(modifier_term)
                    if len(ingredient_matches) == 1:
                        resolved_name = ingredient_matches[0].get("slug", "").replace("_", " ")
                        if resolved_name:
                            modifier_match = find_modifier_match(current_item, resolved_name)
                if modifier_match:
                    removal_result = remove_modifier_from_item(
                        current_item, modifier_match, quantity=removal_qty
                    )
                    if removal_result.success:
                        # Recalculate price after modifier removal/decrement
                        safe_recalculate_price(
                            self._parent.pricing, current_item, "after modifier removal during config"
                        )

                        removed_modifier_name = format_slug_for_display(removal_result.removed_value or modifier_term)
                        logger.info(
                            "Modifier removal during config: removed '%s' (qty=%s) from %s",
                            removed_modifier_name, removal_qty, current_item.menu_item_name
                        )

                        updated_summary = current_item.get_summary()
                        return self._config_removal_response(
                            removal_result.message, order, current_item,
                            f"{removal_result.message} {name_with_prefix('Your', current_item.menu_item_name)} is now {updated_summary}. Anything else?",
                        )
            except MenuDataNotLoadedError:
                # Menu cache not loaded - fall back to checking removable modifiers set
                logger.debug("Menu cache not loaded for modifier match - using removable modifiers set")

                # Legacy fallback using removable modifiers set
                removable_modifiers = _get_removable_modifiers()
                if cancel_desc in removable_modifiers:
                    cancel_variants = get_singular_plural_variants(cancel_desc)
                    selections_to_remove = []
                    removed_modifier_name = cancel_desc

                    for sel in current_item.selections:
                        sel_display = sel.get("display_name", "").lower()
                        sel_slug = sel.get("slug", "").lower()
                        sel_category = sel.get("category", "")
                        if (any(v in sel_display for v in cancel_variants) or
                            any(v in sel_slug for v in cancel_variants)):
                            selections_to_remove.append((sel_category, sel_slug))
                            removed_modifier_name = sel.get("display_name", cancel_desc)

                    for category, slug in selections_to_remove:
                        current_item.remove_selection(category, slug)

                    if selections_to_remove:
                        # Recalculate price after modifier removal
                        safe_recalculate_price(
                            self._parent.pricing, current_item, "after modifier removal during config (fallback)"
                        )
                        logger.info(
                            "Modifier removal during config (fallback): removed '%s' from %s",
                            removed_modifier_name, current_item.menu_item_name
                        )
                        updated_summary = current_item.get_summary()
                        return self._config_removal_response(
                            f"OK, I've removed the {removed_modifier_name}.",
                            order, current_item,
                            f"OK, I've removed the {removed_modifier_name}. {name_with_prefix('Your', current_item.menu_item_name)} is now {updated_summary}. Anything else?",
                        )

        return None

    def _find_and_remove_matching_items(
        self,
        cancel_desc: str,
        current_item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Search for and remove matching items from the order.

        Handles ordinal references ("second bagel"), plural removal ("coffees"),
        category mapping, and item name/type/summary matching. This is the final
        fallback -- it always returns a StateMachineResult.

        Args:
            cancel_desc: Normalized cancellation description from user input.
            current_item: The item currently being configured.
            order: The current order task.

        Returns:
            StateMachineResult indicating items were removed or not found.
        """
        # Get all active items to search through
        active_items, error = check_has_active_items(order)
        if error:
            order.clear_pending()
            return error

        # First, check for ordinal reference (e.g., "second bagel", "3rd coffee")
        ordinal_index, item_type_keyword = extract_ordinal_reference(cancel_desc)

        if ordinal_index is not None and item_type_keyword:
            # User wants to remove a specific Nth item
            result = find_nth_item_of_type(active_items, item_type_keyword, ordinal_index)
            if result:
                item_to_remove, _ = result
                removed_name = item_to_remove.get_summary()
                remove_item_from_order(order, item_to_remove)

                # Clear pending state since we're leaving config phase
                order.clear_pending()
                order.set_phase(OrderPhase.TAKING_ITEMS)

                logger.info(
                    "Removed %s #%d during config: %s",
                    item_type_keyword, ordinal_index, removed_name
                )

                return build_removal_response(
                    order, removed_name, self._parent._configure_next_incomplete_item
                )
            else:
                # Ordinal item not found
                return StateMachineResult(
                    message=f"I couldn't find a {item_type_keyword} #{ordinal_index} in your order. What would you like to do?",
                    order=order,
                )

        # Check if this is a plural removal (e.g., "coffees", "bagels")
        # If plural, we remove ALL matching items
        # Use singularize to properly detect plural forms
        singular_desc = singularize(cancel_desc)
        is_plural = singular_desc != cancel_desc.lower()

        # Get all variants for matching
        cancel_variants = get_singular_plural_variants(cancel_desc)

        # Find matching items (fallback for non-ordinal cancellations)
        items_to_remove = []

        # Map user category terms to item_type via database (e.g., "coffee" -> "sized_beverage")
        # Uses category keywords from item_types.aliases in the database
        mapped_item_type = None
        for variant in cancel_variants:
            category_mapping = menu_cache.get_category_keyword_mapping(variant)
            if category_mapping:
                mapped_item_type = category_mapping.get("slug")
                break

        # For singular removal during config, prioritize the item being configured.
        # When user says "remove the bagel" while configuring an Onion Bagel, they
        # most likely mean the one they're actively configuring, not a different bagel.
        if not is_plural and current_item and _item_matches(
            current_item, cancel_variants, cancel_desc, mapped_item_type
        ):
            items_to_remove.append(current_item)
        else:
            for item in active_items:
                if _item_matches(item, cancel_variants, cancel_desc, mapped_item_type):
                    items_to_remove.append(item)
                    if not is_plural:
                        break

        if items_to_remove:
            # Remove the items
            removed_names = []
            for item in items_to_remove:
                removed_names.append(item.get_summary())
                remove_item_from_order(order, item)

            # Clear pending state since we're leaving config phase
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            logger.info("Removed %d item(s) during config: %s", len(removed_names), removed_names)

            if len(removed_names) == 1:
                return build_removal_response(
                    order, removed_names[0], self._parent._configure_next_incomplete_item
                )

            # Multiple items removed - custom message format
            removed_str = f"the {len(removed_names)} {singular_desc}s"
            remaining = order.items.get_active_items()
            if remaining:
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
            # Couldn't find a matching item
            return StateMachineResult(
                message=item_not_found_in_order(cancel_desc),
                order=order,
            )

    def _get_current_config_question(
        self,
        order: OrderTask,
        item: MenuItemTask,
    ) -> str | None:
        """Get the current configuration question being asked.

        Delegates to config_helper_handler if available.
        """
        if self._parent.config_helper_handler:
            return self._parent.config_helper_handler.get_current_config_question(order, item)
        return None

    def _config_removal_response(
        self,
        removal_msg: str,
        order: OrderTask,
        config_item: MenuItemTask,
        fallback_msg: str,
    ) -> StateMachineResult:
        """Build a response after removing an attribute/modifier during configuration.

        If there's a pending config question, appends it to the removal message.
        Otherwise falls back to the provided fallback message.

        Args:
            removal_msg: The removal acknowledgment (e.g., "OK, I've removed the lox.").
            order: The current order task.
            config_item: The item being configured (used to find the next question).
            fallback_msg: Message to use if no config question is pending.
        """
        question = self._get_current_config_question(order, config_item)
        if question:
            return StateMachineResult(message=f"{removal_msg} {question}", order=order)
        return StateMachineResult(message=fallback_msg, order=order)
