"""
Store Info Handler for Order State Machine.

This module handles store information inquiries (hours, location, delivery zones)
and recommendation requests.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import NYC_NEIGHBORHOOD_ZIPS

logger = logging.getLogger(__name__)


class StoreInfoHandler:
    """
    Handles store information inquiries and recommendations.

    Manages store hours, location, delivery zone checks, and menu recommendations.
    """

    def __init__(
        self,
        menu_data: dict | None = None,
    ):
        """
        Initialize the store info handler.

        Args:
            menu_data: Menu data dictionary for recommendations.
        """
        self._menu_data = menu_data or {}
        self._store_info: dict | None = None

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

    def set_store_info(self, store_info: dict | None) -> None:
        """Set the store info for this request."""
        self._store_info = store_info

    def handle_store_hours_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store hours.

        Uses store_info from the process() call to get hours.
        If store_info is not available (no store context), asks the user which store.
        """
        store_info = self._store_info or {}
        hours = store_info.get("hours")
        store_name = store_info.get("name")

        if hours:
            # We have hours info - return it
            if store_name:
                message = f"Our hours at {store_name} are {hours}. Can I help you with an order?"
            else:
                message = f"Our hours are {hours}. Can I help you with an order?"
            return StateMachineResult(message=message, order=order)

        # No hours info available
        if store_name:
            # We know the store but don't have hours configured
            return StateMachineResult(
                message=f"I don't have the hours for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        # No store context at all - we can't determine which store
        return StateMachineResult(
            message="Which location would you like the hours for?",
            order=order,
        )

    def handle_store_location_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about store location/address.

        Uses store_info from the process() call to get address.
        If store_info is not available (no store context), asks the user which store.
        """
        store_info = self._store_info or {}
        address = store_info.get("address")
        city = store_info.get("city")
        state = store_info.get("state")
        zip_code = store_info.get("zip_code")
        store_name = store_info.get("name")

        # Build full address if we have the parts
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

        # No address info available
        if store_name:
            # We know the store but don't have address configured
            return StateMachineResult(
                message=f"I don't have the address for {store_name} right now. Is there anything else I can help you with?",
                order=order,
            )

        # No store context at all - we can't determine which store
        return StateMachineResult(
            message="Which location would you like the address for?",
            order=order,
        )

    def handle_delivery_zone_inquiry(self, query: str | None, order: OrderTask) -> StateMachineResult:
        """Handle inquiry about whether we deliver to a specific location.

        Process:
        1. If query is a zip code (5 digits), check directly
        2. If query is a neighborhood, look up zip codes in NYC_NEIGHBORHOOD_ZIPS
        3. If it looks like an address, geocode it to get the zip code
        4. Do reverse lookup across all stores to find which deliver to that zip

        Args:
            query: The location they're asking about (zip, neighborhood, or address)
            order: Current order state
        """
        store_info = self._store_info or {}
        all_stores = store_info.get("all_stores", [])

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

        # Check if it's a known neighborhood
        neighborhood_key = query_clean.replace("'", "'").strip()
        if neighborhood_key in NYC_NEIGHBORHOOD_ZIPS:
            zip_codes = NYC_NEIGHBORHOOD_ZIPS[neighborhood_key]
            # Check if any of these zip codes are in delivery zones
            return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Try fuzzy matching for neighborhoods (common variations)
        for key in NYC_NEIGHBORHOOD_ZIPS:
            if key in query_clean or query_clean in key:
                zip_codes = NYC_NEIGHBORHOOD_ZIPS[key]
                return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Check if it looks like an address (has numbers suggesting a street address)
        if re.search(r'\d+\s+\w+', query):
            # Try to geocode the address to get a zip code
            from ..address_service import geocode_to_zip
            zip_code = geocode_to_zip(query)
            if zip_code:
                logger.info("Geocoded '%s' to zip code: %s", query, zip_code)
                return self._check_delivery_for_zip(zip_code, all_stores, order, original_query=query)

        # Unknown location - ask for more specific info
        return StateMachineResult(
            message=f"I'm not sure about {query}. Could you give me a zip code or street address so I can check our delivery area?",
            order=order,
        )

    def _check_delivery_for_zip(
        self, zip_code: str, all_stores: list, order: OrderTask, original_query: str | None = None
    ) -> StateMachineResult:
        """Check which stores deliver to a specific zip code.

        Args:
            zip_code: The zip code to check
            all_stores: List of all stores with delivery zones
            order: Current order state
            original_query: Original address/location query (for nicer messages)
        """
        delivering_stores = []
        # Use original query in messages if provided, otherwise use zip code
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

        # No stores deliver to this zip
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {location_display}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    def _check_delivery_for_neighborhood(
        self, neighborhood: str, zip_codes: list, all_stores: list, order: OrderTask
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

        covered_zips = list(set(covered_zips))  # Remove duplicates

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

        # No stores deliver to this neighborhood
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {neighborhood}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    # =========================================================================
    # Recommendation Handlers
    # =========================================================================

    def handle_recommendation_inquiry(
        self,
        category: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle recommendation questions like 'what do you recommend?' or 'what's your best bagel?'

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the recommendation.

        Args:
            category: Type of recommendation asked - 'bagel', 'sandwich', 'coffee', 'breakfast', 'lunch', or None
            order: Current order state (unchanged)
        """
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
            # General recommendation - suggest popular items
            return self._recommend_general(items_by_type, order)

    def _recommend_bagels(self, order: OrderTask) -> StateMachineResult:
        """Recommend popular bagel options."""
        message = (
            "Our most popular bagels are everything and plain! "
            "The everything bagel with scallion cream cheese is a customer favorite. "
            "We also have sesame, cinnamon raisin, and pumpernickel if you're feeling adventurous. "
            "Would you like to try one?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_sandwiches(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend popular sandwich options from the menu."""
        # Look for signature sandwiches or egg sandwiches
        signature = items_by_type.get("signature_sandwich", [])
        egg_sandwiches = items_by_type.get("egg_sandwich", [])

        recommendations = []

        # Get up to 2 signature sandwiches
        for item in signature[:2]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        # Get 1 egg sandwich if we have room
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

    def _recommend_coffee(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend popular coffee options."""
        message = (
            "Our lattes are really popular - you can get them hot or iced! "
            "We also have great drip coffee if you want something simple. "
            "Would you like a coffee?"
        )
        return StateMachineResult(message=message, order=order)

    def _recommend_breakfast(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend breakfast options."""
        # Look for speed menu bagels and egg items
        speed_menu = items_by_type.get("speed_menu_bagel", [])
        omelettes = items_by_type.get("omelette", [])

        recommendations = []

        # Get a speed menu bagel
        for item in speed_menu[:1]:
            name = item.get("name", "")
            if name:
                recommendations.append(name)

        # Add a classic suggestion
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

    def _recommend_lunch(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """Recommend lunch options."""
        signature = items_by_type.get("signature_sandwich", [])
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

    def _recommend_general(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """General recommendation when no specific category is asked."""
        speed_menu = items_by_type.get("speed_menu_bagel", [])

        # Get a speed menu item name if available
        speed_item = None
        if speed_menu:
            speed_item = speed_menu[0].get("name", "")

        if speed_item:
            message = (
                f"Our {speed_item} is really popular! "
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
