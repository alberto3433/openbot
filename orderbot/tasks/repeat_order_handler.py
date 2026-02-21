"""
Repeat Order Handler for Order State Machine.

This module handles repeat order processing, extracted from checkout_handler.py.
When a returning customer requests to reorder, this handler copies items from
their previous order into the current order.
"""

import logging
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .context import OrderContext

from .models import OrderTask, MenuItemTask
from .schemas import OrderPhase, StateMachineResult
from ..cache import menu_cache
from .handler_config import BaseStateHandler
from .normalization import format_slug_for_display
from .utils.text import number_to_word


logger = logging.getLogger(__name__)

__all__ = ["RepeatOrderHandler"]


class RepeatOrderHandler(BaseStateHandler):
    """
    Handles repeat order processing for returning customers.

    Copies items from the customer's previous order into the current order,
    including all attribute values and configuration.
    """

    def __init__(self, config: "HandlerConfig"):
        super().__init__(config)

    def handle_repeat_order(
        self,
        order: OrderTask,
        returning_customer: dict | None = None,
        set_repeat_info_callback: Callable[[bool, str | None], None] | None = None,
    ) -> StateMachineResult:
        """
        Handle a request to repeat the customer's previous order.

        Copies items from returning_customer.last_order_items to the current order.
        """
        customer = returning_customer or self._returning_customer

        if not customer:
            logger.info("Repeat order requested but no returning customer data")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        last_order_items = customer.get("last_order_items", [])
        if not last_order_items:
            logger.info("Repeat order requested but no last_order_items in returning_customer")
            return StateMachineResult(
                message="I don't have a previous order on file for you. What can I get for you today?",
                order=order,
            )

        # Copy items from previous order
        items_added = []
        for prev_item in last_order_items:
            item_type = prev_item.get("item_type")
            if not item_type:
                logger.error(
                    "Previous order item missing required 'item_type' field. "
                    "Item data: %s",
                    prev_item
                )
                continue

            quantity = prev_item.get("quantity", 1)
            qty_word = number_to_word(quantity)

            # Add item using generic data-driven method
            self._add_repeat_item(prev_item, order, quantity, qty_word, items_added)

        # Copy customer info if available (name, phone, email)
        if customer.get("name") and not order.customer_info.name:
            order.customer_info.name = customer["name"]
        if customer.get("phone") and not order.customer_info.phone:
            order.customer_info.phone = customer["phone"]
        if customer.get("email") and not order.customer_info.email:
            order.customer_info.email = customer["email"]

        # Store last order type for "pickup again?" / "delivery again?" prompt
        if customer.get("last_order_type") and set_repeat_info_callback:
            set_repeat_info_callback(True, customer["last_order_type"])

        logger.info("Repeat order: added %d item types from previous order", len(items_added))

        # Build confirmation message
        if items_added:
            items_str = ", ".join(items_added)
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=f"Got it, I've added your previous order: {items_str}. Anything else?",
                order=order,
            )
        else:
            return StateMachineResult(
                message="I couldn't find any items in your previous order. What can I get for you today?",
                order=order,
            )

    def _add_repeat_item(
        self,
        prev_item: dict,
        order: OrderTask,
        quantity: int,
        qty_word: str,
        items_added: list[str],
    ) -> None:
        """Add a repeated item to the order (generic, data-driven).

        This method handles all item types by copying attribute_values from
        the previous order's item_config. It replaces the type-specific methods
        (_add_repeat_bagel, _add_repeat_coffee, _add_repeat_menu_item) with a
        single data-driven implementation.
        """
        # Get item type and name
        item_type = prev_item.get("menu_item_type") or prev_item.get("item_type")
        menu_item_name = prev_item.get("menu_item_name")
        # Derive name from item_type if not provided
        if not menu_item_name and item_type:
            menu_item_name = menu_cache.get_item_type_display_name(item_type) or format_slug_for_display(item_type, check_cache=False)
        menu_item_name = menu_item_name or "Item"
        price = prev_item.get("price", 0)

        # Create MenuItemTask
        item = MenuItemTask(
            menu_item_name=menu_item_name,
            menu_item_type=item_type,
            unit_price=price,
        )

        # Copy attribute_values if present (contains full nested structure)
        # This preserves all configuration from the original order
        if "attribute_values" in prev_item and prev_item["attribute_values"]:
            item.attribute_values = prev_item["attribute_values"].copy()
        else:
            # Fallback: copy individual top-level keys that match known attributes
            # This handles older orders that may not have attribute_values
            known_attrs = set()
            if item_type:
                known_attrs = set(menu_cache.get_item_type_attributes(item_type).keys())

            # Also include common attribute keys that might be in legacy data
            # These are keys that aren't metadata (quantity, price, etc.)
            metadata_keys = {
                "item_type", "menu_item_type", "menu_item_name", "menu_item_id",
                "quantity", "price", "modifiers", "attribute_values", "base_price",
                "display_name", "free_details", "customization_offered",
            }

            for key, value in prev_item.items():
                if key in metadata_keys:
                    continue
                # Copy if it's a known attribute OR if we don't have known attrs
                # (i.e., item_type not in DB, so accept all keys)
                if value is not None and (key in known_attrs or not known_attrs):
                    item[key] = value

        # Mark complete and add to order
        item.mark_complete()
        for _ in range(quantity):
            order.items.add_item(item.duplicate())

        # Build description using the item's data-driven get_summary() method
        items_added.append(f"{qty_word} {item.get_summary()}")
