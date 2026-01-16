"""
By-the-Pound Handler for Order State Machine.

This module handles by-the-pound items (cheeses, spreads, cold cuts, fish, salads)
including category browsing, selection, and adding items to orders.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from sandwich_bot.menu_data_cache import menu_cache

from .models import OrderTask, MenuItemTask
from .schemas import OrderPhase, StateMachineResult, ByPoundOrderItem
from .parsers import parse_by_pound_category
from .parsers.constants import get_by_pound_items, get_by_pound_category_names
from .handler_config import HandlerConfig, BaseHandler

# Slugs for by-pound item types that have special display handling
BY_POUND_SPREAD_SLUG = "spread"

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class ByPoundHandler(BaseHandler):
    """
    Handles by-the-pound item ordering and category browsing.

    Manages by-the-pound inquiries, category selection, item listing,
    and adding by-the-pound items to orders.
    """

    def __init__(
        self,
        config: HandlerConfig | None = None,
        process_taking_items_input: Callable[[str, OrderTask], StateMachineResult] | None = None,
        **kwargs,
    ):
        """
        Initialize the by-the-pound handler.

        Args:
            config: HandlerConfig with shared dependencies.
            process_taking_items_input: Callback to process new order input.
            **kwargs: Legacy parameter support.
        """
        super().__init__(config, **kwargs)

        # Handler-specific callback
        self._process_taking_items_input = process_taking_items_input or kwargs.get("process_taking_items_input")

    def _get_by_pound_categories_message(self) -> str:
        """Build a message listing available by-pound categories from database."""
        category_names = get_by_pound_category_names()
        if not category_names:
            return "food by the pound"

        names = list(category_names.values())
        if len(names) == 1:
            return names[0]
        elif len(names) == 2:
            return f"{names[0]} and {names[1]}"
        else:
            return ", ".join(names[:-1]) + f", and {names[-1]}"

    def handle_by_pound_inquiry(
        self,
        category: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle initial by-the-pound inquiry."""
        if category:
            # User asked about a specific category directly
            return self.list_by_pound_category(category, order)

        # General inquiry - list all categories and ask which they're interested in
        order.phase = OrderPhase.CONFIGURING_ITEM
        order.pending_field = "by_pound_category"
        categories_list = self._get_by_pound_categories_message()
        return StateMachineResult(
            message=f"We have {categories_list} as food by the pound. Which are you interested in?",
            order=order,
        )

    def handle_by_pound_category_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting a by-the-pound category."""
        parsed = parse_by_pound_category(user_input, model=self.model)

        if parsed.unclear:
            categories_list = self._get_by_pound_categories_message()
            return StateMachineResult(
                message=f"Which would you like to hear about? {categories_list.capitalize()}?",
                order=order,
            )

        if not parsed.category:
            # User declined or said never mind
            order.clear_pending()
            # Phase derived by orchestrator
            return StateMachineResult(
                message="No problem! What else can I get for you?",
                order=order,
            )

        # List the items in the selected category
        return self.list_by_pound_category(parsed.category, order)

    def list_by_pound_category(
        self,
        category: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """List items in a specific by-the-pound category."""
        # Get items from database via menu_cache
        by_pound_items = get_by_pound_items()
        items = by_pound_items.get(category, [])
        category_name = get_by_pound_category_names().get(category, category)

        if not items:
            order.clear_pending()
            # Phase derived by orchestrator
            return StateMachineResult(
                message=f"I don't have information on {category_name} right now. What else can I get for you?",
                order=order,
            )

        # Format the items list nicely for voice
        if len(items) <= 3:
            items_list = ", ".join(items)
        else:
            items_list = ", ".join(items[:-1]) + f", and {items[-1]}"

        order.clear_pending()
        # Phase derived by orchestrator

        # For spreads, don't say "food by the pound" since they're also used on bagels
        if category == BY_POUND_SPREAD_SLUG:
            message = f"Our {category_name} include: {items_list}. Would you like any of these, or something else?"
        else:
            message = f"Our {category_name} food by the pound include: {items_list}. Would you like any of these, or something else?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    def handle_category_inquiry_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user response to 'Would you like to hear what X we have?'

        When we say we don't have an item and ask if they want to hear what
        category items we have, this handles the yes/no response.
        """
        lower_input = user_input.lower().strip()
        category = order.pending_config_queue[0] if order.pending_config_queue else None

        # Check for affirmative response
        affirmative = ("yes", "yeah", "yep", "sure", "ok", "okay", "please", "yes please", "yea", "y")
        if lower_input in affirmative:
            order.clear_pending()
            if category:
                # List items in the category
                return self.list_category_items(category, order)
            else:
                return StateMachineResult(
                    message="What would you like to order?",
                    order=order,
                )

        # Check for negative response
        negative = ("no", "nope", "no thanks", "nevermind", "never mind", "n")
        if lower_input in negative:
            order.clear_pending()
            return StateMachineResult(
                message="No problem! What else can I get for you?",
                order=order,
            )

        # Otherwise, treat as a new order attempt - clear pending and process normally
        order.clear_pending()
        if self._process_taking_items_input:
            return self._process_taking_items_input(user_input, order)
        return StateMachineResult(
            message="What would you like to order?",
            order=order,
        )

    def list_category_items(
        self,
        category: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """List items in a menu category (drinks, desserts, sides, etc.)."""
        # Get category display name from database
        category_info = menu_cache.get_category_keyword_mapping(category)
        category_name = category_info.get("display_name", category) if category_info else category

        # Get items from menu_data
        items = []
        if self._menu_data:
            # Try direct category first
            items = self._menu_data.get(category, [])

            # If no items, try items_by_type using data-driven lookup
            if not items and category_info:
                items_by_type = self._menu_data.get("items_by_type", {})
                # Check if this category expands to multiple types
                expands_to = category_info.get("expands_to")
                if expands_to:
                    for type_slug in expands_to:
                        items.extend(items_by_type.get(type_slug, []))
                else:
                    # Single type - use the slug directly
                    items.extend(items_by_type.get(category_info.get("slug"), []))

        if not items:
            return StateMachineResult(
                message=f"I don't have information on {category_name} right now. What would you like to order?",
                order=order,
            )

        # Get item names
        item_names = [item.get("name", "Unknown") for item in items[:10]]

        # Format nicely
        if len(item_names) == 1:
            items_str = item_names[0]
        elif len(item_names) == 2:
            items_str = f"{item_names[0]} and {item_names[1]}"
        else:
            items_str = ", ".join(item_names[:-1]) + f", and {item_names[-1]}"

        return StateMachineResult(
            message=f"For {category_name}, we have: {items_str}. Would you like any of these?",
            order=order,
        )

    def _get_per_pound_price(self, item_name: str) -> float:
        """Get the per-pound price for a by-the-pound item.

        Uses the unified size pricing (menu_item_size_prices) to look up
        the "1 lb" price, or calculates from "1/4 lb" if 1 lb not available.

        Args:
            item_name: Name of the item (e.g., "Whitefish Salad", "Nova Scotia Salmon")

        Returns:
            Price per pound

        Raises:
            ValueError: If price cannot be determined for the item
        """
        if not self.pricing:
            raise ValueError("Pricing engine not available")

        # Try to get "1 lb" price directly
        one_lb_price, _ = self.pricing.lookup_size_price(item_name, "1 lb")
        if one_lb_price is not None:
            return one_lb_price

        # Fall back to "1/4 lb" price × 4
        quarter_lb_price, _ = self.pricing.lookup_size_price(item_name, "1/4 lb")
        if quarter_lb_price is not None:
            return quarter_lb_price * 4

        # Try without size to see if it's a single-price item
        single_price, size_data = self.pricing.lookup_size_price(item_name, None)
        if single_price is not None:
            return single_price

        raise ValueError(
            f"No size price found for by-pound item '{item_name}'. "
            "Ensure item has prices in menu_item_size_prices table."
        )

    def add_by_pound_items(
        self,
        by_pound_items: list[ByPoundOrderItem],
        order: OrderTask,
    ) -> StateMachineResult:
        """Add by-the-pound items to the order."""
        added_items = []
        for item in by_pound_items:
            # Format the item name with quantity (e.g., "half lb Whitefish Salad")
            item_name = f"{item.quantity} {item.item_name}"

            # Calculate price based on quantity and per-pound price
            if self.pricing:
                pounds = self.pricing.parse_quantity_to_pounds(item.quantity)
                per_pound_price = self._get_per_pound_price(item.item_name)
                total_price = round(pounds * per_pound_price, 2)
            else:
                total_price = 0.0

            # Create menu item task with price
            menu_item = MenuItemTask(
                menu_item_name=item_name.strip(),
                menu_item_type="by_pound",
                unit_price=total_price,
            )
            menu_item.mark_in_progress()
            menu_item.mark_complete()  # By-pound items don't need configuration
            order.items.add_item(menu_item)
            added_items.append(item_name.strip())

        # Format confirmation message
        if len(added_items) == 1:
            confirmation = f"Got it, {added_items[0]}."
        elif len(added_items) == 2:
            confirmation = f"Got it, {added_items[0]} and {added_items[1]}."
        else:
            items_list = ", ".join(added_items[:-1]) + f", and {added_items[-1]}"
            confirmation = f"Got it, {items_list}."

        order.clear_pending()
        # Explicitly set to TAKING_ITEMS - we're asking for more items
        order.phase = OrderPhase.TAKING_ITEMS.value
        return StateMachineResult(
            message=f"{confirmation} Anything else?",
            order=order,
        )
