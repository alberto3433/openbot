"""
Checkout Utilities Handler for Order State Machine.

This module handles checkout-related utility operations including
next question determination, checkout transitions, delivery questions,
and order summary building.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask, ItemTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult
from ..menu_data_cache import menu_cache

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from ..services.message_builder import MessageBuilder
    from .context import OrderContext

logger = logging.getLogger(__name__)


class CheckoutUtilsHandler:
    """
    Handles checkout utility operations.

    Manages next question determination, checkout transitions,
    delivery questions, and order summary building.
    """

    def __init__(
        self,
        config: "HandlerConfig",
        transition_to_next_slot: Callable[[OrderTask], None] | None = None,
    ):
        """
        Initialize the checkout utils handler.

        Args:
            config: HandlerConfig with shared dependencies.
            transition_to_next_slot: Callback to transition to the next slot.
        """
        self._message_builder = config.message_builder

        # Handler-specific callbacks
        self._transition_to_next_slot = transition_to_next_slot
        # Unified callback for item configuration (set after initialization)
        self._configure_next_incomplete_item: Callable[[OrderTask], StateMachineResult] | None = None

        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None

    def set_repeat_order_info(self, is_repeat: bool, last_order_type: str | None) -> None:
        """Set repeat order info for personalized delivery question (legacy method)."""
        self._is_repeat_order = is_repeat
        self._last_order_type = last_order_type

    def set_context(self, ctx: "OrderContext") -> None:
        """Set context from unified OrderContext."""
        self._is_repeat_order = ctx.is_repeat_order
        self._last_order_type = ctx.last_order_type

    def _get_question_for_attribute(
        self,
        pending_field: str,
        item_name: str,
        item_type_slug: str | None,
    ) -> str:
        """
        Get abbreviated question for an attribute using database lookup.

        Parses the pending_field to extract the attribute name, then looks up
        the question text from the database. Falls back to generic question.

        Args:
            pending_field: The pending field in format "item_type:attribute" or just "attribute"
            item_name: Display name of the item for the question
            item_type_slug: The item type slug for database lookup

        Returns:
            Formatted question string like "And the {item_name} - would you like it toasted?"
        """
        # Extract attribute from pending_field
        # Format should be "item_type:attribute" (set by handlers) or just "attribute"
        if ":" in pending_field:
            _, attr_name = pending_field.split(":", 1)
        else:
            attr_name = pending_field

        # Try to get question from database if we have an item type
        db_question = None
        if item_type_slug:
            db_question = menu_cache.get_question_for_field(item_type_slug, attr_name)

        # Build abbreviated question
        if db_question:
            # Format as abbreviated: "And the {item} - {question}"
            q_lower = db_question.lower()
            if q_lower.startswith("would you like"):
                # "Would you like it toasted?" -> "And the X - would you like it toasted?"
                return f"And the {item_name} - {db_question[0].lower()}{db_question[1:]}"
            elif q_lower.startswith("what"):
                # "What size?" -> "And what size for the X?"
                return f"And {db_question[0].lower()}{db_question[1:].rstrip('?')} for the {item_name}?"
            else:
                # Generic format
                return f"And the {item_name} - {db_question}"

        # Fallback to generic question if not in database
        return f"And the {item_name}?"

    def get_next_question(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Determine the next question to ask."""
        # Check for incomplete items that need configuration
        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                # Use unified callback for all incomplete items (data-driven)
                if isinstance(item, MenuItemTask) and self._configure_next_incomplete_item:
                    logger.info("Found incomplete item, using unified handler")
                    return self._configure_next_incomplete_item(order)
                # No unified callback - log warning
                logger.warning("Found in-progress item but no unified handler configured: %s",
                              item.menu_item_name if isinstance(item, MenuItemTask) else item)

        # Check if there are items queued for configuration
        # Loop until we find an incomplete item or queue is empty (defensive safeguard)
        while order.has_queued_config_items():
            next_config = order.pop_next_config_item()
            if not next_config:
                break

            item_id = next_config.get("item_id")
            item_type = next_config.get("item_type")
            item_name = next_config.get("item_name")
            pending_field = next_config.get("pending_field")
            logger.info("Processing queued config item: id=%s, type=%s, name=%s, field=%s",
                        item_id[:8] if item_id else None, item_type, item_name, pending_field)

            # Handle item disambiguation (when a keyword matched multiple menu items)
            if item_type == "item_disambiguation" and order.pending_item_options:
                logger.info("Processing queued item disambiguation")
                order.pending_field = "item_selection"
                order.phase = OrderPhase.CONFIGURING_ITEM.value
                # Build the clarification message
                option_list = []
                for i, option_item in enumerate(order.pending_item_options, 1):
                    name = option_item.get("name", "Unknown")
                    price = option_item.get("base_price", 0)
                    if price > 0:
                        option_list.append(f"{i}. {name} (${price:.2f})")
                    else:
                        option_list.append(f"{i}. {name}")
                options_str = "\n".join(option_list)
                return StateMachineResult(
                    message=f"We have a few options:\n{options_str}\nWhich would you like?",
                    order=order,
                )

            # Find the target item and check if it still needs configuration
            target_item = None
            for item in order.items.items:
                if item.id == item_id:
                    target_item = item
                    break

            # Defensive check: skip if item is already complete
            if target_item and target_item.status == TaskStatus.COMPLETE:
                logger.info("Skipping already-complete item in queue: id=%s, type=%s",
                           item_id[:8] if item_id else None, item_type)
                continue  # Pop next item from queue

            # If we have item_name and pending_field from multi-item processing,
            # use abbreviated question format via database lookup
            if item_name and pending_field:
                order.pending_item_id = item_id
                order.pending_field = pending_field
                order.phase = OrderPhase.CONFIGURING_ITEM.value

                # Get item type for database lookup
                item_type_slug = None
                if target_item and isinstance(target_item, MenuItemTask):
                    item_type_slug = target_item.menu_item_type

                # Build question using database lookup
                question = self._get_question_for_attribute(pending_field, item_name, item_type_slug)

                return StateMachineResult(message=question, order=order)

            # Fall back to unified config handler for queued items without names
            if target_item and isinstance(target_item, MenuItemTask):
                if self._configure_next_incomplete_item:
                    return self._configure_next_incomplete_item(order)

            # If we get here, item wasn't handled - log and continue to next
            logger.warning("Queued config item not handled: id=%s, type=%s",
                          item_id[:8] if item_id else None, item_type)

        # Check if we just finished configuring a multi-item order
        # If so, give a summary like "Great, both toasted. Anything else?"
        if order.multi_item_config_names:
            config_names = order.multi_item_config_names
            order.multi_item_config_names = []  # Clear for next time

            # Build summary based on the number of items configured
            num_items = len(config_names)
            if num_items == 2:
                summary = f"Great, {config_names[0]} and {config_names[1]} - both added."
            elif num_items == 3:
                summary = f"Great, {config_names[0]}, {config_names[1]}, and {config_names[2]} - all added."
            elif num_items > 3:
                items_str = ", ".join(config_names[:-1]) + f", and {config_names[-1]}"
                summary = f"Great, {items_str} - all added."
            else:
                summary = f"Great, {config_names[0]} added."

            order.phase = OrderPhase.TAKING_ITEMS.value
            return StateMachineResult(
                message=f"{summary} Anything else?",
                order=order,
            )

        # Ask if they want anything else
        items = order.items.get_active_items()
        if items:
            # Count consecutive identical items at the end of the list
            last_item = items[-1]
            # Use get_summary() for all item types (data-driven)
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
        elif order.phase == OrderPhase.CHECKOUT_DELIVERY.value:
            # Handle CHECKOUT_DELIVERY phase - could be asking for order type OR address
            if order.delivery_method.order_type == "delivery":
                # Order type already set to delivery, need address
                logger.info("CHECKOUT: Asking for delivery address (order_type already set)")
                return StateMachineResult(
                    message="What's the delivery address?",
                    order=order,
                )
            else:
                # Order type not set yet, ask pickup/delivery
                logger.info("CHECKOUT: Asking for pickup/delivery")
                return StateMachineResult(
                    message=self.get_delivery_question(),
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
