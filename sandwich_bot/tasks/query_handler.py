"""
Query Handler for Informational Inquiries.

This module handles all informational queries about the menu, prices,
store information, recommendations, and item descriptions.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from .schemas import OrderPhase
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_by_pound_items,
    get_by_pound_category_names,
    get_item_type_display_name,
)

# Note: NYC_NEIGHBORHOOD_ZIPS was moved to the database (neighborhood_zip_codes table)
# Neighborhood data is now loaded via menu_data["neighborhood_zip_codes"]

if TYPE_CHECKING:
    from .models import OrderTask
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class StateMachineResult:
    """Result from state machine processing - imported here to avoid circular imports."""
    def __init__(self, message: str, order: "OrderTask"):
        self.message = message
        self.order = order


class QueryHandler:
    """
    Handles informational queries about menu, prices, store info, and recommendations.

    This class is instantiated with the current context and provides methods
    to handle various types of informational inquiries.
    """

    # Note: ITEM_DESCRIPTIONS has been moved to the database (menu_items.description column)
    # Item descriptions are now loaded via menu_data["item_descriptions"]

    def __init__(
        self,
        menu_data: dict | None,
        store_info: dict | None,
        pricing: "PricingEngine",
    ):
        """
        Initialize the query handler.

        Args:
            menu_data: Menu data dictionary.
            store_info: Store information dictionary.
            pricing: PricingEngine instance for price lookups.
        """
        self._menu_data = menu_data or {}
        self._store_info = store_info or {}
        self._pricing = pricing

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict | None):
        self._menu_data = value or {}

    @property
    def store_info(self) -> dict:
        return self._store_info

    @store_info.setter
    def store_info(self, value: dict | None):
        self._store_info = value or {}

    # =========================================================================
    # Store Info Handlers
    # =========================================================================

    def handle_store_hours_inquiry(self, order: "OrderTask") -> StateMachineResult:
        """Handle inquiry about store hours."""
        hours = self._store_info.get("hours")
        store_name = self._store_info.get("name")

        if hours:
            if store_name:
                message = f"Our hours at {store_name} are {hours}. Can I help you with an order?"
            else:
                message = f"Our hours are {hours}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        if store_name:
            return StateMachineResult(
                message=f"I don't have the hours for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        return StateMachineResult(
            message="Which location would you like the hours for?",
            order=order,
        )

    def handle_store_location_inquiry(self, order: "OrderTask") -> StateMachineResult:
        """Handle inquiry about store location/address."""
        address = self._store_info.get("address")
        city = self._store_info.get("city")
        state = self._store_info.get("state")
        zip_code = self._store_info.get("zip_code")
        store_name = self._store_info.get("name")

        if address:
            address_parts = [address]
            if city:
                city_state_zip = city
                if state:
                    city_state_zip += f", {state}"
                if zip_code:
                    city_state_zip += f" {zip_code}"
                address_parts.append(city_state_zip)
            full_address = ", ".join(address_parts)

            if store_name:
                message = f"{store_name} is located at {full_address}. Can I help you with an order?"
            else:
                message = f"We're located at {full_address}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        if store_name:
            return StateMachineResult(
                message=f"I don't have the address for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        return StateMachineResult(
            message="Which location would you like the address for?",
            order=order,
        )

    def handle_delivery_zone_inquiry(
        self, query: str | None, order: "OrderTask"
    ) -> StateMachineResult:
        """Handle inquiry about whether we deliver to a specific location."""
        all_stores = self._store_info.get("all_stores", [])

        if not query:
            return StateMachineResult(
                message="What area would you like to check for delivery? You can give me a zip code or neighborhood.",
                order=order,
            )

        query_clean = query.lower().strip()

        # Check if it's a zip code (5 digits)
        zip_match = re.match(r'^(\d{5})$', query_clean)
        if zip_match:
            zip_code = zip_match.group(1)
            return self._check_delivery_for_zip(zip_code, all_stores, order)

        # Check if it's a known neighborhood (from database)
        neighborhood_zip_codes = self._menu_data.get("neighborhood_zip_codes", {})
        neighborhood_key = query_clean.replace("'", "'").strip()
        if neighborhood_key in neighborhood_zip_codes:
            zip_codes = neighborhood_zip_codes[neighborhood_key]
            return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Try fuzzy matching for neighborhoods
        for key in neighborhood_zip_codes:
            if key in query_clean or query_clean in key:
                zip_codes = neighborhood_zip_codes[key]
                return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Check if it looks like an address
        if re.search(r'\d+\s+\w+', query):
            from ..address_service import geocode_to_zip
            zip_code = geocode_to_zip(query)
            if zip_code:
                logger.info("Geocoded '%s' to zip code: %s", query, zip_code)
                return self._check_delivery_for_zip(zip_code, all_stores, order, original_query=query)

        return StateMachineResult(
            message=f"I'm not sure about {query}. Could you give me a zip code or street address so I can check our delivery area?",
            order=order,
        )

    def _check_delivery_for_zip(
        self, zip_code: str, all_stores: list, order: "OrderTask", original_query: str | None = None
    ) -> StateMachineResult:
        """Check which stores deliver to a specific zip code."""
        delivering_stores = []
        location_display = original_query or zip_code

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if zip_code in delivery_zips:
                delivering_stores.append(store)

        if delivering_stores:
            if len(delivering_stores) == 1:
                store = delivering_stores[0]
                store_name = store.get("name", "our store")
                message = f"Yes! {store_name} delivers to {location_display}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                if len(store_names) == 2:
                    stores_str = f"{store_names[0]} and {store_names[1]}"
                else:
                    stores_str = ", ".join(store_names[:-1]) + f", and {store_names[-1]}"
                message = f"Yes! We can deliver to {location_display} from {stores_str}. Would you like to place a delivery order?"
            return StateMachineResult(message=message, order=order)

        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {location_display}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    def _check_delivery_for_neighborhood(
        self, neighborhood: str, zip_codes: list, all_stores: list, order: "OrderTask"
    ) -> StateMachineResult:
        """Check which stores deliver to any of the neighborhood's zip codes."""
        delivering_stores = []
        covered_zips = []

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            matching_zips = [z for z in zip_codes if z in delivery_zips]
            if matching_zips:
                if store not in delivering_stores:
                    delivering_stores.append(store)
                covered_zips.extend(matching_zips)

        if delivering_stores:
            if len(delivering_stores) == 1:
                store = delivering_stores[0]
                store_name = store.get("name", "our store")
                message = f"Yes! {store_name} delivers to {neighborhood}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                if len(store_names) == 2:
                    stores_str = f"{store_names[0]} and {store_names[1]}"
                else:
                    stores_str = ", ".join(store_names[:-1]) + f", and {store_names[-1]}"
                message = f"Yes! We can deliver to {neighborhood} from {stores_str}. Would you like to place a delivery order?"
            return StateMachineResult(message=message, order=order)

        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {neighborhood}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    # =========================================================================
    # Menu Query Handlers
    # =========================================================================

    def handle_menu_query(
        self,
        menu_query_type: str | None,
        order: "OrderTask",
        show_prices: bool = False,
    ) -> StateMachineResult:
        """Handle inquiry about menu items by type."""
        items_by_type = self._menu_data.get("items_by_type", {}) if self._menu_data else {}

        if not menu_query_type:
            display_names = self._menu_data.get("item_type_display_names", {}) if self._menu_data else {}
            available_types = [get_item_type_display_name(t, display_names) for t, items in items_by_type.items() if items]
            if available_types:
                return StateMachineResult(
                    message=f"We have: {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Handle spread/cream cheese queries
        if menu_query_type in ("spread", "cream_cheese", "cream cheese"):
            return self.list_by_pound_category("spread", order)

        # TRUE category terms - these return the full category, not filtered results
        # When a user asks for "coffee", they want ALL sized beverages (lattes, cappuccinos, etc.)
        # Note: "tea", "latte", "espresso" are NOT category terms - they use partial matching
        # to filter items containing that keyword in the name
        category_terms = {
            "coffee": "sized_beverage",
            "soda": "beverage",
        }

        # HYBRID APPROACH: For terms not in category_terms, try partial string matching
        # This handles "juice", "snapple", "mocha", "chai", "iced", etc.
        if menu_query_type.lower() not in category_terms:
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            all_drinks = sized_items + cold_items
            search_term = menu_query_type.lower()
            items = [
                item for item in all_drinks
                if search_term in item.get("name", "").lower()
            ]
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
                items_str = self._format_item_list(item_list)
                # Pluralize the search term
                type_display = menu_query_type + "s" if not menu_query_type.endswith("s") else menu_query_type
                return StateMachineResult(
                    message=f"Our {type_display} include: {items_str}. Would you like any of these?",
                    order=order,
                )
            # No matches found - fall through to general handling

        # Handle "beverage" or "drink" queries
        if menu_query_type in ("beverage", "drink"):
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            items = sized_items + cold_items
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
                items_str = self._format_item_list(item_list)
                return StateMachineResult(
                    message=f"Our beverages include: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any beverages on the menu right now. Is there anything else I can help you with?",
                order=order,
            )

        # Handle "sandwich" specially
        if menu_query_type == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle dessert queries
        dessert_queries = (
            "dessert", "desserts", "pastry", "pastries", "sweet", "sweets",
            "sweet stuff", "bakery", "baked goods", "treats", "treat",
        )
        if menu_query_type in dessert_queries:
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
                items_str = self._format_item_list(item_list)
                return StateMachineResult(
                    message=f"For desserts and pastries, we have: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any desserts on the menu right now. What else can I get for you?",
                order=order,
            )

        lookup_type = category_terms.get(menu_query_type, menu_query_type)
        items = items_by_type.get(lookup_type, [])

        if not items:
            display_names = self._menu_data.get("item_type_display_names", {}) if self._menu_data else {}
            available_types = [get_item_type_display_name(t, display_names) for t, i in items_by_type.items() if i]
            type_display = get_item_type_display_name(menu_query_type, display_names)
            if available_types:
                return StateMachineResult(
                    message=f"We have {', '.join(available_types)}. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display} on the menu. What else can I help you with?",
                order=order,
            )

        # Format the items list
        type_name = menu_query_type.replace("_", " ")
        if type_name.endswith("ch") or type_name.endswith("s"):
            type_display = type_name + "es"
        else:
            type_display = type_name + "s"

        if show_prices:
            item_list = []
            for item in items[:15]:
                name = item.get('name', 'Unknown')
                if lookup_type == "bagel":
                    bagel_type = name.lower().replace(" bagel", "").strip()
                    price = self._pricing.lookup_bagel_price(bagel_type)
                else:
                    price = item.get('price') or item.get('base_price') or 0
                item_list.append(f"{name} (${price:.2f})")
        else:
            item_list = [item.get("name", "Unknown") for item in items[:15]]

        if len(items) > 15:
            item_list.append(f"...and {len(items) - 15} more")

        items_str = self._format_item_list(item_list)

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            order=order,
        )

    def handle_soda_clarification(self, order: "OrderTask") -> StateMachineResult:
        """Handle when user orders a generic 'soda' without specifying type."""
        items_by_type = self._menu_data.get("items_by_type", {}) if self._menu_data else {}
        beverages = items_by_type.get("beverage", [])

        if beverages:
            soda_names = [item.get("name", "") for item in beverages[:6]]
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

        return StateMachineResult(
            message="What kind? We have Coke, Diet Coke, Sprite, and others.",
            order=order,
        )

    # =========================================================================
    # Price Inquiry Handlers
    # =========================================================================

    def handle_price_inquiry(
        self,
        item_query: str,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle price inquiry for a specific item."""
        if not self._menu_data:
            return StateMachineResult(
                message="I'm sorry, I don't have pricing information available. What can I get for you?",
                order=order,
            )

        items_by_type = self._menu_data.get("items_by_type", {})
        query_lower = item_query.lower().strip()
        query_lower = re.sub(r"^(?:a|an)\s+", "", query_lower)

        # Generic category map
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

        if query_lower == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        sandwich_type_map = {
            "egg sandwich": ("egg_sandwich", "egg sandwiches"),
            "fish sandwich": ("fish_sandwich", "fish sandwiches"),
            "cream cheese sandwich": ("spread_sandwich", "cream cheese sandwiches"),
            "spread sandwich": ("spread_sandwich", "spread sandwiches"),
            "salad sandwich": ("salad_sandwich", "salad sandwiches"),
            "deli sandwich": ("deli_sandwich", "deli sandwiches"),
            "signature sandwich": ("signature_items", "signature sandwiches"),
        }

        if query_lower in sandwich_type_map:
            item_type, display_name = sandwich_type_map[query_lower]
            min_price = self._pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        if query_lower in generic_category_map:
            item_type, display_name = generic_category_map[query_lower]
            min_price = self._pricing.get_min_price_for_category(item_type)
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

                if item_name == query_lower:
                    best_match = item
                    best_match_score = 100
                    break

                if query_lower in item_name:
                    score = len(query_lower) / len(item_name) * 80
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

                if item_name in query_lower:
                    score = len(item_name) / len(query_lower) * 70
                    if score > best_match_score:
                        best_match = item
                        best_match_score = score

            if best_match_score == 100:
                break

        # Check bagels specifically
        bagel_items = items_by_type.get("bagel", [])
        is_bagel_query = "bagel" in query_lower
        if is_bagel_query and not best_match:
            for bagel in bagel_items:
                bagel_name = bagel.get("name", "").lower()
                if query_lower in bagel_name or bagel_name in query_lower:
                    best_match = bagel
                    best_match_score = 75
                    break

            if not best_match and bagel_items:
                best_match = bagel_items[0]
                best_match_score = 50

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
            if is_bagel_query or "bagel" in name.lower():
                bagel_type = name.lower().replace(" bagel", "").strip()
                price = self._pricing.lookup_bagel_price(bagel_type)
            else:
                price = best_match.get("price") or best_match.get("base_price") or 0
            return StateMachineResult(
                message=f"{name} is ${price:.2f}. Would you like one?",
                order=order,
            )

        return StateMachineResult(
            message=f"I'm not sure about the price for '{item_query}'. Is there something else I can help you with?",
            order=order,
        )

    # =========================================================================
    # Recommendation Handlers
    # =========================================================================

    def handle_recommendation_inquiry(
        self,
        category: str | None,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle recommendation questions."""
        items_by_type = self._menu_data.get("items_by_type", {}) if self._menu_data else {}

        if category == "bagel":
            return self._recommend_bagels(order)
        elif category == "sandwich":
            return self._recommend_sandwiches(items_by_type, order)
        elif category == "coffee":
            return self._recommend_coffee(items_by_type, order)
        elif category == "breakfast":
            return self._recommend_breakfast(items_by_type, order)
        elif category == "lunch":
            return self._recommend_lunch(items_by_type, order)
        else:
            return self._recommend_general(items_by_type, order)

    def _recommend_bagels(self, order: "OrderTask") -> StateMachineResult:
        """Recommend popular bagel options."""
        message = (
            "Our most popular bagels are everything and plain! "
            "The everything bagel with scallion cream cheese is a customer favorite. "
            "We also have sesame, cinnamon raisin, and pumpernickel if you're feeling adventurous. "
            "Would you like to try one?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_sandwiches(self, items_by_type: dict, order: "OrderTask") -> StateMachineResult:
        """Recommend popular sandwich options."""
        signature = items_by_type.get("signature_items", [])
        egg_sandwiches = items_by_type.get("egg_sandwich", [])

        recommendations = []
        for item in signature[:2]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        if len(recommendations) < 3 and egg_sandwiches:
            name = egg_sandwiches[0].get("name", "")
            if name:
                recommendations.append(name)

        if recommendations:
            if len(recommendations) == 1:
                message = f"I'd recommend {recommendations[0]} - it's one of our favorites! Would you like to try it?"
            else:
                items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}"
                message = f"Some of our most popular are {items_str}. Would you like to try one?"
        else:
            message = "Our egg sandwiches are really popular! Would you like to hear about them?"

        return StateMachineResult(message=message, order=order)

    def _recommend_coffee(self, items_by_type: dict, order: "OrderTask") -> StateMachineResult:
        """Recommend popular coffee options."""
        message = (
            "Our lattes are really popular - you can get them hot or iced! "
            "We also have great drip coffee if you want something simple. "
            "Would you like a coffee?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_breakfast(self, items_by_type: dict, order: "OrderTask") -> StateMachineResult:
        """Recommend breakfast options."""
        signature_items = items_by_type.get("signature_item", [])
        omelettes = items_by_type.get("omelette", [])

        recommendations = []
        for item in signature_items[:1]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        recommendations.append("an everything bagel with cream cheese")

        if omelettes:
            name = omelettes[0].get("name", "")
            if name:
                recommendations.append(name)

        if len(recommendations) >= 2:
            items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}"
            message = f"For breakfast, I'd suggest {items_str}. What sounds good?"
        else:
            message = "For breakfast, our bagels with cream cheese are always a hit, or try one of our egg sandwiches! What sounds good?"

        return StateMachineResult(message=message, order=order)

    def _recommend_lunch(self, items_by_type: dict, order: "OrderTask") -> StateMachineResult:
        """Recommend lunch options."""
        signature = items_by_type.get("signature_items", [])
        salad = items_by_type.get("salad_sandwich", [])

        recommendations = []
        for item in signature[:2]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        for item in salad[:1]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        if recommendations:
            items_str = ", ".join(recommendations[:-1]) + f", or {recommendations[-1]}" if len(recommendations) > 1 else recommendations[0]
            message = f"For lunch, I'd recommend {items_str}. What sounds good?"
        else:
            message = "For lunch, our sandwiches are great! We have egg sandwiches, signature sandwiches, and salad sandwiches. What sounds good?"

        return StateMachineResult(message=message, order=order)

    def _recommend_general(self, items_by_type: dict, order: "OrderTask") -> StateMachineResult:
        """General recommendation when no specific category is asked."""
        signature_items = items_by_type.get("signature_item", [])
        signature_item_name = signature_items[0].get("name", "") if signature_items else None

        if signature_item_name:
            message = (
                f"Our {signature_item_name} is really popular! "
                "We're also known for our everything bagels with cream cheese, and our lattes are great too. "
                "What are you in the mood for?"
            )
        else:
            message = (
                "Our everything bagel with scallion cream cheese is a customer favorite! "
                "We also have great egg sandwiches and lattes. "
                "What are you in the mood for?"
            )

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # Item Description Handlers
    # =========================================================================

    def handle_item_description_inquiry(
        self,
        item_query: str | None,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle item description questions."""
        if not item_query:
            return StateMachineResult(
                message="Which item would you like to know about?",
                order=order,
            )

        item_query_lower = item_query.lower().strip()

        # Get item descriptions from menu_data (loaded from database)
        item_descriptions = self._menu_data.get("item_descriptions", {}) if self._menu_data else {}

        description = item_descriptions.get(item_query_lower)

        if not description:
            for key, desc in item_descriptions.items():
                if item_query_lower in key or key in item_query_lower:
                    description = desc
                    break

        if not description and self._menu_data:
            items_by_type = self._menu_data.get("items_by_type", {})
            for item_type, items in items_by_type.items():
                for item in items:
                    item_name = item.get("name", "").lower()
                    if item_query_lower in item_name or item_name in item_query_lower:
                        # Check if item has a description directly
                        description = item.get("description")
                        if not description:
                            # Fall back to item_descriptions lookup
                            description = item_descriptions.get(item_name)
                        if description:
                            break
                if description:
                    break

        if description:
            formatted_name = item_query.title()
            message = f"{formatted_name} has {description}. Would you like to order one?"

            # Store context so "yes" / "give me one" adds this item
            order.pending_suggested_item = formatted_name
            order.pending_field = "confirm_suggested_item"
        else:
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                "Would you like me to tell you what sandwiches or egg dishes we have?"
            )

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # Signature Menu Handlers
    # =========================================================================

    def handle_signature_menu_inquiry(
        self,
        menu_type: str | None,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle inquiry about signature/speed menu items."""
        items_by_type = self._menu_data.get("items_by_type", {}) if self._menu_data else {}

        if menu_type:
            items = items_by_type.get(menu_type, [])
            category_key = menu_type
            type_name = menu_type.replace("_", " ")
            # Check if already plural (ends with "s" but not "ss" like "grass")
            if type_name.endswith("s") and not type_name.endswith("ss"):
                type_display_name = type_name  # Already plural
            elif type_name.endswith("ch"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # Get all signature items (already aggregated with is_signature=true)
            items = items_by_type.get("signature_items", [])
            category_key = "signature_items"
            type_display_name = "signature items"

        if not items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                order=order,
            )

        # Paginate: show only DEFAULT_PAGINATION_SIZE items at a time
        batch = items[:DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - len(batch)
        has_more = remaining > 0

        # Build list of item names
        item_names = [item.get("name", "Unknown") for item in batch]

        # Format the response with pagination
        if has_more:
            # Add "...and X more" indicator
            if len(item_names) == 1:
                items_list = f"{item_names[0]}, and {remaining} more"
            else:
                items_list = ", ".join(item_names) + f", and {remaining} more"

            # Save pagination state for "what else" / "more" follow-ups
            order.set_menu_pagination(category_key, DEFAULT_PAGINATION_SIZE, len(items))
        else:
            # All items fit in one response
            items_list = self._format_item_list(item_names)
            order.clear_menu_pagination()

        return StateMachineResult(
            message=f"Our {type_display_name} are: {items_list}. Would you like any of these?",
            order=order,
        )

    def handle_more_menu_items(self, order: "OrderTask") -> StateMachineResult:
        """Handle 'show more' menu requests.

        Continues listing items from where the previous menu query left off.
        """
        pagination = order.get_menu_pagination()

        if not pagination:
            return StateMachineResult(
                message="More of what? What would you like me to list?",
                order=order,
            )

        category = pagination.get("category")
        offset = pagination.get("offset", 0)
        total_items = pagination.get("total_items", 0)

        items_by_type = self._menu_data.get("items_by_type", {}) if self._menu_data else {}
        items = items_by_type.get(category, [])

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like to order anything?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        # Build list of item names
        item_names = [item.get("name", "Unknown") for item in batch]

        # Format the response
        if has_more:
            if len(item_names) == 1:
                items_str = f"{item_names[0]}, and {remaining} more"
            else:
                items_str = ", ".join(item_names) + f", and {remaining} more"

            # Update pagination for next "what else"
            new_offset = offset + DEFAULT_PAGINATION_SIZE
            order.set_menu_pagination(category, new_offset, len(items))
            message = f"We also have: {items_str}. Would you like any of these?"
        else:
            items_str = self._format_item_list(item_names)
            order.clear_menu_pagination()
            message = f"We also have: {items_str}. That's all we have. Would you like any of these?"

        return StateMachineResult(message=message, order=order)

    # =========================================================================
    # By-the-Pound Handlers
    # =========================================================================

    def handle_by_pound_inquiry(
        self,
        category: str | None,
        order: "OrderTask",
    ) -> StateMachineResult:
        """Handle initial by-the-pound inquiry."""
        if category:
            return self.list_by_pound_category(category, order)

        order.phase = OrderPhase.CONFIGURING_ITEM.value
        order.pending_field = "by_pound_category"
        return StateMachineResult(
            message="We have cheeses, spreads, cold cuts, fish, and salads as food by the pound. Which are you interested in?",
            order=order,
        )

    def list_by_pound_category(
        self,
        category: str,
        order: "OrderTask",
    ) -> StateMachineResult:
        """List items in a specific by-the-pound category."""
        if category == "spread" and self._menu_data:
            cheese_types = self._menu_data.get("cheese_types", [])
            items = [
                name for name in cheese_types
                if any(kw in name.lower() for kw in ["cream cheese", "spread", "butter"])
            ]
        else:
            by_pound_items = get_by_pound_items()
            items = by_pound_items.get(category, [])
        category_name = get_by_pound_category_names().get(category, category)

        if not items:
            order.clear_pending()
            return StateMachineResult(
                message=f"I don't have information on {category_name} right now. What else can I get for you?",
                order=order,
            )

        if len(items) <= 3:
            items_list = ", ".join(items)
        else:
            items_list = ", ".join(items[:-1]) + f", and {items[-1]}"

        order.clear_pending()

        if category == "spread":
            message = f"Our {category_name} include: {items_list}. Would you like any of these, or something else?"
        else:
            message = f"Our {category_name} food by the pound include: {items_list}. Would you like any of these, or something else?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    # =========================================================================
    # Category List Handlers
    # =========================================================================

    def list_category_items(
        self,
        category: str,
        order: "OrderTask",
    ) -> StateMachineResult:
        """List items in a menu category (drinks, desserts, sides, etc.)."""
        category_name = {
            "drinks": "drinks",
            "sides": "sides",
            "signature_bagels": "bagels",
            "signature_omelettes": "sandwiches and omelettes",
            "desserts": "desserts",
        }.get(category, "items")

        items = []
        if self._menu_data:
            items = self._menu_data.get(category, [])

            if not items:
                type_map = {
                    "sides": ["side"],
                    "drinks": ["drink", "coffee", "soda", "sized_beverage", "beverage"],
                    "desserts": ["dessert", "pastry", "snack"],
                    "signature_bagels": ["signature_item"],
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

        item_names = [item.get("name", "Unknown") for item in items[:10]]
        items_str = self._format_item_list(item_names)

        return StateMachineResult(
            message=f"For {category_name}, we have: {items_str}. Would you like any of these?",
            order=order,
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _format_item_list(self, items: list[str]) -> str:
        """Format a list of items as natural language."""
        if len(items) == 1:
            return items[0]
        elif len(items) == 2:
            return f"{items[0]} and {items[1]}"
        else:
            return ", ".join(items[:-1]) + f", and {items[-1]}"
