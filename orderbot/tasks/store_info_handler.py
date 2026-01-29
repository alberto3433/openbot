"""
Store Info Handler for Order State Machine.

This module handles store information inquiries (hours, location, delivery zones)
and recommendation requests.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import OrderContext

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE, get_item_type_display_name
from .mixins import MenuDataMixin
from .utils.text import format_english_list

# Note: NYC_NEIGHBORHOOD_ZIPS was moved to the database (neighborhood_zip_codes table)
# Neighborhood data is now loaded via menu_data["neighborhood_zip_codes"]

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)

logger = logging.getLogger(__name__)


class StoreInfoHandler(MenuDataMixin):
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

    def set_context(self, ctx: "OrderContext") -> None:
        """Set context from unified OrderContext."""
        self._store_info = ctx.store_info

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
                stores_str = format_english_list(store_names)
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
                stores_str = format_english_list(store_names)
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
        """Handle recommendation questions with a generic response.

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the recommendation.

        Args:
            category: Type of recommendation asked (unused - returns generic response)
            order: Current order state (unchanged)
        """
        return StateMachineResult(
            message="We have a great selection! What are you in the mood for?",
            order=order,
        )

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
            item_type: Type of item asked about
            category: Specific category asked about
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

        For categories with database-backed items
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
            items_str = format_english_list(items_list)

            order.clear_menu_pagination()
            message = f"For {display_name.lower()}, we have {items_str}. {prompt_suffix}"
        else:
            # Show first batch with pagination
            first_batch = items_list[:DEFAULT_PAGINATION_SIZE]
            items_str = format_english_list(first_batch)

            # Set pagination state for "what else" follow-ups
            order.set_menu_pagination(category, DEFAULT_PAGINATION_SIZE, len(items_list))
            message = f"For {display_name.lower()}, we have {items_str}, and more. {prompt_suffix}"

        return StateMachineResult(message=message, order=order)

    def _describe_item_modifiers(
        self,
        item_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Describe all available modifiers for a specific item type.

        Fully data-driven: queries the database for which ingredient categories
        are valid for this item type and builds the message dynamically.
        """
        from ..menu_data_cache import menu_cache

        item_type_display = get_item_type_display_name(item_type)

        # Get ingredients grouped by category for this specific item type
        ingredients_by_category = menu_cache.get_ingredients_by_category_for_item_type(item_type)

        if not ingredients_by_category:
            # No modifiers defined for this item type
            return StateMachineResult(
                message=f"For {item_type_display}, we don't have additional add-ons. What else can I help you with?",
                order=order,
            )

        # Build message dynamically from database
        parts = [f"For {item_type_display}, you can add:"]

        for category_slug, ingredients in ingredients_by_category.items():
            if not ingredients:
                continue

            # Get display name from database
            display_name = menu_cache.get_ingredient_category_display_name(category_slug)

            # Format a sample of ingredients (limit to 4 for readability)
            ingredient_list = sorted(ingredients)[:4]
            ingredients_str = format_english_list(ingredient_list, conjunction="or")

            parts.append(f"• {display_name}: {ingredients_str}")

        parts.append("What would you like?")
        message = "\n".join(parts)

        return StateMachineResult(message=message, order=order)

    def _describe_general_modifiers(self, order: OrderTask) -> StateMachineResult:
        """Describe general modifier options when no specific item/category is asked."""
        message = (
            "We have lots of ways to customize your order! "
            "What item are you curious about?"
        )
        return StateMachineResult(message=message, order=order)
