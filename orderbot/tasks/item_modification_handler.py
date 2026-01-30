"""
Item Modification Handler.

This module handles modification of existing items in the cart including:
- Adding modifiers to specific items: "can I have scallion cream cheese on the cinnamon raisin bagel"
- Adding modifiers with implicit target: "add mayo and mustard" (applies to last item)
- Handling qualifier conflicts: "light extra mayo"

Extracted from taking_items_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache

from .models import OrderTask, MenuItemTask
from .schemas import StateMachineResult, OpenInputResponse
from .pending_fields import PendingField
from .parsers.quantity_utils import extract_quantity_for_pattern, extract_leading_quantity
from .checkout_messages import sure_updated_anything_else
from .handler_utils import get_last_item, is_configurable_menu_item, recalculate_and_summarize

if TYPE_CHECKING:
    from .pricing import PricingEngine
    from .item_adder_handler import ItemAdderHandler

logger = logging.getLogger(__name__)


class ItemModificationHandler:
    """
    Handles modification of existing items in the cart.

    Manages adding modifiers, handling qualifier conflicts, and
    updating items based on user requests.
    """

    def __init__(
        self,
        pricing: "PricingEngine",
        item_adder_handler: "ItemAdderHandler | None" = None,
    ):
        """
        Initialize the item modification handler.

        Args:
            pricing: PricingEngine for recalculating prices after modifications.
            item_adder_handler: Handler for disambiguation (optional).
        """
        self.pricing = pricing
        self.item_adder_handler = item_adder_handler

    def handle_modify_existing_item(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Handle modification to an existing item in the cart.

        Handles patterns like:
        - "can I have scallion cream cheese on the cinnamon raisin bagel"
        - "make the bagel with scallion cream cheese" (implicit target)
        - "add mayo and mustard" (applies to last item in cart)

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        if not parsed.modify_existing_item:
            return None

        # Check for qualifier conflicts (e.g., "light extra mayo")
        result = self._handle_qualifier_conflicts(parsed, order)
        if result:
            return result

        target_desc = (parsed.modify_target_description or "").lower()
        active_items = order.items.get_active_items()

        # Find the target item
        target_item = self._find_target_item(target_desc, active_items)

        if target_item:
            return self._apply_modifications(
                target_item, parsed, order, raw_user_input
            )
        else:
            return self._handle_no_target_found(target_desc, active_items, order)

    def _handle_qualifier_conflicts(
        self,
        parsed: OpenInputResponse,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle qualifier conflicts like 'light extra mayo'."""
        if not parsed.modify_qualifier_conflicts:
            return None

        conflict_messages = []
        for conflict in parsed.modify_qualifier_conflicts:
            conflict_messages.append(
                f"I heard both '{conflict.qualifier1}' and '{conflict.qualifier2}' for the {conflict.modifier}. "
                f"Did you want {conflict.qualifier1} {conflict.modifier} or {conflict.qualifier2} {conflict.modifier}?"
            )
        # Return first conflict for user to resolve
        logger.info("QUALIFIER CONFLICT: %s", parsed.modify_qualifier_conflicts)
        return StateMachineResult(
            message=conflict_messages[0],
            order=order,
        )

    def _find_target_item(
        self,
        target_desc: str,
        active_items: list,
    ) -> MenuItemTask | None:
        """Find the item that matches the target description."""
        menu_items_in_cart = [i for i in active_items if isinstance(i, MenuItemTask)]

        if target_desc:
            # Match items by summary (data-driven, works for any item type)
            for item in menu_items_in_cart:
                item_summary = item.get_summary().lower()
                # Match if target description is contained in summary or vice versa
                if target_desc in item_summary or item_summary in target_desc:
                    return item
                # Also check if any word from target matches summary
                target_words = target_desc.split()
                if any(word in item_summary for word in target_words if len(word) > 2):
                    return item

            # Also check by item name if no summary matched
            for item in menu_items_in_cart:
                item_name = (item.menu_item_name or "").lower()
                if item_name and item_name in target_desc:
                    return item

            # Check for category reference with single item (e.g., "the bagel" when only one bagel)
            target_category = menu_cache.is_category_reference(target_desc)
            if target_category:
                matching_type_items = [
                    i for i in menu_items_in_cart
                    if i.menu_item_type == target_category
                ]
                if len(matching_type_items) == 1:
                    return matching_type_items[0]
        else:
            # Implicit target ("add mayo", "add mustard", etc.)
            # Use the last item in the cart regardless of type
            if active_items:
                last_item = get_last_item(active_items)
                return last_item if isinstance(last_item, MenuItemTask) else None

        return None

    def _apply_modifications(
        self,
        target_item: MenuItemTask,
        parsed: OpenInputResponse,
        order: OrderTask,
        raw_user_input: str | None,
    ) -> StateMachineResult | None:
        """Apply modifications to the target item."""
        if not parsed.modify_add_modifiers:
            return None

        # Build modifier→category lookup (data-driven from database)
        modifier_to_category: dict[str, str] = {}
        for category in menu_cache.get_all_ingredient_categories():
            for ingredient in menu_cache.get_ingredients(category):
                modifier_to_category[ingredient.lower()] = category

        for modifier in parsed.modify_add_modifiers:
            result = self._add_single_modifier(
                target_item, modifier, modifier_to_category, raw_user_input, order
            )
            if result:
                return result

        # Recalculate price
        updated_summary = recalculate_and_summarize(target_item, self.pricing)
        logger.info("MODIFY EXISTING: Updated '%s' with add_modifiers=%s",
                   target_item.menu_item_name, parsed.modify_add_modifiers)
        return StateMachineResult(
            message=sure_updated_anything_else(updated_summary),
            order=order,
        )

    def _add_single_modifier(
        self,
        target_item: MenuItemTask,
        modifier: str,
        modifier_to_category: dict[str, str],
        raw_user_input: str | None,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Add a single modifier to the target item.

        Returns StateMachineResult only if disambiguation is needed.
        """
        # Handle qualified modifiers: "mayo (extra)" -> base="mayo"
        modifier_lower = modifier.lower()
        base_modifier = modifier_lower.split(" (")[0].strip()

        # Strip quantity prefix from modifier: "2 vanilla syrups" -> "vanilla syrups"
        quantity_from_modifier, base_modifier_stripped = extract_leading_quantity(base_modifier)
        if quantity_from_modifier:
            base_modifier = base_modifier_stripped

        # Also strip trailing 's' for plural: "vanilla syrups" -> "vanilla syrup"
        if base_modifier.endswith("s") and not base_modifier.endswith("ss"):
            singular = base_modifier[:-1]
            # Check if singular form is recognized
            if menu_cache.find_matching_ingredients(singular):
                base_modifier = singular

        # Check for multiple matching ingredients (disambiguation)
        matches = menu_cache.find_matching_ingredients(base_modifier)

        if len(matches) == 0:
            # Fall back to category lookup for generic modifiers
            category = modifier_to_category.get(base_modifier)
            if not category:
                logger.warning(
                    "MODIFY ADD: Skipping modifier '%s' - not found in database",
                    modifier,
                )
                return None

            # Extract quantity - prefer quantity from modifier prefix
            quantity = self._extract_modifier_quantity(
                quantity_from_modifier, raw_user_input, base_modifier, modifier_lower
            )

            modifier_slug = modifier_lower.replace(" ", "_")
            target_item.add_selection(
                slug=modifier_slug,
                category=category,
                display_name=modifier.title(),
                quantity=quantity,
            )
            logger.info("MODIFY ADD: Added '%s' (category=%s, qty=%d) to item", modifier, category, quantity)

        elif len(matches) == 1:
            # Single match - add it directly
            match = matches[0]
            quantity = self._extract_modifier_quantity(
                quantity_from_modifier, raw_user_input, base_modifier, modifier_lower
            )

            target_item.add_selection(
                slug=match["slug"],
                category=match["category"],
                display_name=match["name"],
                quantity=quantity,
            )
            logger.info("MODIFY ADD: Added '%s' (category=%s, qty=%d)", match["name"], match["category"], quantity)

        else:
            # Multiple matches - trigger disambiguation
            logger.info(
                "MODIFY ADD: Multiple matches for '%s' (%d options), triggering disambiguation",
                modifier, len(matches)
            )

            # Store context for when disambiguation resolves
            target_item_index = order.items.items.index(target_item)
            order.pending_modifier_target_item_index = target_item_index
            quantity = self._extract_modifier_quantity(
                quantity_from_modifier, raw_user_input, base_modifier, modifier_lower
            )
            order.pending_modifier_quantity = quantity

            # Use existing disambiguation handler
            if self.item_adder_handler and self.item_adder_handler.disambiguation_handler:
                return self.item_adder_handler.disambiguation_handler.start_disambiguation(
                    item_name=modifier,
                    matching_items=matches,
                    order=order,
                    pending_field=PendingField.MODIFIER_SELECTION,
                    show_prices=False,
                )

        return None

    def _extract_modifier_quantity(
        self,
        quantity_from_modifier: int | None,
        raw_user_input: str | None,
        base_modifier: str,
        modifier_lower: str,
    ) -> int:
        """Extract quantity for a modifier."""
        quantity = quantity_from_modifier if quantity_from_modifier else 1
        if quantity == 1 and raw_user_input:
            quantity = extract_quantity_for_pattern(raw_user_input, base_modifier)
            if quantity == 1 and "(extra)" in modifier_lower:
                quantity = 2
        return quantity

    def _handle_no_target_found(
        self,
        target_desc: str,
        active_items: list,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle case when no target item was found."""
        if target_desc:
            logger.warning(
                "MODIFY EXISTING: Could not find item matching '%s' in cart",
                target_desc
            )
            return StateMachineResult(
                message=f"I couldn't find a {target_desc} in your order. Would you like to add one?",
                order=order,
            )
        else:
            logger.warning("MODIFY EXISTING: No items in cart to modify")
            return StateMachineResult(
                message="I don't see any items in your order to modify. Would you like to add something?",
                order=order,
            )
