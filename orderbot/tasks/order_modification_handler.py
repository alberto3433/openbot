"""
Order Modification Handler for Order State Machine.

Handles order-level modifications:
- Order type changes (pickup <-> delivery)
- Quantity duplication ("make it 2")
- Customer info changes (name, phone, email)
- ID-based item removal (cart X button)

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from .models import OrderTask
from .schemas import OrderPhase, StateMachineResult
from .checkout_messages import CheckoutMessages
from .parsers.quantity_utils import extract_make_it_n_target
from .handler_utils import get_last_item, build_removal_response
from .quantity_management import (
    duplicate_last_item_to_qty,
    handle_make_it_one,
    handle_already_at_target,
)

if TYPE_CHECKING:
    from .message_builder import MessageBuilder
    from .config_helper_handler import ConfigHelperHandler

logger = logging.getLogger(__name__)

# Compiled pattern for customer info change requests
_CUSTOMER_INFO_CHANGE_RE = re.compile(
    r'\b(?:change|update|edit)\s+(?:my\s+)?'
    r'(name|phone(?:\s+number)?|email(?:\s+address)?)\b',
    re.IGNORECASE,
)


class OrderModificationHandler:
    """Handles order-level modifications like type changes, quantity, and removal."""

    def __init__(
        self,
        message_builder: "MessageBuilder",
        config_helper_handler: "ConfigHelperHandler",
        configure_next_incomplete_item: Callable,
    ) -> None:
        self._message_builder = message_builder
        self._config_helper_handler = config_helper_handler
        self._configure_next_incomplete_item = configure_next_incomplete_item

    def handle_order_type_change(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle order type change requests (e.g., 'change it to delivery').

        Detects patterns like "change/switch/make it to delivery/pickup" and
        applies the order type change. If switching to delivery, transitions to
        address collection. If switching to pickup, re-shows confirmation.

        Returns:
            StateMachineResult if an order type change was handled, None otherwise.
        """
        from .parsers import ORDER_TYPE_CHANGE_PATTERN

        match = ORDER_TYPE_CHANGE_PATTERN.search(user_input)
        if not match:
            return None

        new_type = "delivery" if "deliv" in match.group(1).lower() else "pickup"

        if order.delivery_method.order_type == new_type:
            return None  # Already that type, let other handlers process

        old_type = order.delivery_method.order_type
        order.delivery_method.order_type = new_type
        logger.info("ORDER TYPE CHANGE: %s -> %s", old_type, new_type)

        if new_type == "delivery":
            # Need to collect delivery address
            order.set_phase(OrderPhase.CHECKOUT_DELIVERY)
            return StateMachineResult(
                message="Changed to delivery. What's the delivery address?",
                order=order,
            )
        else:
            # Switching to pickup — clear any delivery address
            from .models.order_flow import AddressTask
            order.delivery_method.address = AddressTask()
            # Re-show order confirmation
            order.set_phase(OrderPhase.CHECKOUT_CONFIRM)
            summary = self._message_builder.build_order_summary(order)
            return StateMachineResult(
                message=f"Changed to pickup. {summary} Does that look right? Anything else?",
                order=order,
            )

    def handle_make_it_n(
        self, user_input: str, order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'make it N' quantity duplication pattern.

        Detects patterns like "make it 2", "actually make that three" and
        duplicates the last item to reach the target quantity.

        Returns:
            StateMachineResult if handled, None otherwise.
        """
        from .parsers.deterministic import MAKE_IT_N_PATTERN

        make_it_n_match = MAKE_IT_N_PATTERN.match(user_input.strip())
        if not make_it_n_match or order.items.get_item_count() == 0:
            return None

        target_qty = extract_make_it_n_target(make_it_n_match)
        if not target_qty:
            return handle_make_it_one(make_it_n_match, order)

        result = duplicate_last_item_to_qty(order, target_qty, count_existing=True)
        if result is None:
            return None

        target_qty, last_item_name, added_count = result

        already = handle_already_at_target(order, target_qty, added_count, last_item_name)
        if already:
            return already

        # If mid-configuration, re-ask the pending config question
        suffix = "Anything else?"
        if order.is_configuring_item() and order.first_pending_item_id:
            config_item = order.items.get_item_by_id(order.first_pending_item_id)
            if config_item:
                question = self._config_helper_handler.get_current_config_question(order, config_item)
                if question:
                    suffix = question

        return StateMachineResult(
            message=f"Sure, that's {target_qty} total. {suffix}",
            order=order,
        )

    def handle_customer_info_change(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle requests to change customer name, phone, or email.

        Detects patterns like "change my name", "update my email", etc.
        Clears the relevant field and transitions to the appropriate checkout phase
        so the orchestrator re-collects it.

        Args:
            user_input: The user's input text.
            order: The current order task.

        Returns:
            StateMachineResult if a change was requested, None otherwise.
        """
        match = _CUSTOMER_INFO_CHANGE_RE.search(user_input)
        if not match:
            return None

        field = match.group(1).lower()

        # Map matched field to (customer_info attr, checkout phase, re-ask message)
        field_map = {
            "name": ("name", OrderPhase.CHECKOUT_NAME, "Sure! What name should I put on the order?"),
            "phone": ("phone", OrderPhase.CHECKOUT_PHONE, CheckoutMessages.PHONE),
            "email": ("email", OrderPhase.CHECKOUT_EMAIL, CheckoutMessages.EMAIL),
        }

        # Normalize "phone number" -> "phone", "email address" -> "email"
        key = "phone" if field.startswith("phone") else "email" if field.startswith("email") else field
        if key not in field_map:
            return None

        attr, phase, msg = field_map[key]
        if not getattr(order.customer_info, attr):
            return None

        # Save current phase so checkout handlers can restore it after re-collection
        order.return_to_phase = order.phase
        setattr(order.customer_info, attr, None)
        order.checkout.order_reviewed = False
        order.set_phase(phase)
        return StateMachineResult(message=msg, order=order)

    def handle_id_based_removal(
        self,
        item_id: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle removal of a specific item by its unique ID.

        Called when the frontend passes an item_id (e.g., from the cart X button).
        Bypasses text-based parsing entirely for exact item targeting.

        Args:
            item_id: The unique ID of the item to remove
            order: The current order task

        Returns:
            StateMachineResult if handled, None if item_id is invalid
        """
        item = order.items.get_active_item_by_id(item_id)
        if item is None:
            return StateMachineResult(
                message="That item has already been removed. Anything else?",
                order=order,
            )

        removed_name = item.get_summary()

        # If the item being removed is currently being configured, clear pending state
        if order.first_pending_item_id == item_id:
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

        # Also remove from pending config queue if present
        order.pending_config_queue = [
            entry for entry in order.pending_config_queue
            if not (isinstance(entry, dict) and entry.get("item_id") == item_id)
        ]

        order.items.remove_item_with_bundle(item_id)

        return build_removal_response(
            order,
            removed_name,
            configure_next_incomplete=self._configure_next_incomplete_item,
        )
