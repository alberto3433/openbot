"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, ItemTask
from .schemas import StateMachineResult

if TYPE_CHECKING:
    from .by_pound_handler import ByPoundHandler
    from .coffee_config_handler import CoffeeConfigHandler
    from .bagel_config_handler import BagelConfigHandler
    from .speed_menu_handler import SpeedMenuBagelHandler
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler

logger = logging.getLogger(__name__)


class ConfiguringItemHandler:
    """
    Handles configuring items (answering configuration questions).

    Routes user input to the appropriate field-specific handler based
    on the pending_field in the order.
    """

    def __init__(
        self,
        by_pound_handler: "ByPoundHandler | None" = None,
        coffee_handler: "CoffeeConfigHandler | None" = None,
        bagel_handler: "BagelConfigHandler | None" = None,
        speed_menu_handler: "SpeedMenuBagelHandler | None" = None,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            by_pound_handler: Handler for by-pound items.
            coffee_handler: Handler for coffee configuration.
            bagel_handler: Handler for bagel configuration.
            speed_menu_handler: Handler for speed menu items.
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
        """
        self.by_pound_handler = by_pound_handler
        self.coffee_handler = coffee_handler
        self.bagel_handler = bagel_handler
        self.speed_menu_handler = speed_menu_handler
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler

    def handle_configuring_item(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle input when configuring a specific item.

        THIS IS THE KEY: we use state-specific parsers that can ONLY
        interpret input as answers for the pending field. No new items.
        """
        # Handle by-pound category selection (no item required)
        if order.pending_field == "by_pound_category":
            return self.by_pound_handler.handle_by_pound_category_selection(user_input, order)

        # Handle drink selection when multiple options were presented
        if order.pending_field == "drink_selection":
            return self.coffee_handler.handle_drink_selection(user_input, order)

        # Handle category inquiry follow-up ("Would you like to hear what X we have?" -> "yes")
        if order.pending_field == "category_inquiry":
            return self.by_pound_handler.handle_category_inquiry_response(user_input, order)

        item = self.checkout_utils_handler.get_item_by_id(order, order.pending_item_id)
        if item is None:
            order.clear_pending()
            return StateMachineResult(
                message="Something went wrong. What would you like to order?",
                order=order,
            )

        # Check for cancellation requests BEFORE routing to field-specific handlers
        # This allows "remove the coffee", "cancel this", "remove the coffees" etc. during configuration
        cancel_result = self.config_helper_handler.check_cancellation_during_config(user_input, item, order)
        if cancel_result:
            return cancel_result

        # Check for modifier change requests during configuration
        # If detected, tell user to wait until config is complete
        change_request = self.modifier_change_handler.detect_change_request(user_input)
        if change_request:
            logger.info("CHANGE REQUEST: Detected during config, deferring: %s", change_request)
            msg = self.modifier_change_handler.generate_mid_config_message()
            # Re-ask the current question
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"{msg} {current_question}"
            return StateMachineResult(message=msg, order=order)

        # Route to field-specific handler
        if order.pending_field == "side_choice":
            return self.config_helper_handler.handle_side_choice(user_input, item, order)
        elif order.pending_field == "bagel_choice":
            return self.bagel_handler.handle_bagel_choice(user_input, item, order)
        elif order.pending_field == "spread":
            return self.bagel_handler.handle_spread_choice(user_input, item, order)
        elif order.pending_field == "toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        elif order.pending_field == "cheese_choice":
            return self.bagel_handler.handle_cheese_choice(user_input, item, order)
        elif order.pending_field == "coffee_size":
            return self.coffee_handler.handle_coffee_size(user_input, item, order)
        elif order.pending_field == "coffee_style":
            return self.coffee_handler.handle_coffee_style(user_input, item, order)
        elif order.pending_field == "speed_menu_bagel_toasted":
            return self.speed_menu_handler.handle_speed_menu_bagel_toasted(user_input, item, order)
        elif order.pending_field == "spread_sandwich_toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        else:
            order.clear_pending()
            return self.checkout_utils_handler.get_next_question(order)
