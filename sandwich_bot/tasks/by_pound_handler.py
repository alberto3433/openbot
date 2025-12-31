"""
By-the-Pound Handler for Order State Machine.

This module handles by-the-pound items (cheeses, spreads, cold cuts, fish, salads)
including category browsing, selection, and adding items to orders.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import Callable, TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .schemas import OrderPhase, StateMachineResult, ByPoundOrderItem
from .parsers import parse_by_pound_category
from .parsers.constants import BY_POUND_ITEMS, BY_POUND_CATEGORY_NAMES

if TYPE_CHECKING:
    from .pricing_engine import PricingEngine

logger = logging.getLogger(__name__)


class ByPoundHandler:
    """
    Handles by-the-pound item ordering and category browsing.

    Manages by-the-pound inquiries, category selection, item listing,
    and adding by-the-pound items to orders.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        menu_data: dict | None = None,
        pricing: "PricingEngine | None" = None,
        process_taking_items_input: Callable[[str, OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the by-the-pound handler.

        Args:
            model: LLM model to use for parsing.
            menu_data: Menu data dictionary for category listings.
            pricing: PricingEngine instance for price lookups.
            process_taking_items_input: Callback to process new order input.
        """
        self.model = model
        self._menu_data = menu_data or {}
        self.pricing = pricing
        self._process_taking_items_input = process_taking_items_input

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

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
        return StateMachineResult(
            message="We have cheeses, spreads, cold cuts, fish, and salads as food by the pound. Which are you interested in?",
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
            return StateMachineResult(
                message="Which would you like to hear about? Cheeses, spreads, cold cuts, fish, or salads?",
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
        # For spreads, fetch from menu_data (cheese_types contains cream cheese options)
        if category == "spread" and self._menu_data:
            cheese_types = self._menu_data.get("cheese_types", [])
            # Filter to only cream cheese, spreads, and butter
            items = [
                name for name in cheese_types
                if any(kw in name.lower() for kw in ["cream cheese", "spread", "butter"])
            ]
        else:
            items = BY_POUND_ITEMS.get(category, [])
        category_name = BY_POUND_CATEGORY_NAMES.get(category, category)

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
        if category == "spread":
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
        category_name = {
            "drinks": "drinks",
            "sides": "sides",
            "signature_bagels": "bagels",
            "signature_omelettes": "sandwiches and omelettes",
            "desserts": "desserts",
        }.get(category, "items")

        # Get items from menu_data
        items = []
        if self._menu_data:
            # Try direct category first
            items = self._menu_data.get(category, [])

            # If no items, try items_by_type
            if not items:
                type_map = {
                    "sides": ["side"],
                    "drinks": ["drink", "coffee", "soda", "sized_beverage", "beverage"],
                    "desserts": ["dessert", "pastry", "snack"],  # Combine dessert, pastry, and snack types
                    "signature_bagels": ["speed_menu_bagel"],
                    "signature_omelettes": ["omelette"],
                }
                items_by_type = self._menu_data.get("items_by_type", {})
                for type_slug in type_map.get(category, []):
                    items.extend(items_by_type.get(type_slug, []))

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

    def add_by_pound_items(
        self,
        by_pound_items: list[ByPoundOrderItem],
        order: OrderTask,
    ) -> StateMachineResult:
        """Add by-the-pound items to the order."""
        added_items = []
        for item in by_pound_items:
            # Format the item name with quantity (e.g., "1 lb Muenster Cheese")
            category_name = BY_POUND_CATEGORY_NAMES.get(item.category, "")
            if category_name:
                # Use singular form for category (remove trailing 's' if present)
                category_singular = category_name.rstrip("s") if category_name.endswith("s") else category_name
                item_name = f"{item.quantity} {item.item_name} {category_singular}"
            else:
                item_name = f"{item.quantity} {item.item_name}"

            # Calculate price based on quantity and per-pound price
            if self.pricing:
                pounds = self.pricing.parse_quantity_to_pounds(item.quantity)
                per_pound_price = self.pricing.lookup_by_pound_price(item.item_name)
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
