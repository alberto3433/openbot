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
from .pricing import PricingEngine
from .handler_config import HandlerConfig

if TYPE_CHECKING:
    from .menu_lookup import MenuLookup

logger = logging.getLogger(__name__)


class SpeedMenuBagelHandler:
    """
    Handles speed menu bagel ordering and configuration flow.

    Manages adding speed menu bagel items and toasted preference selection.
    """

    def __init__(self, config: HandlerConfig | None = None, **kwargs):
        """
        Initialize the speed menu bagel handler.

        Args:
            config: HandlerConfig with shared dependencies.
            **kwargs: Legacy parameter support.
        """
        if config:
            self.model = config.model
            self.menu_lookup = config.menu_lookup
            self._get_next_question = config.get_next_question
            self.pricing_engine = config.pricing
        else:
            # Legacy support for direct parameters
            self.model = kwargs.get("model", "gpt-4o-mini")
            self.menu_lookup = kwargs.get("menu_lookup")
            self._get_next_question = kwargs.get("get_next_question")
            self.pricing_engine = kwargs.get("pricing_engine") or kwargs.get("pricing")

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

        # Validate that the menu item exists - fail gracefully if not found
        if not menu_item:
            if self.menu_lookup:
                message, _ = self.menu_lookup.get_not_found_message(item_name)
            else:
                message = f"I'm sorry, I couldn't find '{item_name}' on our menu."
            return StateMachineResult(
                message=message,
                order=order,
            )

        price = menu_item.get("base_price")
        if price is None:
            logger.error("Menu item '%s' has no base_price defined", item_name)
            return StateMachineResult(
                message=f"I'm sorry, I couldn't get the price for '{item_name}'. Please try ordering something else.",
                order=order,
            )

        menu_item_id = menu_item.get("id")

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

    def _item_has_cheese(self, item_name: str) -> bool:
        """Check if a speed menu item contains cheese and needs cheese type selection."""
        name_lower = item_name.lower()
        # Items with cheese: BEC (bacon egg cheese), any "egg and cheese" variant
        cheese_indicators = [
            "bec",
            "egg and cheese",
            "egg & cheese",
            "eggs and cheese",
            "eggs & cheese",
            " cheese",  # Space before to avoid matching "cream cheese"
        ]
        return any(indicator in name_lower for indicator in cheese_indicators)

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

        # Configure items one at a time - ask cheese first (if applicable), then bagel type, then toasted
        for item in incomplete_items:
            # First ask for cheese type if item has cheese and cheese not specified
            if self._item_has_cheese(item.menu_item_name) and item.cheese_choice is None:
                order.phase = OrderPhase.CONFIGURING_ITEM
                order.pending_item_id = item.id
                order.pending_field = "speed_menu_cheese_choice"
                return StateMachineResult(
                    message="What kind of cheese would you like? We have American, cheddar, Swiss, and muenster.",
                    order=order,
                )

            # Then ask for bagel type if not specified
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

    # Paginated bagel options for "what else" responses
    BAGEL_OPTION_PAGES = [
        ["plain", "everything", "sesame", "whole wheat"],
        ["poppy", "onion", "cinnamon raisin", "pumpernickel"],
        ["salt", "garlic", "bialy", "egg", "multigrain"],
        ["asiago", "jalapeno", "blueberry", "gluten free"],
    ]

    # Paginated cheese options for "what else" responses
    CHEESE_OPTION_PAGES = [
        ["American", "cheddar", "Swiss", "muenster"],
        ["provolone", "pepper jack"],
    ]

    def _is_show_more_request(self, user_input: str) -> bool:
        """Check if user is asking to see more options."""
        input_lower = user_input.lower().strip()
        show_more_phrases = [
            "what else",
            "any other",
            "more options",
            "other options",
            "what other",
            "anything else",
            "show more",
            "more bagels",
            "other bagels",
            "different",
        ]
        return any(phrase in input_lower for phrase in show_more_phrases)

    def _get_bagel_options_message(self, page: int) -> str:
        """Get the bagel options message for a given page."""
        if page >= len(self.BAGEL_OPTION_PAGES):
            return "Those are all the bagel types we have. Would you like one of those?"

        options = self.BAGEL_OPTION_PAGES[page]
        options_str = ", ".join(options[:-1]) + f", or {options[-1]}"

        if page == 0:
            return f"What type of bagel would you like? For example, {options_str}."
        else:
            return f"We also have {options_str}."

    def _get_cheese_options_message(self, page: int) -> str:
        """Get the cheese options message for a given page."""
        if page >= len(self.CHEESE_OPTION_PAGES):
            return "Those are all the cheese types we have. Would you like one of those?"

        options = self.CHEESE_OPTION_PAGES[page]
        if len(options) == 1:
            options_str = options[0]
        else:
            options_str = ", ".join(options[:-1]) + f", or {options[-1]}"

        if page == 0:
            return f"What kind of cheese would you like? We have {options_str}."
        else:
            return f"We also have {options_str}."

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

        # Check if user is asking for more bagel options
        if self._is_show_more_request(user_input):
            order.config_options_page += 1
            message = self._get_bagel_options_message(order.config_options_page)
            return StateMachineResult(
                message=message,
                order=order,
            )

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
            # Reset options page when showing first options
            order.config_options_page = 0
            return StateMachineResult(
                message=self._get_bagel_options_message(0),
                order=order,
            )

        item.bagel_choice = bagel_type

        # Calculate and apply bagel type upcharge (e.g., gluten free +$0.80)
        # Bagel type upcharges are stored in the database (bagel_type attribute options)
        if self.pricing_engine:
            upcharge = self.pricing_engine.get_bagel_type_upcharge(bagel_type)
            item.bagel_choice_upcharge = upcharge
            if upcharge > 0:
                # Add upcharge to the item's unit price
                item.unit_price = (item.unit_price or 0) + upcharge
                logger.info("Applied bagel choice upcharge: %s = +$%.2f, new price: $%.2f",
                           bagel_type, upcharge, item.unit_price)
        else:
            # Pricing engine required for bagel type upcharges
            logger.warning(
                "Pricing engine not available for bagel type upcharge lookup. "
                "Bagel choice '%s' will have no upcharge applied.", bagel_type
            )
            item.bagel_choice_upcharge = 0.0

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

    def handle_speed_menu_cheese_choice(
        self,
        user_input: str,
        item: SpeedMenuBagelItemTask,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle cheese type selection for speed menu bagel with cheese."""
        # Check if user is asking for more cheese options
        if self._is_show_more_request(user_input):
            order.config_options_page += 1
            message = self._get_cheese_options_message(order.config_options_page)
            return StateMachineResult(
                message=message,
                order=order,
            )

        input_lower = user_input.lower().strip()

        # Try to extract cheese type from input
        cheese_types = {
            "american": ["american", "america"],
            "cheddar": ["cheddar", "ched"],
            "swiss": ["swiss"],
            "muenster": ["muenster", "munster"],
            "provolone": ["provolone", "prov"],
            "pepper jack": ["pepper jack", "pepperjack", "pepper-jack"],
        }

        selected_cheese = None
        for cheese, patterns in cheese_types.items():
            for pattern in patterns:
                if pattern in input_lower:
                    selected_cheese = cheese
                    break
            if selected_cheese:
                break

        if not selected_cheese:
            # Reset options page when showing first options
            order.config_options_page = 0
            return StateMachineResult(
                message=self._get_cheese_options_message(0),
                order=order,
            )

        item.cheese_choice = selected_cheese
        logger.info("Cheese choice '%s' applied to speed menu item '%s'", selected_cheese, item.menu_item_name)

        # Continue to configure bagel type and toasted
        return self.configure_next_incomplete_speed_menu_bagel(order)
