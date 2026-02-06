"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
This handler acts as an orchestrator, delegating to specialized handlers:
- ConfigSelectionHandler: item/modifier selection and disambiguation
- ConfigModificationHandler: mid-config modifications ("can you make it X?", "add bacon")
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask, parse_pending_field
from .pending_fields import PendingField
from .schemas import StateMachineResult, OrderPhase
from .parsers.intent_patterns import ANOTHER_ITEM_PATTERN, ONE_MORE_PATTERN, MAKE_IT_N_CONFIG_PATTERN
from .parsers.quantity_utils import parse_make_it_n_quantity
from .checkout_messages import ErrorMessages
from .config_input_validation import (
    detect_modifier_inquiry,
    is_valid_answer_for_pending_field,
    is_off_topic_request,
)
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .config_helper_handler import ConfigHelperHandler
    from .checkout_utils_handler import CheckoutUtilsHandler
    from .modifier_change_handler import ModifierChangeHandler
    from .item_adder_handler import ItemAdderHandler
    from .config import MenuItemConfigHandler
    from .taking_items_handler import TakingItemsHandler
    from .config_selection_handler import ConfigSelectionHandler
    from .config_modification_handler import ConfigModificationHandler

logger = logging.getLogger(__name__)


class ConfiguringItemHandler:
    """
    Handles configuring items (answering configuration questions).

    Routes user input to the appropriate field-specific handler based
    on the pending_field in the order. The pending_field format is
    "item_type:attr_slug" (e.g., "bagel:toasted", "sized_beverage:size").
    """

    def __init__(
        self,
        config_helper_handler: "ConfigHelperHandler | None" = None,
        checkout_utils_handler: "CheckoutUtilsHandler | None" = None,
        modifier_change_handler: "ModifierChangeHandler | None" = None,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
        config_selection_handler: "ConfigSelectionHandler | None" = None,
        config_modification_handler: "ConfigModificationHandler | None" = None,
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, espresso, etc.).
            config_selection_handler: Handler for item/modifier selection flows.
            config_modification_handler: Handler for mid-config modifications.
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        self.menu_item_handler = menu_item_handler
        self.config_selection_handler = config_selection_handler
        self.config_modification_handler = config_modification_handler
        # Set via setter after TakingItemsHandler is created (to avoid circular dependency)
        self._taking_items_handler: "TakingItemsHandler | None" = None

    @property
    def taking_items_handler(self) -> "TakingItemsHandler | None":
        """Get the taking items handler."""
        return self._taking_items_handler

    @taking_items_handler.setter
    def taking_items_handler(self, handler: "TakingItemsHandler | None") -> None:
        """Set the taking items handler (called after initialization to avoid circular deps)."""
        self._taking_items_handler = handler

    def _process_pending_parsed_items(self, order: OrderTask) -> StateMachineResult | None:
        """Delegate to config_selection_handler for processing pending parsed items.

        This method is kept for backward compatibility with menu_item_handler.
        """
        if self.config_selection_handler:
            return self.config_selection_handler.process_pending_parsed_items(order)
        return None

    def _handle_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to config_selection_handler for item selection.

        This method is kept for backward compatibility with tests.
        """
        return self.config_selection_handler.handle_item_selection(user_input, order)

    def _handle_modifier_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Delegate to config_selection_handler for modifier selection.

        This method is kept for backward compatibility with tests.
        """
        return self.config_selection_handler.handle_modifier_selection(user_input, order)

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
        # Handle generic item selection when multiple options were presented
        if order.pending_field == PendingField.ITEM_SELECTION:
            return self.config_selection_handler.handle_item_selection(user_input, order)

        # Handle modifier selection (disambiguation for modifiers like "cream cheese")
        if order.pending_field == PendingField.MODIFIER_SELECTION:
            return self.config_selection_handler.handle_modifier_selection(user_input, order)

        # Handle duplicate selection when user said "another one" with multiple items in cart
        if order.pending_field == PendingField.DUPLICATE_SELECTION:
            return self._taking_items_handler.handle_duplicate_selection(user_input, order)

        # Handle "same thing" clarification when user has both previous order AND cart items
        if order.pending_field == PendingField.SAME_THING_CLARIFICATION:
            return self._taking_items_handler.handle_same_thing_clarification(user_input, order)

        # Handle suggested item confirmation ("Would you like to order one?" -> "yes" / "give me one")
        if order.pending_field == PendingField.CONFIRM_SUGGESTED_ITEM:
            return self._taking_items_handler.handle_confirm_suggested_item(user_input, order)

        # Handle ingredient suggestion confirmation ("Would you like one of those?" -> "yes")
        if order.pending_field == PendingField.CONFIRM_INGREDIENT_SUGGESTION:
            return self._taking_items_handler.handle_confirm_ingredient_suggestion(user_input, order)

        # Handle dietary follow-up confirmation ("Would you like to see our vegan options?" -> "yes")
        if order.pending_field == PendingField.CONFIRM_DIETARY_FOLLOWUP:
            return self._taking_items_handler.handle_confirm_dietary_followup(user_input, order)

        # Handle quantity addition selection ("add 3" with multiple item types in cart)
        if order.pending_field == PendingField.QUANTITY_ADDITION_SELECTION:
            return self._taking_items_handler.handle_quantity_addition_selection(user_input, order)

        # Handle item switch confirmation ("can you make it X?" -> similar item found)
        if order.pending_field == PendingField.CONFIRM_ITEM_SWITCH:
            return self.config_modification_handler.handle_confirm_item_switch(user_input, order)

        item = order.items.get_item_by_id(order.pending_item_id)
        if item is None:
            order.clear_pending()
            return StateMachineResult(
                message=ErrorMessages.WHAT_TO_ORDER,
                order=order,
            )

        interceptor_result = self._check_config_interceptors(user_input, item, order)
        if interceptor_result:
            return interceptor_result

        # Route to field-specific handler
        if order.pending_field == PendingField.SIDE_CHOICE:
            return self.config_helper_handler.handle_side_choice(user_input, item, order)

        # Handle menu item configuration (deli sandwiches, etc.)
        if order.pending_field == PendingField.CUSTOMIZATION_CHECKPOINT:
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_checkpoint(user_input, item, order)
        elif order.pending_field == PendingField.CUSTOMIZATION_SELECTION:
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                return self.menu_item_handler.handle_customization_selection(user_input, item, order)

        # Data-driven routing: pending_field format is "item_type:attr_slug"
        # Parse the pending_field and route to the appropriate handler
        item_type_slug, attr_slug = parse_pending_field(order.pending_field)
        if item_type_slug and attr_slug and isinstance(item, MenuItemTask) and self.menu_item_handler:
            # Special case: side_choice attribute should use component slot handler
            # which has the full list of options (bagel + fruit salad)
            if attr_slug == "side_choice" and menu_cache.item_type_has_component_slots(item_type_slug):
                logger.debug(
                    "Routing side_choice attr to component slot handler for %s",
                    item_type_slug
                )
                return self.config_helper_handler.handle_side_choice(user_input, item, order)
            logger.debug(
                "Routing '%s' through unified handler for %s attr=%s",
                order.pending_field, item_type_slug, attr_slug
            )
            return self.menu_item_handler.handle_attribute_input(user_input, item, order, attr_slug)

        # Handle queued menu item configuration (abbreviated flow from checkout_utils_handler)
        # This is set when a menu item is in the config queue and asked an abbreviated question
        # like "And what type of bread for the {item_name}?" - we need to capture the answer
        # and continue with the full configuration flow
        elif order.pending_field == PendingField.MENU_ITEM_CONFIG:
            if isinstance(item, MenuItemTask) and self.menu_item_handler:
                # Capture any attributes mentioned in user input (e.g., bread type)
                self.menu_item_handler.capture_attributes_from_input(user_input, item)
                # Continue with full configuration flow - this will ask the next
                # unanswered mandatory attribute (e.g., toasted) or move to checkout
                return self.menu_item_handler.get_first_question(item, order)

        # Default: unknown pending_field, advance to next question
        order.clear_pending()
        return self.checkout_utils_handler.get_next_question(order)

    def _check_config_interceptors(
        self, user_input: str, item, order: OrderTask
    ) -> StateMachineResult | None:
        """Run pre-routing interceptors during item configuration.

        Checks for cancellation, change requests, off-topic input,
        and modifier inquiries before routing to field-specific handlers.

        Returns:
            StateMachineResult if an interceptor handled the input, None to continue.
        """
        # Check for cancellation requests BEFORE routing to field-specific handlers
        # This allows "remove the coffee", "cancel this", "remove the coffees" etc. during configuration
        cancel_result = self.config_helper_handler.check_cancellation_during_config(user_input, item, order)
        if cancel_result:
            return cancel_result

        # Check for quantity change requests like "make it two hot teas"
        # This allows users to change the quantity of the item being configured
        quantity_result = self._handle_quantity_change_during_config(user_input, item, order)
        if quantity_result:
            return quantity_result

        # Check for "another item" request - redirect to finish current config first
        # e.g., "another latte" or "one more bagel" while configuring size
        another_match = ANOTHER_ITEM_PATTERN.match(user_input)
        one_more_match = ONE_MORE_PATTERN.match(user_input)
        if another_match or one_more_match:
            item_name = item.get_display_name()
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                message = f"Let's finish customizing the {item_name}. {current_question}"
            else:
                message = f"Let's finish customizing the {item_name} first."
            return StateMachineResult(message=message, order=order)

        # Check for "and a X" / "also X" patterns that add new items mid-config
        # This must run BEFORE is_valid_answer check to prevent "blueberry" being
        # matched as a bread option when user says "and a Blueberry Cream Cheese Sandwich"
        if isinstance(item, MenuItemTask):
            add_item_result = self.config_modification_handler.handle_add_item_during_config(
                user_input, item, order
            )
            if add_item_result:
                return add_item_result

        # Context-aware check: if input could be a valid answer to the current question,
        # skip change request and off-topic detection. This prevents "I want avocado" from
        # being misinterpreted as a change request or off-topic when asked about toppings.
        is_valid_answer = is_valid_answer_for_pending_field(user_input, order.pending_field)
        if is_valid_answer:
            logger.debug("Input is valid answer for %s - skipping change/off-topic detection", order.pending_field)

        # Check for modifier change requests during configuration
        # If detected, try to apply immediately instead of deferring
        change_request = None if is_valid_answer else self.modifier_change_handler.detect_change_request(user_input)
        if change_request and isinstance(item, MenuItemTask):
            result = self.config_modification_handler.apply_modification_during_config(change_request, item, order)
            if result:
                return result
            # If couldn't apply, fall through to normal processing

        # Check for "can you make it X?" style requests (e.g., "can you make it iced?")
        # This handles users asking to modify an aspect of the item being configured
        # Skip at customization_checkpoint - let the checkpoint handler use direct_option_matcher
        # which properly handles pricing/upcharges (e.g., "make it 3 eggs" -> upcharge for extra egg)
        if (not is_valid_answer
            and isinstance(item, MenuItemTask)
            and order.pending_field != PendingField.CUSTOMIZATION_CHECKPOINT):
            can_you_make_it_result = self.config_modification_handler.handle_can_you_make_it(user_input, item, order)
            if can_you_make_it_result:
                return can_you_make_it_result

        # Check for "add X" patterns during configuration (e.g., "add bacon and cheese")
        # Parse and apply the modifiers to the current item, then continue with config
        if not is_valid_answer and isinstance(item, MenuItemTask):
            add_result = self.config_modification_handler.handle_add_modifiers_during_config(user_input, item, order)
            if add_result:
                return add_result

        # Check for off-topic requests during configuration (e.g., "what syrups do you have?", "add vanilla syrup")
        # If detected, politely redirect back to the current configuration question
        # Note: Questions relevant to the current config (e.g., "what cream cheese do you have?" when asked about spread) are allowed
        # Skip this check if we already determined the input is a valid answer
        if not is_valid_answer and is_off_topic_request(user_input, order.pending_field):
            logger.info("OFF-TOPIC REQUEST: Detected during config: '%s'", user_input[:50])
            # Get a friendly description of the item being configured
            item_name = item.get_summary() if hasattr(item, 'get_summary') else "your item"
            current_question = self.config_helper_handler.get_current_config_question(order, item)
            if current_question:
                msg = f"Let's finish with your {item_name} first. {current_question}"
            else:
                msg = f"Let's finish with your {item_name} first."
            return StateMachineResult(message=msg, order=order)

        # Check for modifier inquiries like "what toppings do you have?" that passed the off-topic check
        # These should be routed to the store_info_handler for proper pagination support
        # EXCEPT when at customization_checkpoint or in attribute configuration (item_type:attr_slug)
        # - customization_checkpoint: handle_customization_checkpoint() has proper options inquiry handling
        # - item_type:attr_slug: handle_attribute_input() has _detect_different_attribute_inquiry()
        modifier_category = detect_modifier_inquiry(user_input)
        pending_is_attr_config = order.pending_field and ":" in order.pending_field
        if (modifier_category
            and self._taking_items_handler
            and self._taking_items_handler.store_info_handler
            and order.pending_field != PendingField.CUSTOMIZATION_CHECKPOINT
            and not pending_is_attr_config):
            logger.info("MODIFIER INQUIRY during config: category='%s'", modifier_category)
            return self._taking_items_handler.store_info_handler.handle_modifier_inquiry(
                None,  # item_type - not specified
                modifier_category,  # category extracted from query
                order,
            )

        return None

    def _handle_quantity_change_during_config(
        self, user_input: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult | None:
        """Handle quantity change requests during item configuration.

        Detects patterns like "make it two hot teas" or "I want 3 of those"
        and duplicates the current item being configured.

        Args:
            user_input: Raw user input string.
            item: The current item being configured.
            order: Current order state.

        Returns:
            StateMachineResult if quantity change handled, None otherwise.
        """
        if not isinstance(item, MenuItemTask):
            return None

        match = MAKE_IT_N_CONFIG_PATTERN.match(user_input.strip())
        if not match:
            return None

        # Extract the quantity from capture groups
        num_str = None
        for i in range(1, 10):
            group = match.group(i)
            if group:
                num_str = group.lower()
                break

        if not num_str:
            return None

        target_qty = parse_make_it_n_quantity(num_str)
        if not target_qty:
            return None

        # Duplicate the current item to reach target quantity
        # Use mark_complete=False so duplicates stay IN_PROGRESS and get configured
        # after the current item is complete
        item_name = item.get_display_name()
        added_count = target_qty - 1

        for _ in range(added_count):
            order.items.add_item(item.duplicate(mark_complete=False))

        logger.info(
            "QUANTITY CHANGE during config: Added %d more of '%s' (target: %d)",
            added_count, item_name, target_qty
        )

        # Continue with the current config question
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(
                message=f"Sure, I've added {added_count} more {item_name}. {current_question}",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"Sure, I've added {added_count} more {item_name}. Anything else?",
                order=order,
            )
