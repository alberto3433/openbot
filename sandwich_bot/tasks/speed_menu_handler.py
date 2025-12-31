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
            # Item is complete only if both bagel_choice and toasted are specified
            if bagel_choice is not None and toasted is not None:
                item.mark_complete()
            else:
                # Need to ask about bagel type and/or toasting
                item.mark_in_progress()
            order.items.add_item(item)

        # If both are specified, we're done
        if bagel_choice is not None and toasted is not None:
            order.clear_pending()
            return self._get_next_question(order)

        # Need to configure bagel type and/or toasted preference
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

        # Configure items one at a time - ask bagel type first, then toasted
        for item in incomplete_items:
            # First ask for bagel type if not specified
            if item.bagel_choice is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = item.id
                order.pending_field = "speed_menu_bagel_type"
                return StateMachineResult(
                    message="What type of bagel would you like for that?",
                    order=order,
                )

            # Then ask for toasted if not specified
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

    def handle_speed_menu_bagel_type(
        self,
        user_input: str,
        item: SpeedMenuBagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle bagel type selection for speed menu bagel."""
        from .parsers.deterministic import _extract_bagel_type as parse_bagel_type_response
        from .parsers.deterministic import _extract_spread
        from .models import BagelItemTask

        # Parse the bagel type from user input
        bagel_type = parse_bagel_type_response(user_input)

        # Check if user is adding a modifier to a different item (e.g., "add cream cheese to the bagel")
        # This applies when configuring a speed menu item but user mentions spread for plain bagel
        if bagel_type is None:
            spread, spread_type = _extract_spread(user_input)
            if spread:
                # Find a plain bagel in the order that could take this spread
                plain_bagels = [
                    i for i in order.items.items
                    if isinstance(i, BagelItemTask) and i.spread is None
                ]
                if plain_bagels:
                    # Apply spread to the first plain bagel without a spread
                    plain_bagels[0].spread = spread
                    if spread_type:
                        plain_bagels[0].spread_type = spread_type
                    logger.info("Applied spread '%s' to plain bagel while configuring speed menu item", spread)
                    return StateMachineResult(
                        message=f"Got it, I added {spread} to your bagel. Now, what type of bagel would you like for your {item.menu_item_name}?",
                        order=order,
                    )

        if bagel_type is None:
            return StateMachineResult(
                message="What type of bagel would you like? For example, plain, everything, sesame, or whole wheat.",
                order=order,
            )

        item.bagel_choice = bagel_type

        # Continue to ask for toasted if not set
        if item.toasted is None:
            order.pending_field = "speed_menu_bagel_toasted"
            return StateMachineResult(
                message="Would you like that toasted?",
                order=order,
            )

        # Both fields are set - mark complete
        item.mark_complete()
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
