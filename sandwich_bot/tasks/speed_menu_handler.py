"""
Speed Menu Bagel Handler for Order State Machine.

This module handles the speed menu bagel ordering and configuration flow,
including toasted preference selection.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import SpeedMenuBagelItemTask, OrderTask, TaskStatus
from .schemas import OrderPhase, StateMachineResult
from .parsers import parse_toasted_deterministic, parse_toasted_choice

if TYPE_CHECKING:
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)


class SpeedMenuBagelHandler:
    """
    Handles speed menu bagel ordering and configuration flow.

    Manages adding speed menu bagel items and toasted preference selection.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        menu_lookup: "MenuLookup | None" = None,
        get_next_question: Callable[[OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the speed menu bagel handler.

        Args:
            model: LLM model to use for parsing.
            menu_lookup: MenuLookup instance for menu item lookups.
            get_next_question: Callback to get the next question in the flow.
        """
        self.model = model
        self.menu_lookup = menu_lookup
        self._get_next_question = get_next_question

    def add_speed_menu_bagel(
        self,
        item_name: str | None,
        quantity: int,
        toasted: bool | None,
        order: OrderTask,
        bagel_choice: str | None = None,
        modifications: list[str] | None = None,
    ) -> StateMachineResult:
        """Add speed menu bagel(s) to the order."""
        if not item_name:
            return StateMachineResult(
                message="Which speed menu item would you like?",
                order=order,
            )

        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item from menu to get price
        menu_item = self.menu_lookup.lookup_menu_item(item_name) if self.menu_lookup else None
        price = menu_item.get("base_price", 10.00) if menu_item else 10.00
        menu_item_id = menu_item.get("id") if menu_item else None

        # Create the requested quantity of items
        for _ in range(quantity):
            item = SpeedMenuBagelItemTask(
                menu_item_name=item_name,
                menu_item_id=menu_item_id,
                toasted=toasted,
                bagel_choice=bagel_choice,
                modifications=modifications or [],
                unit_price=price,
            )
            if toasted is not None:
                # Toasted preference already specified - mark complete
                item.mark_complete()
            else:
                # Need to ask about toasting
                item.mark_in_progress()
            order.items.add_item(item)

        # If toasted was specified, we're done
        if toasted is not None:
            order.clear_pending()
            return self._get_next_question(order)

        # Need to configure toasted preference
        return self.configure_next_incomplete_speed_menu_bagel(order)

    def configure_next_incomplete_speed_menu_bagel(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete speed menu bagel item."""
        # Find incomplete speed menu bagel items
        incomplete_items = [
            item for item in order.items.items
            if isinstance(item, SpeedMenuBagelItemTask) and item.status == TaskStatus.IN_PROGRESS
        ]

        if not incomplete_items:
            order.clear_pending()
            return self._get_next_question(order)

        # Configure items one at a time
        for item in incomplete_items:
            if item.toasted is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = item.id
                order.pending_field = "speed_menu_bagel_toasted"
                return StateMachineResult(
                    message="Would you like that toasted?",
                    order=order,
                )

            # This item is complete
            item.mark_complete()

        # All items configured
        order.clear_pending()
        return self._get_next_question(order)

    def handle_speed_menu_bagel_toasted(
        self,
        user_input: str,
        item: SpeedMenuBagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for speed menu bagel."""
        # Try deterministic parsing first, fall back to LLM
        toasted = parse_toasted_deterministic(user_input)
        if toasted is None:
            parsed = parse_toasted_choice(user_input, model=self.model)
            toasted = parsed.toasted

        if toasted is None:
            return StateMachineResult(
                message="Would you like that toasted?",
                order=order,
            )

        item.toasted = toasted
        item.mark_complete()
        order.clear_pending()

        return self._get_next_question(order)
