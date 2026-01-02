"""
Checkout Utilities Handler for Order State Machine.

This module handles checkout-related utility operations including
next question determination, checkout transitions, delivery questions,
and order summary building.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, CoffeeItemTask, SpeedMenuBagelItemTask, BagelItemTask, ItemTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult

if TYPE_CHECKING:
    from .message_builder import MessageBuilder

logger = logging.getLogger(__name__)


class CheckoutUtilsHandler:
    """
    Handles checkout utility operations.

    Manages next question determination, checkout transitions,
    delivery questions, and order summary building.
    """

    def __init__(
        self,
        transition_to_next_slot: Callable[[OrderTask], None] | None = None,
        configure_next_incomplete_coffee: Callable[[OrderTask], StateMachineResult] | None = None,
        configure_next_incomplete_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
        configure_next_incomplete_speed_menu_bagel: Callable[[OrderTask], StateMachineResult] | None = None,
        message_builder: "MessageBuilder | None" = None,
    ):
        """
        Initialize the checkout utils handler.

        Args:
            transition_to_next_slot: Callback to transition to the next slot.
            configure_next_incomplete_coffee: Callback to configure next incomplete coffee.
            configure_next_incomplete_bagel: Callback to configure next incomplete bagel.
            configure_next_incomplete_speed_menu_bagel: Callback to configure next incomplete speed menu bagel.
            message_builder: MessageBuilder instance for generating summaries.
        """
        self._transition_to_next_slot = transition_to_next_slot
        self._configure_next_incomplete_coffee = configure_next_incomplete_coffee
        self._configure_next_incomplete_bagel = configure_next_incomplete_bagel
        self._configure_next_incomplete_speed_menu_bagel = configure_next_incomplete_speed_menu_bagel
        self._message_builder = message_builder
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    def set_repeat_order_info(self, is_repeat: bool, last_order_type: str | None) -> None:
        """Set repeat order info for personalized delivery question."""
        self._is_repeat_order = is_repeat
        self._last_order_type = last_order_type

    def get_next_question(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Determine the next question to ask."""
        # Check for incomplete items that need configuration
        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                # Handle bagels that need configuration
                if isinstance(item, BagelItemTask):
                    if item.bagel_type is None or item.toasted is None:
                        logger.info("Found incomplete bagel, starting configuration")
                        if self._configure_next_incomplete_bagel:
                            return self._configure_next_incomplete_bagel(order)
                # Handle speed menu bagels that need configuration
                elif isinstance(item, SpeedMenuBagelItemTask):
                    if item.bagel_choice is None or item.toasted is None:
                        logger.info("Found incomplete speed menu bagel, starting configuration")
                        if self._configure_next_incomplete_speed_menu_bagel:
                            return self._configure_next_incomplete_speed_menu_bagel(order)
                # Handle coffee that needs configuration
                elif isinstance(item, CoffeeItemTask):
                    logger.info("Found incomplete coffee, starting configuration")
                    if self._configure_next_incomplete_coffee:
                        return self._configure_next_incomplete_coffee(order)
                else:
                    # Other in-progress items - log warning
                    logger.warning(f"Found in-progress item without handler: {item}")

        # Check if there are items queued for configuration
        if order.has_queued_config_items():
            next_config = order.pop_next_config_item()
            if next_config:
                item_id = next_config.get("item_id")
                item_type = next_config.get("item_type")
                logger.info("Processing queued config item: id=%s, type=%s", item_id[:8] if item_id else None, item_type)

                # Handle coffee disambiguation (when "coffee" matched multiple items like Coffee, Latte, etc.)
                if item_type == "coffee_disambiguation" and order.pending_drink_options:
                    logger.info("Processing queued coffee disambiguation")
                    order.pending_field = "drink_selection"
                    order.phase = OrderPhase.CONFIGURING_ITEM.value
                    # Build the clarification message
                    option_list = []
                    for i, option_item in enumerate(order.pending_drink_options, 1):
                        name = option_item.get("name", "Unknown")
                        price = option_item.get("base_price", 0)
                        if price > 0:
                            option_list.append(f"{i}. {name} (${price:.2f})")
                        else:
                            option_list.append(f"{i}. {name}")
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"For your coffee - we have a few options:\n{options_str}\nWhich would you like?",
                        order=order,
                    )

                # Find the item by ID and start configuration based on type
                for item in order.items.items:
                    if item.id == item_id:
                        if item_type == "bagel" and isinstance(item, BagelItemTask):
                            # Start bagel configuration
                            if self._configure_next_incomplete_bagel:
                                return self._configure_next_incomplete_bagel(order)
                        elif item_type == "speed_menu_bagel" and isinstance(item, SpeedMenuBagelItemTask):
                            # Start speed menu bagel configuration
                            if self._configure_next_incomplete_speed_menu_bagel:
                                return self._configure_next_incomplete_speed_menu_bagel(order)
                        elif item_type == "coffee" and isinstance(item, CoffeeItemTask):
                            # Start coffee configuration
                            if self._configure_next_incomplete_coffee:
                                return self._configure_next_incomplete_coffee(order)

        # Ask if they want anything else
        items = order.items.get_active_items()
        if items:
            # Count consecutive identical items at the end of the list
            last_item = items[-1]
            last_summary = last_item.get_summary()
            count = 0
            for item in reversed(items):
                if item.get_summary() == last_summary:
                    count += 1
                else:
                    break

            # Show quantity if more than 1 identical item
            if count > 1:
                summary = f"{count} {last_summary}s" if not last_summary.endswith("s") else f"{count} {last_summary}"
            else:
                summary = last_summary

            # Explicitly set to TAKING_ITEMS - we're asking for more items
            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                order=order,
            )

        return StateMachineResult(
            message="What can I get for you?",
            order=order,
        )

    def transition_to_checkout(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Transition to checkout phase.

        Uses the slot orchestrator to determine what to ask next.
        """
        order.clear_pending()

        # Use orchestrator to determine next step in checkout
        if self._transition_to_next_slot:
            self._transition_to_next_slot(order)

        # Return appropriate message based on phase set by orchestrator
        if order.phase == OrderPhase.CHECKOUT_NAME.value:
            logger.info("CHECKOUT: Asking for name (delivery=%s)", order.delivery_method.order_type)
            return StateMachineResult(
                message="Can I get a name for the order?",
                order=order,
            )
        elif order.phase == OrderPhase.CHECKOUT_CONFIRM.value:
            # We have both delivery type and customer name
            logger.info("CHECKOUT: Skipping to confirmation (already have name=%s, delivery=%s)",
                       order.customer_info.name, order.delivery_method.order_type)
            summary = self.build_order_summary(order)
            return StateMachineResult(
                message=f"{summary}\n\nDoes that look right?",
                order=order,
            )
        else:
            # Default: ask for delivery method
            return StateMachineResult(
                message=self.get_delivery_question(),
                order=order,
            )

    def get_delivery_question(self) -> str:
        """Get the delivery/pickup question, personalized for repeat orders."""
        if self._is_repeat_order and self._last_order_type == "pickup":
            return "Is this for pickup again, or delivery?"
        elif self._is_repeat_order and self._last_order_type == "delivery":
            return "Is this for delivery again, or pickup?"
        else:
            return "Is this for pickup or delivery?"

    def get_item_by_id(self, order: OrderTask, item_id: str) -> ItemTask | None:
        """Find an item by its ID."""
        for item in order.items.items:
            if item.id == item_id:
                return item
        return None

    def build_order_summary(self, order: OrderTask) -> str:
        """Build order summary string with consolidated identical items and total.

        Delegates to MessageBuilder for the actual implementation.
        """
        if self._message_builder:
            return self._message_builder.build_order_summary(order)
        # Fallback if message_builder not set (shouldn't happen in practice)
        return "Here's your order."
