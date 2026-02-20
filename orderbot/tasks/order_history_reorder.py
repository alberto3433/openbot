from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .pending_fields import PendingField
from .schemas import StateMachineResult, OrderPhase
from .utils.text import normalize_text, parse_selection

if TYPE_CHECKING:
    from .order_history_handler import OrderHistoryHandler

logger = logging.getLogger(__name__)


def _get_responses() -> dict:
    from .order_history_handler import RESPONSES
    return RESPONSES


class OrderHistoryReorder:

    def __init__(self, parent: OrderHistoryHandler) -> None:
        self._parent = parent

    def handle_reorder_specific_item(
        self,
        item_ref: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'Just the bagel from last time' - Add specific item from history.

        Args:
            item_ref: The item reference from user input (e.g., "bagel", "coffee").
            order: The current order task.

        Returns:
            StateMachineResult with confirmation or error message.
        """
        phone = self._parent._data._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=_get_responses()["no_phone"],
                order=order,
            )

        # Get items from returning customer or fetch history
        items = []
        if self._parent._returning_customer and self._parent._returning_customer.get("last_order_items"):
            items = self._parent._returning_customer["last_order_items"]
        else:
            history = self._parent._data._get_order_history(phone, limit=1)
            if history and history.get("orders"):
                items = history["orders"][0].get("items", [])

        if not items:
            return StateMachineResult(
                message=_get_responses()["no_history"],
                order=order,
            )

        # Find matching items
        item_ref_lower = normalize_text(item_ref)
        matching_items = []
        for item in items:
            name = item.get("menu_item_name", "").lower()
            item_type = item.get("item_type", "").lower()
            # Match by name or item type
            if item_ref_lower in name or item_ref_lower in item_type:
                matching_items.append(item)

        if not matching_items:
            return StateMachineResult(
                message=_get_responses()["item_not_found"].format(item_ref=item_ref),
                order=order,
            )

        if len(matching_items) == 1:
            # Single match - add it
            item_data = matching_items[0]
            return self._add_item_from_history(item_data, order)

        # Multiple matches - ask for clarification
        item_names = [item.get("menu_item_name", "item") for item in matching_items]
        order.pending_reorder_items = matching_items
        order.pending_field = PendingField.REORDER_ITEM_SELECTION

        qr = [{"label": name, "value": name} for name in item_names]
        return StateMachineResult(
            message=_get_responses()["multiple_matches"].format(item_type=item_ref)
            + f" {', '.join(item_names)}?",
            order=order,
            quick_replies=qr,
        )

    def handle_reorder_with_modifications(
        self,
        modification_text: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'Repeat my order but iced' - Reorder with modifications.

        Args:
            modification_text: The modification text (e.g., "iced", "without the bagel").
            order: The current order task.

        Returns:
            StateMachineResult with confirmation or error message.
        """
        phone = self._parent._data._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=_get_responses()["no_phone"],
                order=order,
            )

        # Get items to reorder
        items = []
        if self._parent._returning_customer and self._parent._returning_customer.get("last_order_items"):
            items = self._parent._returning_customer["last_order_items"]
        else:
            history = self._parent._data._get_order_history(phone, limit=1)
            if history and history.get("orders"):
                items = history["orders"][0].get("items", [])

        if not items:
            return StateMachineResult(
                message=_get_responses()["no_history"],
                order=order,
            )

        # Apply modifications
        modified_items, description = self._parent._data.apply_modifications(items, modification_text)

        if not modified_items:
            return StateMachineResult(
                message="After that modification, there are no items left. What can I get you?",
                order=order,
            )

        # Add modified items to order
        items_added = []
        for item_data in modified_items:
            self._add_item_from_history(item_data, order, silent=True)
            items_added.append(item_data.get("menu_item_name", "item"))

        items_str = ", ".join(items_added)
        return StateMachineResult(
            message=_get_responses()["reorder_modified"].format(
                modification_desc=f"({description}): {items_str}"
            ),
            order=order,
        )

    def handle_reorder_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user's response to reorder item clarification.

        Args:
            user_input: The user's response.
            order: The current order task.

        Returns:
            StateMachineResult with appropriate action.
        """
        pending_items = order.pending_reorder_items
        if not pending_items:
            order.pending_field = None
            return None

        text_lower = user_input.strip().lower()

        # Try to match by name
        for item in pending_items:
            name = item.get("menu_item_name", "").lower()
            if text_lower in name or name in text_lower:
                order.clear_pending()
                return self._add_item_from_history(item, order)

        # Try ordinal (1, 2, first, second, etc.)
        selected_idx = parse_selection(user_input, len(pending_items))
        if selected_idx is not None and 0 <= selected_idx < len(pending_items):
            order.clear_pending()
            return self._add_item_from_history(pending_items[selected_idx], order)

        # Didn't understand
        item_names = [item.get("menu_item_name", "item") for item in pending_items]
        qr = [{"label": name, "value": name} for name in item_names]
        return StateMachineResult(
            message=f"I didn't catch that. Which one would you like: {', '.join(item_names)}?",
            order=order,
            quick_replies=qr,
        )

    def handle_reorder_offer_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user's yes/no response to 'Want to reorder it?' offer.

        Args:
            user_input: The user's response (e.g., "yes", "no", "sure").
            order: The current order task.

        Returns:
            StateMachineResult with appropriate action.
        """
        from .response_utils import is_affirmative, is_negative

        pending_items = order.pending_reorder_offer_items
        if not pending_items:
            order.clear_pending()
            return None

        text_lower = user_input.strip().lower()

        # Check for affirmative response
        if is_affirmative(text_lower):
            order.clear_pending()

            # Add all items from pending offer
            items_added = []
            for item_data in pending_items:
                self._add_item_from_history(item_data, order, silent=True)
                qty = item_data.get("quantity", 1)
                name = item_data.get("menu_item_name", "item")
                if qty > 1:
                    items_added.append(f"{qty} {name}s")
                else:
                    items_added.append(name)

            items_str = ", ".join(items_added)
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message=_get_responses()["reorder_success"].format(summary=items_str),
                order=order,
            )

        # Check for negative response
        if is_negative(text_lower):
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message="No problem! What can I get for you today?",
                order=order,
            )

        # Didn't understand - clear pending state and fall through to normal processing
        order.clear_pending()
        return None

    def _add_item_from_history(
        self,
        item_data: dict,
        order: OrderTask,
        silent: bool = False,
    ) -> StateMachineResult | None:
        """Add an item from order history to the current order.

        Args:
            item_data: Item dict from order history.
            order: Current order task.
            silent: If True, don't return a result (for batch adds).

        Returns:
            StateMachineResult with confirmation, or None if silent.
        """
        # Check item availability (optional)
        item_name = item_data.get("menu_item_name", "Item")
        menu_item_type = item_data.get("menu_item_type") or item_data.get("item_type")
        price = item_data.get("price", 0)
        quantity = item_data.get("quantity", 1)

        # Create MenuItemTask
        item = MenuItemTask(
            menu_item_name=item_name,
            menu_item_type=menu_item_type,
            unit_price=price,
        )

        # Copy attribute_values if present
        if "attribute_values" in item_data and item_data["attribute_values"]:
            item.attribute_values = item_data["attribute_values"].copy()
        else:
            # Copy individual attributes (legacy support)
            metadata_keys = {
                "item_type", "menu_item_type", "menu_item_name", "menu_item_id",
                "quantity", "price", "modifiers", "attribute_values", "base_price",
                "display_name", "free_details", "customization_offered",
            }
            for key, value in item_data.items():
                if key not in metadata_keys and value is not None:
                    item[key] = value

        # Mark complete and add to order
        item.mark_complete()
        for _ in range(quantity):
            order.items.add_item(item.duplicate())

        order.set_phase(OrderPhase.TAKING_ITEMS)

        if silent:
            return None

        logger.info(
            "Added item '%s' from order history (qty=%d)",
            item_name, quantity
        )

        qty_word = f"{quantity} " if quantity > 1 else ""
        return StateMachineResult(
            message=_get_responses()["reorder_success"].format(
                summary=f"{qty_word}{item_name}"
            ),
            order=order,
        )
