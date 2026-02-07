"""
Config Selection Handler for Order State Machine.

Handles item and modifier selection/disambiguation flows during item configuration.
Extracted from configuring_item_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask, TaskStatus
from .schemas import StateMachineResult, OrderPhase, Selection, ParsedItemEntry
from .parsers.selection_patterns import SELECTION_PATTERNS
from .utils.text import format_numbered_list
from .checkout_messages import got_it_anything_else, ErrorMessages
from .pending_fields import PendingField
from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize
from .utils.pricing_utils import safe_recalculate_price

if TYPE_CHECKING:
    from .item_adder_handler import ItemAdderHandler
    from .config import MenuItemConfigHandler
    from .taking_items_handler import TakingItemsHandler

logger = logging.getLogger(__name__)


class ConfigSelectionHandler:
    """
    Handles item selection and modifier disambiguation flows.

    When the user needs to select from multiple options (e.g., which type of cookie,
    which type of cream cheese), this handler processes their selection and continues
    the order flow.
    """

    def __init__(
        self,
        item_adder_handler: "ItemAdderHandler | None" = None,
        menu_item_handler: "MenuItemConfigHandler | None" = None,
    ) -> None:
        """
        Initialize the config selection handler.

        Args:
            item_adder_handler: Handler for adding items.
            menu_item_handler: Handler for menu item configuration.
        """
        self.item_adder_handler = item_adder_handler
        self.menu_item_handler = menu_item_handler
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

    def process_pending_parsed_items(self, order: OrderTask) -> StateMachineResult | None:
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
        if not order.pending_parsed_items or not self._taking_items_handler:
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
            order, summary, disambiguation_result = self._taking_items_handler._add_parsed_item(
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

    def handle_item_selection(
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
        if user_lower.startswith('-') or user_lower.startswith('\u2212'):
            options_str = format_numbered_list(options)
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
                    options_str = format_numbered_list(options)
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
            options_str = format_numbered_list(options)
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
            # Check if selected item is a signature item (e.g., "The Classic BEC")
            is_signature = menu_cache.item_has_default_ingredients(selected_name)
            menu_item = {
                "name": selected_name,
                "id": selected_id,
                "base_price": selected_price,
                "item_type": selected_item_type,
                "is_signature": is_signature,
            }
            return self.item_adder_handler._create_configurable_item(
                menu_item=menu_item,
                order=order,
                quantity=quantity,
                pre_filled_attributes=pre_filled if pre_filled else None,
                extracted_selections=extracted_selections,
            )

        # For non-configurable items, use direct creation
        # Check if item type has component slots (e.g., omelette includes a side)
        has_component_slots = (
            menu_cache.item_type_has_component_slots(selected_item_type)
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
            if has_component_slots:
                item.mark_in_progress()  # Items with component slots need configuration
            else:
                item.mark_complete()  # Simple items don't need configuration
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        if has_component_slots:
            # Get the component slot question from database (e.g., "side" slot)
            side_slot = menu_cache.get_component_slot(selected_item_type, "side")
            if side_slot and side_slot.get("prompt_text"):
                question = side_slot["prompt_text"]
            else:
                # Build question dynamically from options
                options = menu_cache.get_component_slot_options(selected_item_type, "side")
                if options:
                    option_names = [
                        opt.get("display_name") or opt.get("allowed_item_type", "item")
                        for opt in options
                    ]
                    if len(option_names) <= 2:
                        options_str = " or ".join(option_names)
                    else:
                        options_str = ", ".join(option_names[:-1]) + f", or {option_names[-1]}"
                    question = f"Would you like {options_str.lower()} with your {selected_name}?"
                else:
                    question = f"Would you like a side with your {selected_name}?"
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
        pending_result = self.process_pending_parsed_items(order)
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

    def handle_modifier_selection(
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
        disambiguation = self._taking_items_handler.item_adder_handler.disambiguation_handler

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
                price=selected.get("base_price", 0.0),
            )

            # Recalculate price
            pricing = self._taking_items_handler.pricing if self._taking_items_handler else None
            safe_recalculate_price(pricing, target_item, "after modifier selection")

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
