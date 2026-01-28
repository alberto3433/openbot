"""
Generic Disambiguation Handler for Order State Machine.

This module handles disambiguation when multiple menu items match a user's request.
It provides a unified approach for all item types (bagels, beverages, menu items, etc.)
instead of having separate disambiguation logic scattered across handlers.

The flow is:
1. start_disambiguation() - Called when multiple items match. Stores state and returns options message.
2. resolve_disambiguation() - Called when user responds. Matches selection and returns selected item.

This replaces the ad-hoc disambiguation code in:
- item_adder_handler.py::add_menu_item (lines 230-400)
- item_adder_handler.py::_add_coffee (lines 1100-1190)
"""

import logging
from typing import Any

from .models import OrderTask
from .schemas import StateMachineResult, OrderPhase
from .parsers.constants import _SELECTION_PATTERNS

logger = logging.getLogger(__name__)


class DisambiguationHandler:
    """Handles disambiguation when multiple menu items match user input."""

    # Number/ordinal patterns for selection - imported from constants to avoid duplication
    NUMBER_PATTERNS = _SELECTION_PATTERNS

    MAX_OPTIONS = 6

    def check_exact_match(
        self,
        item_name: str,
        matching_items: list[dict],
    ) -> dict | None:
        """Check if user input exactly matches one of the options.

        Args:
            item_name: The item name the user requested
            matching_items: List of matching menu items

        Returns:
            The matching item dict if exact match found, None otherwise
        """
        item_lower = item_name.lower()
        for item in matching_items:
            if item.get("name", "").lower() == item_lower:
                logger.info(
                    "DISAMBIGUATION: Exact match found for '%s'",
                    item_name
                )
                return item
        return None

    def check_cart_match(
        self,
        matching_items: list[dict],
        order: OrderTask,
    ) -> dict | None:
        """Check if user already has a matching item in their cart.

        If user already has one of the matching items in their cart,
        assume they want another of the same type.

        Args:
            matching_items: List of matching menu items
            order: Current order task

        Returns:
            The matching item dict if cart match found, None otherwise
        """
        for cart_item in order.items.items:
            # Get cart item name - all items use menu_item_name
            cart_name = None
            if hasattr(cart_item, 'menu_item_name') and cart_item.menu_item_name:
                cart_name = cart_item.menu_item_name.lower()
            elif hasattr(cart_item, 'get_display_name'):
                cart_name = cart_item.get_display_name().lower()

            if not cart_name:
                continue

            # Check if any matching item matches something in the cart
            for match_item in matching_items:
                match_name = match_item.get("name", "").lower()
                if cart_name == match_name or match_name in cart_name or cart_name in match_name:
                    logger.info(
                        "DISAMBIGUATION: User already has '%s' in cart, using same item",
                        match_item.get("name")
                    )
                    return match_item

        return None

    def start_disambiguation(
        self,
        item_name: str,
        matching_items: list[dict],
        order: OrderTask,
        quantity: int = 1,
        pending_field: str = "item_selection",
        modifiers: dict[str, Any] | None = None,
        show_prices: bool = False,
    ) -> StateMachineResult:
        """Start disambiguation flow when multiple items match.

        Stores the pending state and returns a message asking user to choose.

        Args:
            item_name: The item name the user requested
            matching_items: List of matching menu items (must have >1 items)
            order: Current order task
            quantity: Number of items requested
            pending_field: The pending_field value to set (default: "item_selection")
            modifiers: Optional dict of modifiers to preserve during disambiguation (for beverages)
            show_prices: Whether to show prices in the options list

        Returns:
            StateMachineResult with disambiguation message
        """
        if len(matching_items) <= 1:
            raise ValueError("start_disambiguation requires >1 matching items")

        # Store pending state
        order.pending_item_options = matching_items[:self.MAX_OPTIONS]
        order.pending_item_quantity = quantity
        order.pending_field = pending_field
        order.set_phase(OrderPhase.CONFIGURING_ITEM)

        # Store modifiers if provided (for beverages)
        if modifiers:
            order.pending_item_modifiers = modifiers
            logger.info(
                "DISAMBIGUATION: Stored modifiers for %s: %s",
                pending_field,
                {k: v for k, v in modifiers.items() if v is not None}
            )

        # Build options list
        options_str = self._format_options(matching_items[:self.MAX_OPTIONS], show_prices)

        logger.info(
            "DISAMBIGUATION: Multiple matches for '%s' (%d items), asking user to choose",
            item_name,
            len(matching_items)
        )

        return StateMachineResult(
            message=f"We have a few options for {item_name}:\n{options_str}\nWhich would you like?",
            order=order,
        )

    def resolve_disambiguation(
        self,
        user_input: str,
        order: OrderTask,
    ) -> dict | None:
        """Resolve user's disambiguation selection.

        Tries to match user input to one of the pending options.

        Args:
            user_input: User's response to disambiguation question
            order: Current order task with pending_item_options

        Returns:
            The selected item dict if match found, None if no match
        """
        if not order.pending_item_options:
            return None

        user_lower = user_input.lower().strip()
        options = order.pending_item_options

        # Reject negative numbers or other invalid input
        if user_lower.startswith('-') or user_lower.startswith('−'):
            return None

        # Try to match by number/ordinal
        for key, idx in self.NUMBER_PATTERNS:
            if key in user_lower:
                if idx < len(options):
                    logger.info(
                        "DISAMBIGUATION: User selected option %d ('%s') by number",
                        idx + 1,
                        options[idx].get("name")
                    )
                    return options[idx]
                else:
                    # Out of range - return None to trigger re-ask
                    logger.info(
                        "DISAMBIGUATION: User selected %s but only %d options available",
                        key,
                        len(options)
                    )
                    return None

        # Try to match by name
        for option in options:
            option_name = option.get("name", "").lower()
            # Check if option name is in user input or vice versa
            # Require minimum length to avoid false matches
            if len(user_lower) >= 3 and (option_name in user_lower or user_lower in option_name):
                logger.info(
                    "DISAMBIGUATION: User selected '%s' by name match",
                    option.get("name")
                )
                return option

            # Also try matching individual words
            for word in user_lower.split():
                if len(word) >= 3 and word in option_name:
                    logger.info(
                        "DISAMBIGUATION: User selected '%s' by word match '%s'",
                        option.get("name"),
                        word
                    )
                    return option

        logger.info("DISAMBIGUATION: Could not match user input '%s' to any option", user_input[:50])
        return None

    def get_reask_message(self, order: OrderTask, show_prices: bool = False) -> str:
        """Get message to re-ask disambiguation question.

        Args:
            order: Current order task with pending_item_options
            show_prices: Whether to show prices in the options list

        Returns:
            Message string asking user to choose again
        """
        options = order.pending_item_options or []
        options_str = self._format_options(options[:self.MAX_OPTIONS], show_prices)
        return f"I didn't catch which one. Please choose:\n{options_str}"

    def clear_disambiguation_state(self, order: OrderTask) -> None:
        """Clear all disambiguation-related state from the order.

        Args:
            order: Current order task
        """
        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.pending_item_modifiers = {}
        order.clear_pending()
        logger.info("DISAMBIGUATION: Cleared pending state")

    def _format_options(self, options: list[dict], show_prices: bool = False) -> str:
        """Format options list for display.

        Args:
            options: List of menu item dicts
            show_prices: Whether to include prices

        Returns:
            Formatted string with numbered options
        """
        option_list = []
        for i, item in enumerate(options, 1):
            name = item.get("name", "Unknown")
            if show_prices:
                price = item.get("base_price", 0)
                if price > 0:
                    option_list.append(f"{i}. {name} (${price:.2f})")
                else:
                    option_list.append(f"{i}. {name}")
            else:
                option_list.append(f"{i}. {name}")
        return "\n".join(option_list)
