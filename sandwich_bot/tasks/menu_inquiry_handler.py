"""
Menu Inquiry Handler for Order State Machine.

This module handles menu-related inquiries including:
- Menu listings by type (beverages, sandwiches, etc.)
- Price inquiries for specific items
- Item description questions
- Signature/speed menu inquiries
- Soda clarification

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import Callable, TYPE_CHECKING

from .models import OrderTask
from .schemas import StateMachineResult

if TYPE_CHECKING:
    from .pricing_engine import PricingEngine

logger = logging.getLogger(__name__)


class MenuInquiryHandler:
    """
    Handles menu-related inquiries.

    Manages menu listings, price inquiries, item descriptions, and signature menu queries.
    """

    # Item descriptions from Zucker's menu (what's on each item)
    ITEM_DESCRIPTIONS = {
        # Egg Sandwiches
        "the classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar",
        "classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar",
        "the latke bec": "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke",
        "latke bec": "Two Eggs, Applewood Smoked Bacon, Cheddar, and a Breakfast Potato Latke",
        "the leo": "Smoked Nova Scotia Salmon, Eggs, and Sauteed Onions",
        "leo": "Smoked Nova Scotia Salmon, Eggs, and Sauteed Onions",
        "the delancey": "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sauteed Onions, and Swiss",
        "delancey": "Two Eggs, Corned Beef or Pastrami, Breakfast Potato Latke, Sauteed Onions, and Swiss",
        "the mulberry": "Two Eggs, Esposito's Sausage, Green & Red Peppers, and Sauteed Onions",
        "mulberry": "Two Eggs, Esposito's Sausage, Green & Red Peppers, and Sauteed Onions",
        "the truffled egg": "Two Eggs, Swiss, Truffle Cream Cheese, and Sauteed Mushrooms",
        "truffled egg": "Two Eggs, Swiss, Truffle Cream Cheese, and Sauteed Mushrooms",
        "the lexington": "Egg Whites, Swiss, and Spinach",
        "lexington": "Egg Whites, Swiss, and Spinach",
        "the columbus": "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese",
        "columbus": "Three Egg Whites, Turkey Bacon, Avocado, and Swiss Cheese",
        "the health nut": "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "health nut": "Three Egg Whites, Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        # Signature Sandwiches
        "the zucker's traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "zucker's traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "the traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "traditional": "Nova Scotia Salmon, Plain Cream Cheese, Beefsteak Tomatoes, Red Onions, and Capers",
        "the flatiron": "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado",
        "flatiron": "Everything-seeded Salmon with Scallion Cream Cheese and Fresh Avocado",
        "the alton brown": "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko",
        "alton brown": "Smoked Trout with Plain Cream Cheese, Avocado Horseradish, and Tobiko",
        "the old-school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "old-school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "old school tuna": "Fresh Tuna Salad with Lettuce and Beefsteak Tomatoes",
        "the max zucker": "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions",
        "max zucker": "Smoked Whitefish Salad with Beefsteak Tomatoes and Red Onions",
        "the chelsea club": "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions",
        "chelsea club": "Chicken Salad, Cheddar, Smoked Bacon, Beefsteak Tomatoes, Lettuce, and Red Onions",
        "the grand central": "Grilled Chicken, Smoked Bacon, Beefsteak Tomatoes, Romaine, and Dijon Mayo",
        "grand central": "Grilled Chicken, Smoked Bacon, Beefsteak Tomatoes, Romaine, and Dijon Mayo",
        "the tribeca": "Roast Turkey, Havarti, Romaine, Beefsteak Tomatoes, Basil Mayo, and Cracked Black Pepper",
        "tribeca": "Roast Turkey, Havarti, Romaine, Beefsteak Tomatoes, Basil Mayo, and Cracked Black Pepper",
        "the natural": "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce",
        "natural": "Smoked Turkey, Brie, Beefsteak Tomatoes, Lettuce, and Dijon Dill Sauce",
        "the blt": "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo",
        "blt": "Applewood Smoked Bacon, Lettuce, Beefsteak Tomatoes, and Mayo",
        "the reuben": "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing",
        "reuben": "Corned Beef, Pastrami, or Roast Turkey with Sauerkraut, Swiss Cheese, and Russian Dressing",
        # Speed Menu Bagels
        "the classic": "Two Eggs, Applewood Smoked Bacon, and Cheddar on a Bagel",
        "classic": "Two Eggs, Applewood Smoked Bacon, and Cheddar on a Bagel",
        # Omelettes
        "the chipotle egg omelette": "Three Eggs with Pepper Jack Cheese, Jalapenos, and Chipotle Cream Cheese",
        "chipotle egg omelette": "Three Eggs with Pepper Jack Cheese, Jalapenos, and Chipotle Cream Cheese",
        "chipotle omelette": "Three Eggs with Pepper Jack Cheese, Jalapenos, and Chipotle Cream Cheese",
        "the health nut omelette": "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "health nut omelette": "Three Egg Whites with Mushrooms, Spinach, Green & Red Peppers, and Tomatoes",
        "the delancey omelette": "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese",
        "delancey omelette": "Three Eggs with Corned Beef or Pastrami, Onions, and Swiss Cheese",
        # Avocado Toast
        "the avocado toast": "Crushed Avocado with Diced Tomatoes, Lemon Everything Seeds, Salt and Pepper",
        "avocado toast": "Crushed Avocado with Diced Tomatoes, Lemon Everything Seeds, Salt and Pepper",
    }

    def __init__(
        self,
        menu_data: dict | None = None,
        pricing: "PricingEngine | None" = None,
        list_by_pound_category: Callable[[str, OrderTask], StateMachineResult] | None = None,
    ):
        """
        Initialize the menu inquiry handler.

        Args:
            menu_data: Menu data dictionary containing items_by_type, cheese_types, etc.
            pricing: PricingEngine instance for price lookups.
            list_by_pound_category: Callback to list items in a by-the-pound category.
        """
        self._menu_data = menu_data or {}
        self.pricing = pricing
        self._list_by_pound_category = list_by_pound_category

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

    def handle_menu_query(
        self,
        menu_query_type: str | None,
        order: OrderTask,
        show_prices: bool = False,
    ) -> StateMachineResult:
        """Handle inquiry about menu items by type.

        Args:
            menu_query_type: Type of item being queried (e.g., 'beverage', 'bagel', 'sandwich')
            show_prices: If True, include prices in the listing (for price inquiries)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        if not menu_query_type:
            # Generic "what do you have?" - list available types
            available_types = [t.replace("_", " ") for t, items in items_by_type.items() if items]
            if available_types:
                return StateMachineResult(
                    message=f"We have: {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Handle spread/cream cheese queries as by-the-pound category
        if menu_query_type in ("spread", "cream_cheese", "cream cheese"):
            if self._list_by_pound_category:
                return self._list_by_pound_category("spread", order)
            return StateMachineResult(
                message="We have various cream cheeses and spreads. Would you like to hear about them?",
                order=order,
            )

        # Map common query types to actual item_type slugs
        # - "soda", "water", "juice" -> "beverage" (cold-only drinks)
        # - "coffee", "tea", "latte" -> "sized_beverage" (hot/iced drinks)
        # - "beverage", "drink" -> combine both types
        type_aliases = {
            "coffee": "sized_beverage",
            "tea": "sized_beverage",
            "latte": "sized_beverage",
            "espresso": "sized_beverage",
            "soda": "beverage",
            "water": "beverage",
            "juice": "beverage",
        }

        # Handle "beverage" or "drink" queries by combining both types
        if menu_query_type in ("beverage", "drink"):
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            items = sized_items + cold_items
            if items:
                # Conditionally show prices based on show_prices flag
                if show_prices:
                    item_list = [
                        f"{item.get('name', 'Unknown')} (${item.get('price') or item.get('base_price') or 0:.2f})"
                        for item in items[:15]
                    ]
                else:
                    item_list = [item.get("name", "Unknown") for item in items[:15]]
                if len(items) > 15:
                    item_list.append(f"...and {len(items) - 15} more")
                if len(item_list) == 1:
                    items_str = item_list[0]
                elif len(item_list) == 2:
                    items_str = f"{item_list[0]} and {item_list[1]}"
                else:
                    items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"
                return StateMachineResult(
                    message=f"Our beverages include: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any beverages on the menu right now. Is there anything else I can help you with?",
                order=order,
            )

        # Handle "sandwich" specially - too broad, need to ask what kind
        if menu_query_type == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle "dessert", "pastry", "sweets", etc. by combining dessert and pastry types
        dessert_queries = (
            "dessert", "desserts", "pastry", "pastries", "sweet", "sweets",
            "sweet stuff", "bakery", "baked goods", "treats", "treat",
        )
        if menu_query_type in dessert_queries:
            # Combine dessert, pastry, and snack types
            dessert_items = items_by_type.get("dessert", [])
            pastry_items = items_by_type.get("pastry", [])
            snack_items = items_by_type.get("snack", [])
            items = dessert_items + pastry_items + snack_items
            if items:
                if show_prices:
                    item_list = [
                        f"{item.get('name', 'Unknown')} (${item.get('price') or item.get('base_price') or 0:.2f})"
                        for item in items[:15]
                    ]
                else:
                    item_list = [item.get("name", "Unknown") for item in items[:15]]
                if len(items) > 15:
                    item_list.append(f"...and {len(items) - 15} more")
                if len(item_list) == 1:
                    items_str = item_list[0]
                elif len(item_list) == 2:
                    items_str = f"{item_list[0]} and {item_list[1]}"
                else:
                    items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"
                return StateMachineResult(
                    message=f"For desserts and pastries, we have: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any desserts on the menu right now. What else can I get for you?",
                order=order,
            )

        lookup_type = type_aliases.get(menu_query_type, menu_query_type)

        # Look up items for the specific type
        items = items_by_type.get(lookup_type, [])

        if not items:
            # Try to suggest what we do have
            available_types = [t.replace("_", " ") for t, i in items_by_type.items() if i]
            type_display = menu_query_type.replace("_", " ")
            if available_types:
                return StateMachineResult(
                    message=f"I don't have any {type_display}s on the menu. We do have: {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display}s on the menu. What else can I help you with?",
                order=order,
            )

        # Format the items list (conditionally show prices)
        type_name = menu_query_type.replace("_", " ")
        # Proper pluralization
        if type_name.endswith("ch") or type_name.endswith("s"):
            type_display = type_name + "es"
        else:
            type_display = type_name + "s"

        # Conditionally show prices based on show_prices flag
        if show_prices:
            item_list = []
            for item in items[:15]:
                name = item.get('name', 'Unknown')
                # Bagels use _lookup_bagel_price since they don't store price in items_by_type
                if lookup_type == "bagel":
                    # Extract bagel type from name (e.g., "Plain Bagel" -> "plain")
                    bagel_type = name.lower().replace(" bagel", "").strip()
                    price = self.pricing.lookup_bagel_price(bagel_type) if self.pricing else 0
                else:
                    price = item.get('price') or item.get('base_price') or 0
                item_list.append(f"{name} (${price:.2f})")
        else:
            item_list = [item.get("name", "Unknown") for item in items[:15]]

        if len(items) > 15:
            item_list.append(f"...and {len(items) - 15} more")

        # Format the response
        if len(item_list) == 1:
            items_str = item_list[0]
        elif len(item_list) == 2:
            items_str = f"{item_list[0]} and {item_list[1]}"
        else:
            items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            order=order,
        )

    def handle_soda_clarification(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle when user orders a generic 'soda' without specifying type.

        Asks what kind of soda they want, listing available options.
        """
        # Get beverages from menu data
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        beverages = items_by_type.get("beverage", [])

        if beverages:
            # Get just the names of a few common sodas
            soda_names = [item.get("name", "") for item in beverages[:6]]
            # Filter out empty names and format nicely
            soda_names = [name for name in soda_names if name]
            if len(soda_names) > 3:
                soda_list = ", ".join(soda_names[:3]) + ", and others"
            elif len(soda_names) > 1:
                soda_list = ", ".join(soda_names[:-1]) + f", and {soda_names[-1]}"
            else:
                soda_list = soda_names[0] if soda_names else "Coke, Diet Coke, Sprite"

            return StateMachineResult(
                message=f"What kind? We have {soda_list}.",
                order=order,
            )

        # Fallback if no beverages in menu data
        return StateMachineResult(
            message="What kind? We have Coke, Diet Coke, Sprite, and others.",
            order=order,
        )

    def handle_price_inquiry(
        self,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle price inquiry for a specific item.

        Args:
            item_query: The item the user is asking about (e.g., 'sesame bagel', 'large latte')

        Returns:
            StateMachineResult with the price information
        """
        if not self.menu_data:
            return StateMachineResult(
                message="I'm sorry, I don't have pricing information available. What can I get for you?",
                order=order,
            )

        items_by_type = self.menu_data.get("items_by_type", {})
        query_lower = item_query.lower().strip()

        # Strip leading "a " or "an " from the query
        query_lower = re.sub(r"^(?:a|an)\s+", "", query_lower)

        # Check if this is a generic category inquiry (e.g., "a bagel", "coffee", "sandwich")
        # Map generic terms to their item_type and display name
        generic_category_map = {
            "bagel": ("bagel", "bagels"),
            "coffee": ("sized_beverage", "coffees"),
            "latte": ("sized_beverage", "lattes"),
            "cappuccino": ("sized_beverage", "cappuccinos"),
            "espresso": ("sized_beverage", "espressos"),
            "tea": ("sized_beverage", "teas"),
            "drink": ("beverage", "drinks"),
            "beverage": ("beverage", "beverages"),
            "soda": ("beverage", "sodas"),
            "omelette": ("omelette", "omelettes"),
            "side": ("side", "sides"),
        }

        # Special handling for "sandwich" - too broad, need to ask what kind
        if query_lower == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle specific sandwich types
        sandwich_type_map = {
            "egg sandwich": ("egg_sandwich", "egg sandwiches"),
            "fish sandwich": ("fish_sandwich", "fish sandwiches"),
            "cream cheese sandwich": ("spread_sandwich", "cream cheese sandwiches"),
            "spread sandwich": ("spread_sandwich", "spread sandwiches"),
            "salad sandwich": ("salad_sandwich", "salad sandwiches"),
            "deli sandwich": ("deli_sandwich", "deli sandwiches"),
            "signature sandwich": ("signature_sandwich", "signature sandwiches"),
        }

        if query_lower in sandwich_type_map and self.pricing:
            item_type, display_name = sandwich_type_map[query_lower]
            min_price = self.pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        if query_lower in generic_category_map and self.pricing:
            item_type, display_name = generic_category_map[query_lower]
            min_price = self.pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        # Search all menu items for a match
        best_match = None
        best_match_score = 0

        for item_type, items in items_by_type.items():
            for item in items:
                item_name = item.get("name", "").lower()
                item_price = item.get("price", 0)

                # Exact match
                if item_name == query_lower:
                    best_match = item
                    best_match_score = 100
                    break

                # Check if query is contained in item name
                if query_lower in item_name:
                    score = len(query_lower) / len(item_name) * 80
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

                # Check if item name is contained in query
                if item_name in query_lower:
                    score = len(item_name) / len(query_lower) * 70
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

            if best_match_score == 100:
                break

        # Check bagels specifically (they may not be in items_by_type with prices)
        bagel_items = items_by_type.get("bagel", [])
        is_bagel_query = "bagel" in query_lower
        if is_bagel_query and not best_match:
            # Try to find a matching bagel
            for bagel in bagel_items:
                bagel_name = bagel.get("name", "").lower()
                if query_lower in bagel_name or bagel_name in query_lower:
                    best_match = bagel
                    best_match_score = 75
                    break

            # If they asked about a specific bagel type but we didn't find it,
            # give the general bagel price if available
            if not best_match and bagel_items:
                # Use the first bagel price as the general price
                best_match = bagel_items[0]
                best_match_score = 50

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
            # Bagels use _lookup_bagel_price since they don't store price in items_by_type
            if is_bagel_query or "bagel" in name.lower():
                bagel_type = name.lower().replace(" bagel", "").strip()
                price = self.pricing.lookup_bagel_price(bagel_type) if self.pricing else 0
            else:
                price = best_match.get("price") or best_match.get("base_price") or 0
            return StateMachineResult(
                message=f"{name} is ${price:.2f}. Would you like one?",
                order=order,
            )

        # No match found - give helpful response
        return StateMachineResult(
            message=f"I'm not sure about the price for '{item_query}'. Is there something else I can help you with?",
            order=order,
        )

    def handle_item_description_inquiry(
        self,
        item_query: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle item description questions like 'what's on the health nut?'

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the description.

        Args:
            item_query: The item name the user is asking about
            order: Current order state (unchanged)
        """
        if not item_query:
            return StateMachineResult(
                message="Which item would you like to know about?",
                order=order,
            )

        item_query_lower = item_query.lower().strip()

        # Try to find an exact match or close match in descriptions
        description = self.ITEM_DESCRIPTIONS.get(item_query_lower)

        if not description:
            # Try partial matching - look for item_query in keys
            for key, desc in self.ITEM_DESCRIPTIONS.items():
                if item_query_lower in key or key in item_query_lower:
                    description = desc
                    break

        if not description:
            # Also search menu_data for item names
            if self.menu_data:
                items_by_type = self.menu_data.get("items_by_type", {})
                for item_type, items in items_by_type.items():
                    for item in items:
                        item_name = item.get("name", "").lower()
                        if item_query_lower in item_name or item_name in item_query_lower:
                            # Found the item in menu but no description - check ITEM_DESCRIPTIONS again
                            item_key = item.get("name", "").lower()
                            description = self.ITEM_DESCRIPTIONS.get(item_key)
                            if description:
                                break
                    if description:
                        break

        if description:
            # Format with proper capitalization
            formatted_name = item_query.title()
            message = f"{formatted_name} has {description}. Would you like to order one?"
        else:
            # Item not found - offer to help find it
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                "Would you like me to tell you what sandwiches or egg dishes we have?"
            )

        return StateMachineResult(message=message, order=order)

    def handle_signature_menu_inquiry(
        self,
        menu_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about signature/speed menu items.

        Args:
            menu_type: Specific type like 'signature_sandwich' or 'speed_menu_bagel',
                      or None for all signature items
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # If a specific type is requested, look it up directly
        if menu_type:
            items = items_by_type.get(menu_type, [])
            # Get the display name from the type slug (proper pluralization)
            type_name = menu_type.replace("_", " ")
            if type_name.endswith("ch") or type_name.endswith("s"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # No specific type - combine signature_sandwich and speed_menu_bagel items
            items = []
            items.extend(items_by_type.get("signature_sandwich", []))
            items.extend(items_by_type.get("speed_menu_bagel", []))
            type_display_name = "signature menu options"

        if not items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                order=order,
            )

        # Build a nice list of items (without prices - prices only shown when specifically asked)
        item_descriptions = [item.get("name", "Unknown") for item in items]

        # Format the response
        if len(item_descriptions) == 1:
            items_list = item_descriptions[0]
        elif len(item_descriptions) == 2:
            items_list = f"{item_descriptions[0]} and {item_descriptions[1]}"
        else:
            items_list = ", ".join(item_descriptions[:-1]) + f", and {item_descriptions[-1]}"

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )
