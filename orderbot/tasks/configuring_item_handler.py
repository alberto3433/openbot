"""
Configuring Item Handler for Order State Machine.

This module handles the configuration of items (answering questions about
items being configured like size, style, toasted, spread, etc.).

Extracted from state_machine.py for better separation of concerns.
"""

import logging

from .models import OrderTask, MenuItemTask, TaskStatus, parse_pending_field
from .pending_fields import PendingField
from .schemas import StateMachineResult, OrderPhase, Selection, ParsedItemEntry
from .parsers.constants import (
    SELECTION_PATTERNS,
    parse_can_you_make_it,
    ANOTHER_ITEM_PATTERN,
    ONE_MORE_PATTERN,
)
from .handler_utils import format_numbered_options
from .modifier_change_handler import ChangeRequest
from .checkout_messages import got_it_anything_else, ErrorMessages
from .config_input_validation import (
    detect_modifier_inquiry,
    is_valid_answer_for_pending_field,
    is_off_topic_request,
)
from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize

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
    ) -> None:
        """
        Initialize the configuring item handler.

        Args:
            config_helper_handler: Handler for config helpers (side choice, etc.).
            checkout_utils_handler: Handler for checkout utilities.
            modifier_change_handler: Handler for modifier changes.
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration (deli sandwiches, espresso, etc.).
        """
        self.config_helper_handler = config_helper_handler
        self.checkout_utils_handler = checkout_utils_handler
        self.modifier_change_handler = modifier_change_handler
        self.item_adder_handler = item_adder_handler
        self.menu_item_handler = menu_item_handler
        # Set via setter after TakingItemsHandler is created (to avoid circular dependency)
        self.taking_items_handler: "TakingItemsHandler | None" = None

    def _process_pending_parsed_items(self, order: OrderTask) -> StateMachineResult | None:
        """Process any pending parsed items stored during disambiguation.

        When user says "latte and bagel" and latte triggers disambiguation,
        the bagel's ParsedItem is stored in order.pending_parsed_items.
        After disambiguation resolves and the latte is configured, this method
        processes the bagel by adding it to the cart and starting its configuration.

        Args:
            order: The current order state

        Returns:
            StateMachineResult if items were processed and need configuration,
            None if no pending items to process.
        """
        if not order.pending_parsed_items or not self.taking_items_handler:
            return None

        logger.info(
            "Processing %d pending parsed items after disambiguation",
            len(order.pending_parsed_items)
        )

        # Pop all pending items to process
        pending_items = order.pending_parsed_items
        order.pending_parsed_items = []

        # Track added items for config queueing
        added_items: list[tuple[str, str, str]] = []  # (item_id, display_name, item_type)

        for item_dict in pending_items:
            # Reconstruct ParsedItemEntry from stored dict
            try:
                parsed_item = ParsedItemEntry(**item_dict)
            except Exception as e:
                logger.warning("Failed to reconstruct ParsedItemEntry: %s", e)
                continue

            # Process through taking_items_handler._add_parsed_item
            items_before_count = len(order.items.items)
            order, summary, disambiguation_result = self.taking_items_handler._add_parsed_item(
                parsed_item, order
            )

            # If another disambiguation was triggered, store remaining items and return
            if disambiguation_result:
                logger.info("Nested disambiguation triggered for pending item")
                # Store any remaining pending items
                remaining_idx = pending_items.index(item_dict) + 1
                if remaining_idx < len(pending_items):
                    order.pending_parsed_items = pending_items[remaining_idx:]
                # Queue already-added items for config
                for item_id, display_name, item_type in added_items:
                    item = order.items.get_item_by_id(item_id)
                    if item and item.status == TaskStatus.IN_PROGRESS:
                        order.queue_item_for_config(item_id, item_type, item_name=display_name)
                return disambiguation_result

            # Track newly added items
            if summary:
                new_items = order.items.items[items_before_count:]
                for new_item in new_items:
                    added_items.append((
                        new_item.id,
                        new_item.get_display_name(),
                        parsed_item.item_type
                    ))
                    logger.info(
                        "Added pending item: %s (%s)",
                        new_item.get_display_name(),
                        new_item.id[:8]
                    )

        # Queue items that need configuration (IN_PROGRESS status)
        items_needing_config = []
        for item_id, display_name, item_type in added_items:
            item = order.items.get_item_by_id(item_id)
            if item and item.status == TaskStatus.IN_PROGRESS:
                items_needing_config.append((item_id, display_name, item_type))

        if not items_needing_config:
            # All items were complete - nothing more to configure
            return None

        # Queue items 2+ for later configuration
        for item_id, item_name, item_type in items_needing_config[1:]:
            order.queue_item_for_config(item_id, item_type, item_name=item_name)
            logger.info("Queued pending item %s (%s) for config", item_name, item_id[:8])

        # Start configuration for the first item
        first_item_id, first_item_name, first_item_type = items_needing_config[0]
        first_item = order.items.get_item_by_id(first_item_id)

        if isinstance(first_item, MenuItemTask) and self.menu_item_handler:
            logger.info(
                "Starting configuration for pending item: %s (%s)",
                first_item_name, first_item_id[:8]
            )
            return self.menu_item_handler.get_first_question(first_item, order)

        # Fallback
        order.pending_item_id = first_item_id
        order.set_phase(OrderPhase.CONFIGURING_ITEM)
        return StateMachineResult(
            message=f"Got it, {first_item_name}! Any preferences?",
            order=order,
        )

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
            return self._handle_item_selection(user_input, order)

        # Handle modifier selection (disambiguation for modifiers like "cream cheese")
        if order.pending_field == PendingField.MODIFIER_SELECTION:
            return self._handle_modifier_selection(user_input, order)

        # Handle duplicate selection when user said "another one" with multiple items in cart
        if order.pending_field == PendingField.DUPLICATE_SELECTION:
            return self.taking_items_handler.handle_duplicate_selection(user_input, order)

        # Handle "same thing" clarification when user has both previous order AND cart items
        if order.pending_field == PendingField.SAME_THING_CLARIFICATION:
            return self.taking_items_handler.handle_same_thing_clarification(user_input, order)

        # Handle suggested item confirmation ("Would you like to order one?" -> "yes" / "give me one")
        if order.pending_field == PendingField.CONFIRM_SUGGESTED_ITEM:
            return self.taking_items_handler.handle_confirm_suggested_item(user_input, order)

        # Handle item switch confirmation ("can you make it X?" -> similar item found)
        if order.pending_field == PendingField.CONFIRM_ITEM_SWITCH:
            return self._handle_confirm_item_switch(user_input, order)

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
            result = self._apply_modification_during_config(change_request, item, order)
            if result:
                return result
            # If couldn't apply, fall through to normal processing

        # Check for "can you make it X?" style requests (e.g., "can you make it iced?")
        # This handles users asking to modify an aspect of the item being configured
        if not is_valid_answer and isinstance(item, MenuItemTask):
            can_you_make_it_result = self._handle_can_you_make_it(user_input, item, order)
            if can_you_make_it_result:
                return can_you_make_it_result

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
            and self.taking_items_handler
            and self.taking_items_handler.store_info_handler
            and order.pending_field != PendingField.CUSTOMIZATION_CHECKPOINT
            and not pending_is_attr_config):
            logger.info("MODIFIER INQUIRY during config: category='%s'", modifier_category)
            return self.taking_items_handler.store_info_handler.handle_modifier_inquiry(
                None,  # item_type - not specified
                modifier_category,  # category extracted from query
                order,
            )

        return None

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
            options_str = format_numbered_options(options)
            return StateMachineResult(
                message=f"Please choose a number from 1 to {min(len(options), 6)}:\n{options_str}",
                order=order,
            )

        # Try to match by number (1, 2, 3, "first", "second", etc.)
        # Uses shared SELECTION_PATTERNS from constants (sorted by length descending)
        selected_item = None

        # Check for number/ordinal selection (longer patterns first)
        for key, idx in SELECTION_PATTERNS:
            if key in user_lower:
                if idx < len(options):
                    selected_item = options[idx]
                    break
                else:
                    # User selected a number that's out of range - ask again
                    logger.info("ITEM SELECTION: User selected %s but only %d options available", key, len(options))
                    options_str = format_numbered_options(options)
                    return StateMachineResult(
                        message=f"I only have {min(len(options), 6)} options. Please choose:\n{options_str}",
                        order=order,
                    )

        # If not found by number, try to match by name
        if not selected_item:
            for option in options:
                option_name = option.get("name", "").lower()
                # Check if the option name is in user input or vice versa
                # Require minimum length to avoid false matches
                if len(user_lower) >= 3 and (option_name in user_lower or user_lower in option_name):
                    selected_item = option
                    break
                # Also try matching individual words
                for word in user_lower.split():
                    if len(word) >= 3 and word in option_name:
                        selected_item = option
                        break

        if not selected_item:
            # Couldn't determine which one - ask again
            options_str = format_numbered_options(options)
            return StateMachineResult(
                message=f"I didn't catch which one. Please choose:\n{options_str}",
                order=order,
            )

        # Found the selection - clear pending state
        selected_name = selected_item.get("name", "item")
        selected_price = selected_item.get("base_price", 0.0)
        selected_id = selected_item.get("id")
        selected_item_type = selected_item.get("item_type")

        # Get any pre-filled modifiers from disambiguation (size, milk, etc.)
        # Filter out structural keys that aren't actual item attributes
        raw_pre_filled = order.pending_item_modifiers or {}
        non_attribute_keys = {"item_name", "quantity", "original_input", "item_type", "extracted_selections"}
        pre_filled = {k: v for k, v in raw_pre_filled.items() if k not in non_attribute_keys}

        # Extract and convert selections (stored as dicts for JSON serialization)
        stored_selections = raw_pre_filled.get("extracted_selections")
        extracted_selections = None
        if stored_selections:
            extracted_selections = [
                Selection(**s) if isinstance(s, dict) else s
                for s in stored_selections
            ]

        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.pending_item_modifiers = None
        order.clear_pending()

        logger.info("ITEM SELECTION: User chose '%s' (type=%s), adding %d item(s)",
                    selected_name, selected_item_type, quantity)

        # Check if item type is configurable (has conversation attributes like size, temperature)
        configurable_types = menu_cache.get_configurable_item_types()
        is_configurable = selected_item_type in configurable_types if selected_item_type else False

        # For configurable items (sized_beverage, bagel, etc.), route through proper config flow
        if is_configurable and self.item_adder_handler:
            menu_item = {
                "name": selected_name,
                "id": selected_id,
                "base_price": selected_price,
                "item_type": selected_item_type,
            }
            return self.item_adder_handler._create_configurable_item(
                menu_item=menu_item,
                order=order,
                quantity=quantity,
                pre_filled_attributes=pre_filled if pre_filled else None,
                extracted_selections=extracted_selections,
            )

        # For non-configurable items, use direct creation
        # Check if item type requires side choice (data-driven from database)
        requires_side_choice = (
            menu_cache.item_type_has_side_choice(selected_item_type)
            if selected_item_type else False
        )

        # Directly create the MenuItemTask(s) for non-configurable items
        first_item = None
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=selected_name,
                menu_item_id=selected_id,
                unit_price=selected_price,
                menu_item_type=selected_item_type,
            )
            # Infer attributes from item name (data-driven)
            if self.item_adder_handler:
                self.item_adder_handler._infer_attributes_from_item_name(item)
            if requires_side_choice:
                item.mark_in_progress()  # Items with side choice need configuration
            else:
                item.mark_complete()  # Simple items don't need configuration
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        if requires_side_choice:
            # Get the side choice attribute question from database
            side_choice_attr = menu_cache.get_side_choice_attribute(selected_item_type)
            question = (
                side_choice_attr.get("question_text") if side_choice_attr
                else f"Would you like a bagel or fruit salad with your {selected_name}?"
            )
            # Set state to wait for side choice
            order.set_phase(OrderPhase.CONFIGURING_ITEM)
            order.pending_item_id = first_item.id
            order.pending_field = PendingField.SIDE_CHOICE
            return StateMachineResult(
                message=question,
                order=order,
            )

        # Check if there are pending parsed items that haven't been added yet
        # This handles the case where disambiguation was triggered and remaining items
        # in the order were stored (e.g., "latte and bagel" - bagel is stored while
        # we disambiguate latte type)
        pending_result = self._process_pending_parsed_items(order)
        if pending_result:
            return pending_result

        # Check if there are other items queued for configuration
        # This handles the case where disambiguation was triggered after other items
        # were already added (e.g., "an everything bagel and a latte")
        if order.has_queued_config_items() and self.menu_item_handler:
            next_config = order.pop_next_config_item()
            next_item = order.items.get_item_by_id(next_config["item_id"])
            if next_item and isinstance(next_item, MenuItemTask):
                logger.info(
                    "Processing queued item after disambiguation: %s (%s)",
                    next_config.get("item_name"), next_config["item_id"][:8]
                )
                return self.menu_item_handler.get_first_question(next_item, order)

        # Return to taking items phase for items not requiring side choice
        order.set_phase(OrderPhase.TAKING_ITEMS)
        item_description = f"{quantity} {pluralize(selected_name) if quantity > 1 else selected_name}"
        return StateMachineResult(
            message=got_it_anything_else(item_description),
            order=order,
        )

    def _handle_modifier_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting from multiple modifier options (e.g., cream cheese types)."""
        if not order.pending_item_options:
            order.clear_pending()
            order.pending_modifier_target_item_index = None
            order.pending_modifier_quantity = None
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        # Get the disambiguation handler through taking_items_handler
        disambiguation = self.taking_items_handler.item_adder_handler.disambiguation_handler

        # Use existing disambiguation resolution
        selected = disambiguation.resolve_disambiguation(user_input, order)

        if not selected:
            # Couldn't match - re-ask
            return StateMachineResult(
                message=disambiguation.get_reask_message(order),
                order=order,
            )

        # Get the target item and add the modifier
        target_idx = order.pending_modifier_target_item_index
        if target_idx is None or target_idx >= len(order.items.items):
            disambiguation.clear_disambiguation_state(order)
            order.pending_modifier_target_item_index = None
            order.pending_modifier_quantity = None
            return StateMachineResult(
                message=ErrorMessages.WHAT_ELSE,
                order=order,
            )

        target_item = order.items.items[target_idx]
        quantity = order.pending_modifier_quantity or 1

        # Add the selected modifier to the item
        if isinstance(target_item, MenuItemTask):
            target_item.add_selection(
                slug=selected["slug"],
                category=selected["category"],
                display_name=selected["name"],
                quantity=quantity,
            )

            # Recalculate price
            if self.taking_items_handler and self.taking_items_handler.pricing:
                self.taking_items_handler.pricing.recalculate_item_price(target_item)

        # Clear disambiguation state
        disambiguation.clear_disambiguation_state(order)
        order.pending_modifier_target_item_index = None
        order.pending_modifier_quantity = None

        logger.info("MODIFIER SELECTION: User chose '%s', added to item", selected["name"])

        # Return to taking items phase
        order.set_phase(OrderPhase.TAKING_ITEMS)
        return StateMachineResult(
            message=f"Added {selected['name']}. Anything else?",
            order=order,
        )

    def _handle_can_you_make_it(
        self,
        user_input: str,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """
        Handle 'can you make it X?' requests during item configuration.

        When user asks "can you make it iced?" while being asked about size:
        1. Check if the current item has an attribute option matching "iced"
        2. If yes, apply it and continue with normal configuration
        3. If not, search for a similar menu item with that modifier
        4. Offer to switch or report "Sorry, we don't have that option"

        Args:
            user_input: The user's input text
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if handled, None if not a "can you make it X?" request
        """
        modifier = parse_can_you_make_it(user_input)
        if not modifier:
            return None

        logger.info("CAN_YOU_MAKE_IT: Detected modifier request '%s' for %s", modifier, item.menu_item_name)
        modifier_lower = modifier.lower()

        # 1. Check if current item has an attribute option matching this modifier
        item_type = item.menu_item_type
        if item_type:
            try:
                attrs = menu_cache.get_item_type_attributes(item_type)
                for attr_slug, attr_config in attrs.items():
                    for opt in attr_config.get("options", []):
                        opt_slug = opt.get("slug", "").lower()
                        opt_display = opt.get("display_name", "").lower()
                        if modifier_lower == opt_slug or modifier_lower == opt_display:
                            # Found matching attribute option - apply it
                            logger.info("CAN_YOU_MAKE_IT: Found matching attr %s=%s", attr_slug, opt_slug)
                            item.set_attribute(attr_slug, opt.get("slug"))
                            # Re-ask current question (the one we were on)
                            current_question = self.config_helper_handler.get_current_config_question(order, item)
                            if current_question:
                                return StateMachineResult(
                                    message=f"Sure! {current_question}",
                                    order=order,
                                )
                            return None  # Continue with normal flow
            except Exception as e:
                logger.debug("Error checking attributes for 'can you make it': %s", e)

        # 2. Check if it's an ingredient/modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(modifier_lower)
        if len(matches) == 1:
            match = matches[0]
            self._replace_or_add_modifier(item, match)
            logger.info("CAN_YOU_MAKE_IT: Applied modifier %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )
        elif len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("CAN_YOU_MAKE_IT: Multiple matches for '%s', starting disambiguation", modifier)
            return self._start_modifier_disambiguation(modifier, matches, item, order)

        # 3. Search for similar menu item with the modifier
        if self.item_adder_handler and self.item_adder_handler.menu_lookup:
            similar_item = self.item_adder_handler.menu_lookup.find_similar_item_with_modifier(
                item.menu_item_name or "",
                modifier,
            )
            if similar_item:
                logger.info(
                    "CAN_YOU_MAKE_IT: Found similar item '%s' for '%s' + '%s'",
                    similar_item.get("name"),
                    item.menu_item_name,
                    modifier,
                )
                # Offer to switch
                order.pending_switch_item = similar_item
                order.pending_field = PendingField.CONFIRM_ITEM_SWITCH
                return StateMachineResult(
                    message=(
                        f"{item.menu_item_name} isn't available {modifier}, "
                        f"but we have {similar_item.get('name')}. Would you like that instead?"
                    ),
                    order=order,
                )

        # 4. Not found - report and re-ask
        logger.info("CAN_YOU_MAKE_IT: No matching attribute, ingredient, or similar item found for '%s'", modifier)
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(
                message=f"Sorry, we don't have that option. {current_question}",
                order=order,
            )
        return StateMachineResult(
            message="Sorry, we don't have that option.",
            order=order,
        )

    def _handle_confirm_item_switch(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle user confirmation for item switch (from "can you make it X?").

        Args:
            user_input: The user's response (yes/no)
            order: The current order state

        Returns:
            StateMachineResult with next action
        """
        switch_item = order.pending_switch_item
        if not switch_item:
            order.clear_pending()
            return StateMachineResult(
                message="What would you like to order?",
                order=order,
            )

        from .response_utils import is_affirmative

        if is_affirmative(user_input):
            # Get the current item being configured and remove it
            current_item = order.items.get_item_by_id(order.pending_item_id)
            if current_item:
                order.items.remove_item(current_item)

            # Clear switch state
            order.pending_switch_item = None
            order.clear_pending()

            # Add the new item via item_adder_handler
            if self.item_adder_handler:
                return self.item_adder_handler.add_menu_item(
                    switch_item.get("name", "item"),
                    order,
                    quantity=1,
                )

            # Fallback - just acknowledge
            order.set_phase(OrderPhase.TAKING_ITEMS)
            return StateMachineResult(
                message=got_it_anything_else(switch_item.get('name')),
                order=order,
            )
        else:
            # User declined - continue with original item
            order.pending_switch_item = None
            # Get the original item and continue configuration
            original_item = order.items.get_item_by_id(order.pending_item_id)
            if original_item:
                # Clear the confirm_item_switch field and restore previous config state
                # Get the next question for the original item
                if isinstance(original_item, MenuItemTask) and self.menu_item_handler:
                    order.pending_field = None  # Clear to let get_first_question set it
                    return self.menu_item_handler.get_first_question(original_item, order)

            order.clear_pending()
            return StateMachineResult(
                message="No problem. What else can I help you with?",
                order=order,
            )

    def _apply_modification_during_config(
        self,
        change_request: ChangeRequest,
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Apply a modification to the item being configured, then continue config.

        This handles the case where a user says something like "make it veggie cream cheese"
        during item configuration. Instead of deferring the change, we apply it immediately
        and continue with the remaining configuration questions.

        Args:
            change_request: The detected change request
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult if the change was applied, None if we couldn't apply it
        """
        new_value = change_request.new_value
        logger.info("APPLY_MOD_DURING_CONFIG: Attempting to apply '%s' to item being configured", new_value)

        # Case 1: Unambiguous attribute change (bread, size, toasted, temperature)
        if not change_request.is_ambiguous and change_request.possible_attributes:
            attr_slug = change_request.possible_attributes[0]
            if attr_slug != "unknown":
                result = self.modifier_change_handler.apply_change(
                    order, item.id, attr_slug, new_value
                )
                if result.success:
                    logger.info("APPLY_MOD_DURING_CONFIG: Applied attribute change %s=%s", attr_slug, new_value)
                    return self._continue_config_with_message(
                        f"Sure, I've changed that to {new_value}.", item, order
                    )

        # Case 2: Try as modifier (spread, topping, syrup, etc.)
        matches = menu_cache.find_matching_ingredients(new_value.lower())

        if len(matches) == 1:
            match = matches[0]
            # Replace or add the modifier
            self._replace_or_add_modifier(item, match)
            logger.info("APPLY_MOD_DURING_CONFIG: Applied modifier change %s (%s)", match['name'], match['category'])
            return self._continue_config_with_message(
                f"Sure, I've changed the {match['category']} to {match['name']}.", item, order
            )

        if len(matches) > 1:
            # Multiple matches - need disambiguation
            logger.info("APPLY_MOD_DURING_CONFIG: Multiple matches for '%s', starting disambiguation", new_value)
            return self._start_modifier_disambiguation(new_value, matches, item, order)

        # Couldn't apply - fall through to normal processing
        logger.debug("APPLY_MOD_DURING_CONFIG: Could not apply change for '%s'", new_value)
        return None

    def _replace_or_add_modifier(self, item: MenuItemTask, match: dict) -> None:
        """Replace existing modifier of same category, or add if none exists.

        Args:
            item: The item to modify
            match: Dict with slug, name, category, base_price from find_matching_ingredients()
        """
        category = match["category"]

        # Remove existing modifier of same category (if any)
        item.modifiers = [m for m in item.modifiers if m.get("category") != category]

        # Add new one
        item.add_selection(
            slug=match["slug"],
            category=category,
            display_name=match["name"],
            quantity=1,
            price=match.get("base_price", 0.0),
        )

        # Recalculate price
        if self.modifier_change_handler and self.modifier_change_handler.pricing:
            self.modifier_change_handler.pricing.recalculate_item_price(item)

    def _continue_config_with_message(
        self, message: str, item: MenuItemTask, order: OrderTask
    ) -> StateMachineResult:
        """Return message + next config question, or proceed if item complete.

        Args:
            message: The feedback message about the change that was applied
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult with the message and next question, or checkout transition
        """
        current_question = self.config_helper_handler.get_current_config_question(order, item)
        if current_question:
            return StateMachineResult(message=f"{message} {current_question}", order=order)

        # Item configuration complete - proceed to next question or checkout
        return self.checkout_utils_handler.get_next_question(order)

    def _start_modifier_disambiguation(
        self,
        new_value: str,
        matches: list[dict],
        item: MenuItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Start disambiguation flow for a modifier with multiple matches.

        Args:
            new_value: The modifier value that has multiple matches
            matches: List of matching ingredient dicts
            item: The item being configured
            order: The current order state

        Returns:
            StateMachineResult asking user to select which modifier they want
        """
        # Store the modifier options for disambiguation
        order.pending_item_options = matches
        order.pending_field = PendingField.MODIFIER_SELECTION
        order.pending_modifier_target_item_index = order.items.items.index(item)

        # Build disambiguation message
        option_lines = []
        for i, match in enumerate(matches[:6], 1):
            price_str = ""
            if match.get("base_price", 0) > 0:
                price_str = f" (+${match['base_price']:.2f})"
            option_lines.append(f"{i}. {match['name']}{price_str}")

        options_str = "\n".join(option_lines)
        return StateMachineResult(
            message=f"Which {new_value} would you like?\n{options_str}",
            order=order,
        )
