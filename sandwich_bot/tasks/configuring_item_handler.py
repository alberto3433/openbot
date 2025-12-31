"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, ItemTask, MenuItemTask
from .schemas import StateMachineResult, OrderPhase

if TYPE_CHECKING:
    from .by_pound_handler import ByPoundHandler
    from .coffee_config_handler import CoffeeConfigHandler
    from .bagel_config_handler import BagelConfigHandler
    from .speed_menu_handler import SpeedMenuBagelHandler
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler

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
        item_adder_handler: "ItemAdderHandler | None" = None,
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
            item_adder_handler: Handler for adding items.
        """
        self.by_pound_handler = by_pound_handler
        self.coffee_handler = coffee_handler
        self.bagel_handler = bagel_handler
        self.speed_menu_handler = speed_menu_handler
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler

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

        # Handle generic item selection when multiple options were presented (cookies, muffins, etc.)
        if order.pending_field == "item_selection":
            return self._handle_item_selection(user_input, order)

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
        elif order.pending_field == "speed_menu_bagel_type":
            return self.speed_menu_handler.handle_speed_menu_bagel_type(user_input, item, order)
        elif order.pending_field == "speed_menu_bagel_toasted":
            return self.speed_menu_handler.handle_speed_menu_bagel_toasted(user_input, item, order)
        elif order.pending_field == "spread_sandwich_toasted":
            return self.bagel_handler.handle_toasted_choice(user_input, item, order)
        else:
            order.clear_pending()
            return self.checkout_utils_handler.get_next_question(order)

    def _handle_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple generic item options (cookies, muffins, etc.)."""
        if not order.pending_item_options:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        user_lower = user_input.lower().strip()
        options = order.pending_item_options
        quantity = order.pending_item_quantity or 1

        # Reject negative numbers or other invalid input early
        if user_lower.startswith('-') or user_lower.startswith('−'):
            option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {len(options[:6])}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        # IMPORTANT: Sorted by length descending so longer matches are checked first
        # (e.g., "the second one" should match "the second" not "one")
        number_patterns = sorted([
            ("the first", 0), ("number one", 0), ("number 1", 0), ("first", 0), ("one", 0), ("1", 0),
            ("the second", 1), ("number two", 1), ("number 2", 1), ("second", 1), ("two", 1), ("2", 1),
            ("the third", 2), ("number three", 2), ("number 3", 2), ("third", 2), ("three", 2), ("3", 2),
            ("the fourth", 3), ("number four", 3), ("number 4", 3), ("fourth", 3), ("four", 3), ("4", 3),
            ("the fifth", 4), ("number five", 4), ("number 5", 4), ("fifth", 4), ("five", 4), ("5", 4),
            ("the sixth", 5), ("number six", 5), ("number 6", 5), ("sixth", 5), ("six", 5), ("6", 5),
        ], key=lambda x: len(x[0]), reverse=True)

        selected_item = None

        # Check for number/ordinal selection (longer patterns first)
        for key, idx in number_patterns:
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("ITEM SELECTION: User selected %s but only %d options available", key, len(options))
                    option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
                    options_str = "\n".join(option_list)
                    return StateMachineResult(
                        message=f"I only have {len(options[:6])} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # Require minimum length to avoid false matches
                if len(user_lower) > 3 and (option_name in user_lower or user_lower in option_name):
                    selected_item = option
                    break
                # Also try matching individual words
                for word in user_lower.split():
                    if len(word) > 3 and word in option_name:
                        selected_item = option
                        break

        if not selected_item:
            # Couldn't determine which one - ask again
            option_list = [f"{i}. {item.get('name', 'Unknown')}" for i, item in enumerate(options[:6], 1)]
            options_str = "\n".join(option_list)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - clear pending state and add the item directly
        selected_name = selected_item.get("name", "item")
        selected_price = selected_item.get("base_price", 0.0)
        selected_id = selected_item.get("id")

        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.clear_pending()

        logger.info("ITEM SELECTION: User chose '%s', adding %d item(s)", selected_name, quantity)

        # Directly create the MenuItemTask(s) - no need to go through add_menu_item
        # since we already have all the item details from pending_item_options
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_id=selected_id,
                unit_price=selected_price,
            )
            item.mark_complete()  # Desserts/simple items don't need configuration
            order.items.add_item(item)

        # Return to taking items phase
        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"Got it, {quantity} {selected_name}{'s' if quantity > 1 and not selected_name.endswith('s') else ''}. Anything else?",
            order=order,
        )
