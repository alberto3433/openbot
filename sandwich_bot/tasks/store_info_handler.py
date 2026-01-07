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
from .parsers.constants import DEFAULT_PAGINATION_SIZE

# Note: NYC_NEIGHBORHOOD_ZIPS was moved to the database (neighborhood_zip_codes table)
# Neighborhood data is now loaded via menu_data["neighborhood_zip_codes"]

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)

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
                message = f"Store hours for our {store_name} location are {hours}. Can I help you with an order?"
            else:
                message = f"Our store hours are {hours}. Can I help you with an order?"
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
                message = f"The address for our {store_name} location is {full_address}. Can I help you with an order?"
            else:
                message = f"Our address is {full_address}. Can I help you with an order?"
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

    def handle_customer_service_inquiry(self, order: OrderTask) -> StateMachineResult:
        """Handle customer service escalation requests.

        When a customer says things like "I want to speak to a manager", "my order was wrong",
        or "I need a refund", provide them with the corporate email and store phone number.

        Args:
            order: Current order state (unchanged)

        Returns:
            StateMachineResult with contact information for customer service
        """
        store_info = self._store_info or {}
        store_phone = store_info.get("phone")
        store_name = store_info.get("name")

        # Get company info from menu_data
        company_info = self._menu_data.get("company_info", {})
        corporate_email = company_info.get("corporate_email")
        instagram_handle = company_info.get("instagram_handle")
        feedback_form_url = company_info.get("feedback_form_url")

        # Build the response message
        contact_parts = []

        if store_phone:
            if store_name:
                contact_parts.append(f"call our {store_name} location at {store_phone}")
            else:
                contact_parts.append(f"call us at {store_phone}")

        if corporate_email:
            contact_parts.append(f"email us at {corporate_email}")

        if feedback_form_url:
            contact_parts.append(f"submit feedback at {feedback_form_url}")

        if contact_parts:
            contact_str = ", or ".join(contact_parts)
            message = (
                f"I'm sorry to hear that. For customer service assistance, you can {contact_str}. "
                "Our team will be happy to help resolve any issues. Is there anything else I can help with?"
            )
        else:
            # Fallback if no contact info is available
            message = (
                "I'm sorry to hear that. Please reach out to our team for assistance with your concern. "
                "Is there anything else I can help with?"
            )

        return StateMachineResult(message=message, order=order)

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

        # Check if it's a known neighborhood (from database)
        neighborhood_zip_codes = self._menu_data.get("neighborhood_zip_codes", {})
        neighborhood_key = query_clean.replace("'", "'").strip()
        if neighborhood_key in neighborhood_zip_codes:
            zip_codes = neighborhood_zip_codes[neighborhood_key]
            # Check if any of these zip codes are in delivery zones
            return self._check_delivery_for_neighborhood(query, zip_codes, all_stores, order)

        # Try fuzzy matching for neighborhoods (common variations)
        for key in neighborhood_zip_codes:
            if key in query_clean or query_clean in key:
                zip_codes = neighborhood_zip_codes[key]
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
        # Look for signature items (all items with is_signature=true) or egg sandwiches
        signature = items_by_type.get("signature_items", [])
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
        # Look for signature items and egg items
        signature_items = items_by_type.get("signature_item", [])
        omelettes = items_by_type.get("omelette", [])

        recommendations = []

        # Get a signature item
        for item in signature_items[:1]:
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

    def _recommend_general(self, items_by_type: dict, order: OrderTask) -> StateMachineResult:
        """General recommendation when no specific category is asked."""
        signature_items = items_by_type.get("signature_item", [])

        # Get a signature item name if available
        signature_item_name = None
        if signature_items:
            signature_item_name = signature_items[0].get("name", "")

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
    # Modifier Inquiry Handlers
    # =========================================================================

    def handle_modifier_inquiry(
        self,
        item_type: str | None,
        category: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle modifier/add-on questions like 'what can I add to coffee?' or 'what sweeteners do you have?'

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.

        Args:
            item_type: Type of item asked about - 'coffee', 'tea', 'hot_chocolate', 'bagel', 'sandwich', or None
            category: Specific category asked about - 'sweeteners', 'milks', 'syrups', 'spreads', etc., or None
            order: Current order state (unchanged)
        """
        # If specific category asked about, return just that category
        if category:
            return self._describe_modifier_category(category, item_type, order)

        # If specific item asked about, describe all modifiers for that item
        if item_type:
            return self._describe_item_modifiers(item_type, order)

        # Generic question - describe most common options
        return self._describe_general_modifiers(order)

    def _describe_modifier_category(
        self,
        category: str,
        item_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Describe available options for a specific modifier category.

        For categories with database-backed items (toppings, proteins, cheeses, spreads),
        this method loads items dynamically and sets pagination state for "what else" follow-ups.

        Category data is loaded from menu_data["modifier_categories"] which comes from the
        modifier_categories database table. Falls back to hardcoded values if not found.
        """
        # Try to get category info from menu_data (database-backed)
        modifier_categories = self._menu_data.get("modifier_categories", {})
        categories_data = modifier_categories.get("categories", {})
        cat_info = categories_data.get(category)

        if cat_info:
            # Check if this category loads from ingredients (needs pagination)
            if cat_info.get("options"):
                # Database-backed category with dynamic options
                return self._describe_db_modifier_category_from_menu(
                    category, cat_info, order
                )
            elif cat_info.get("description"):
                # Static category with fixed description
                description = cat_info.get("description", "")
                prompt_suffix = cat_info.get("prompt_suffix", "What would you like?")
                message = f"{description} {prompt_suffix}"
                order.clear_menu_pagination()
                return StateMachineResult(message=message, order=order)

        # Category not found in database - log warning and return generic response
        logger.warning("Modifier category '%s' not found in database", category)
        order.clear_menu_pagination()
        return StateMachineResult(
            message="We have various options available. What would you like?",
            order=order
        )

    def _describe_db_modifier_category_from_menu(
        self,
        category: str,
        cat_info: dict,
        order: OrderTask,
    ) -> StateMachineResult:
        """Describe a modifier category using pre-loaded options from menu_data.

        Args:
            category: Category key for pagination (e.g., 'toppings', 'proteins')
            cat_info: Category info dict from menu_data with 'options', 'description', etc.
            order: Current order state
        """
        options = cat_info.get("options", [])
        display_name = cat_info.get("display_name", category.title())
        prompt_suffix = cat_info.get("prompt_suffix", "What would you like?")

        if not options:
            order.clear_menu_pagination()
            return StateMachineResult(
                message=f"We have various {display_name.lower()} available. {prompt_suffix}",
                order=order,
            )

        # Format options for display
        items_list = sorted(options)

        if len(items_list) <= DEFAULT_PAGINATION_SIZE:
            # Show all items, no pagination needed
            if len(items_list) == 1:
                items_str = items_list[0]
            elif len(items_list) == 2:
                items_str = f"{items_list[0]} and {items_list[1]}"
            else:
                items_str = ", ".join(items_list[:-1]) + f", and {items_list[-1]}"

            order.clear_menu_pagination()
            message = f"For {display_name.lower()}, we have {items_str}. {prompt_suffix}"
        else:
            # Show first batch with pagination
            first_batch = items_list[:DEFAULT_PAGINATION_SIZE]
            if len(first_batch) == 1:
                items_str = first_batch[0]
            elif len(first_batch) == 2:
                items_str = f"{first_batch[0]} and {first_batch[1]}"
            else:
                items_str = ", ".join(first_batch[:-1]) + f", and {first_batch[-1]}"

            # Set pagination state for "what else" follow-ups
            order.set_menu_pagination(category, DEFAULT_PAGINATION_SIZE, len(items_list))
            message = f"For {display_name.lower()}, we have {items_str}, and more. {prompt_suffix}"

        return StateMachineResult(message=message, order=order)

    def _describe_item_modifiers(
        self,
        item_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Describe all available modifiers for a specific item type."""
        item_modifiers = {
            "coffee": (
                "For coffee, you can add:\n"
                "• Sweeteners: sugar, raw sugar, honey, Equal, Splenda, or Stevia\n"
                "• Milk: whole, skim, 2%, oat, almond, or soy\n"
                "• Flavor syrups: vanilla, hazelnut, or caramel\n"
                "Just let me know what you'd like!"
            ),
            "tea": (
                "For tea, you can add:\n"
                "• Sweeteners: sugar, raw sugar, honey, Equal, Splenda, or Stevia\n"
                "• Milk: whole, skim, 2%, oat, almond, or soy\n"
                "What would you like in your tea?"
            ),
            "hot_chocolate": (
                "For hot chocolate, you can add whipped cream or extra chocolate. "
                "What would you like?"
            ),
            "bagel": (
                "For bagels, you can add:\n"
                "• Spreads: cream cheese (plain, scallion, vegetable), butter, peanut butter, or Nutella\n"
                "• Proteins: bacon, lox, whitefish, or eggs\n"
                "• Cheeses: American, Swiss, cheddar, muenster\n"
                "• Veggies: tomato, onion, lettuce, cucumber, capers\n"
                "What sounds good?"
            ),
            "sandwich": (
                "For sandwiches, you can customize with:\n"
                "• Extra proteins: bacon, ham, turkey\n"
                "• Cheeses: American, Swiss, cheddar, muenster, provolone\n"
                "• Veggies: lettuce, tomato, onion, pickles\n"
                "• Sauces: mayo, mustard, hot sauce\n"
                "What would you like to add or change?"
            ),
        }

        message = item_modifiers.get(
            item_type,
            "We have various add-ons available. What would you like to add?"
        )

        return StateMachineResult(message=message, order=order)

    def _describe_general_modifiers(self, order: OrderTask) -> StateMachineResult:
        """Describe general modifier options when no specific item/category is asked."""
        message = (
            "We have lots of ways to customize your order! "
            "For drinks, we have various sweeteners, milks, and flavor syrups. "
            "For bagels, we have cream cheese, butter, and lots of toppings. "
            "What are you curious about?"
        )
        return StateMachineResult(message=message, order=order)
