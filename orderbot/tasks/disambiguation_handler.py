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

from orderbot.constants import MAX_DISAMBIGUATION_OPTIONS
from .models import OrderTask
from .pending_fields import PendingField
from .schemas import StateMachineResult, OrderPhase
from .utils import OptionMatcher
from .utils.disambiguation_utils import format_options_list

logger = logging.getLogger(__name__)

# Shared OptionMatcher instance for disambiguation
_option_matcher = OptionMatcher()


def _get_item_display_name(item) -> str | None:
    """Extract display name from either a cart item or a dict."""
    if isinstance(item, dict):
        name = item.get("name", "")
        return name.lower() if name else None
    if hasattr(item, 'menu_item_name') and item.menu_item_name:
        return item.menu_item_name.lower()
    if hasattr(item, 'get_display_name'):
        return item.get_display_name().lower()
    return None


def _names_match(name1: str, name2: str) -> bool:
    """Check if two item names match (exact or substring)."""
    return name1 == name2 or name2 in name1 or name1 in name2


class DisambiguationHandler:
    """Handles disambiguation when multiple menu items match user input."""

    MAX_OPTIONS = MAX_DISAMBIGUATION_OPTIONS

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
            cart_name = _get_item_display_name(cart_item)
            if not cart_name:
                continue

            # Check if any matching item matches something in the cart
            for match_item in matching_items:
                match_name = _get_item_display_name(match_item)
                if match_name and _names_match(cart_name, match_name):
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
        pending_field: str = PendingField.ITEM_SELECTION,
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

        Uses OptionMatcher.match_from_numbered_list() for unified matching
        with ordinal support.

        Args:
            user_input: User's response to disambiguation question
            order: Current order task with pending_item_options

        Returns:
            The selected item dict if match found, None if no match
        """
        if not order.pending_item_options:
            return None

        options = order.pending_item_options

        # Use unified matcher with ordinal support
        match = _option_matcher.match_from_numbered_list(
            user_input, options, name_key="name", slug_key="slug"
        )

        if match:
            logger.info("DISAMBIGUATION: Selected '%s'", match.get("name"))
            return match

        logger.info("DISAMBIGUATION: Could not match '%s' to any option", user_input[:50])
        return None

    def get_reask_message(self, order: OrderTask, show_prices: bool = False) -> str:
        """Get message to re-ask disambiguation question."""
        options = order.pending_item_options or []
        options_str = format_options_list(
            options[:self.MAX_OPTIONS],
            name_key="name",
            show_prices=show_prices,
            price_key="base_price",
        )
        return f"I didn't catch which one. Please choose:\n{options_str}"

    def clear_disambiguation_state(self, order: OrderTask) -> None:
        """Clear all disambiguation-related state from the order."""
        order.pending_item_options = []
        order.pending_item_quantity = 1
        order.pending_item_modifiers = {}
        order.clear_pending()
        logger.info("DISAMBIGUATION: Cleared pending state")

    def _format_options(self, options: list[dict], show_prices: bool = False) -> str:
        """Format options list for display."""
        return format_options_list(
            options,
            name_key="name",
            show_prices=show_prices,
            price_key="base_price",
        )
