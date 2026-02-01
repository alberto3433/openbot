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
from orderbot.cache import menu_cache

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

    def _format_delivery_response(
        self, delivering_stores: list, location_display: str, order: OrderTask
    ) -> StateMachineResult:
        """Format delivery availability response for a location.

        Args:
            delivering_stores: List of stores that deliver to the location
            location_display: Human-readable location name for messages
            order: Current order state

        Returns:
            StateMachineResult with appropriate delivery message
        """
        if delivering_stores:
            if len(delivering_stores) == 1:
                store_name = delivering_stores[0].get("name", "our store")
                message = f"Yes! {store_name} delivers to {location_display}. Would you like to place a delivery order?"
            else:
                store_names = [s.get("name", "Store") for s in delivering_stores]
                stores_str = format_english_list(store_names)
                message = f"Yes! We can deliver to {location_display} from {stores_str}. Would you like to place a delivery order?"
            return StateMachineResult(message=message, order=order)

        # No stores deliver to this location
        return StateMachineResult(
            message=f"Unfortunately, we don't currently deliver to {location_display}. You're welcome to place a pickup order instead. Would you like to do that?",
            order=order,
        )

    def _check_delivery_for_zip(
        self, zip_code: str, all_stores: list, order: OrderTask, original_query: str | None = None
    ) -> StateMachineResult:
        """Check which stores deliver to a specific zip code."""
        delivering_stores = []
        location_display = original_query or zip_code

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if zip_code in delivery_zips:
                delivering_stores.append(store)

        return self._format_delivery_response(delivering_stores, location_display, order)

    def _check_delivery_for_neighborhood(
        self, neighborhood: str, zip_codes: list, all_stores: list, order: OrderTask
    ) -> StateMachineResult:
        """Check which stores deliver to any of the neighborhood's zip codes."""
        delivering_stores = []

        for store in all_stores:
            delivery_zips = store.get("delivery_zip_codes", [])
            if any(z in delivery_zips for z in zip_codes):
                delivering_stores.append(store)

        return self._format_delivery_response(delivering_stores, neighborhood, order)

    # =========================================================================
    # Recommendation Handlers
    # =========================================================================

    def handle_recommendation_inquiry(
        self,
        match_type: str | None,
        order: OrderTask,
        item_type_slug: str | None = None,
        menu_item_ids: list[int] | None = None,
        search_term: str | None = None,
    ) -> StateMachineResult:
        """Handle recommendation questions with data-driven responses.

        IMPORTANT: This should NOT add anything to the cart. It's just answering a question.
        The user needs to explicitly order something after getting the recommendation.

        Args:
            match_type: Type of match ("general", "item_type", or "menu_items")
            order: Current order state (unchanged)
            item_type_slug: Item type slug when match_type is "item_type"
            menu_item_ids: Menu item IDs when match_type is "menu_items"
            search_term: Original search term (e.g., "bagel", "coffee")
        """
        max_items = 5

        # Determine effective search term
        effective_term = search_term or item_type_slug

        # ALWAYS search ingredients first if we have a search term
        # This handles "what bagels do you recommend" -> finds bagel types in bread category
        if effective_term:
            ingredient_items = self._search_ingredients_by_term(effective_term, max_items)
            if ingredient_items:
                return self._format_recommendation_response(ingredient_items, effective_term, order)

        # Handle specific menu item matches (by ID) - only if no ingredients found
        if match_type == "menu_items" and menu_item_ids:
            items = self._get_menu_item_names_by_ids(menu_item_ids[:max_items])
            if items:
                return self._format_recommendation_response(items, effective_term, order)

        # Handle item type matches - fall back to menu items by item type
        if match_type == "item_type" and item_type_slug:
            menu_items = menu_cache.get_items_by_item_type(item_type_slug)
            if menu_items:
                item_names = [item.get("name") for item in menu_items[:max_items] if item.get("name")]
                if item_names:
                    display_name = menu_cache.get_item_type_display_name(item_type_slug)
                    return self._format_recommendation_response(item_names, display_name, order)

        # Generic fallback - show item types to help user decide
        return self._format_item_type_suggestions(order)

    def _search_ingredients_by_term(self, search_term: str, max_items: int) -> list[str]:
        """Search all ingredient categories for items containing the search term.

        Args:
            search_term: Term to search for (e.g., "bagel")
            max_items: Maximum number of items to return

        Returns:
            List of ingredient names that contain the search term.
        """
        search_lower = search_term.lower()
        matching_items = []

        # Get all ingredient categories
        categories = menu_cache.get_all_ingredient_categories()

        for category in categories:
            details = menu_cache.get_ingredient_details(category)
            for ingredient in details:
                name = ingredient.get("name", "")
                if search_lower in name.lower():
                    matching_items.append(name)
                    if len(matching_items) >= max_items:
                        return matching_items

        return matching_items

    def _get_menu_item_names_by_ids(self, item_ids: list[int]) -> list[str]:
        """Get menu item names by their IDs.

        Args:
            item_ids: List of menu item IDs to look up

        Returns:
            List of item names (in order of IDs provided, skipping not found).
        """
        # Build a lookup from ID to name by iterating through all items
        id_to_name: dict[int, str] = {}
        for item_data in menu_cache._all_menu_items_by_name.values():
            item_id = item_data.get("id")
            if item_id in item_ids:
                id_to_name[item_id] = item_data.get("name", f"Item {item_id}")

        # Return names in the order of requested IDs
        return [id_to_name[item_id] for item_id in item_ids if item_id in id_to_name]

    def _format_recommendation_response(
        self,
        items: list[str],
        category_name: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format a recommendation response with item names.

        Args:
            items: List of item names to recommend
            category_name: Optional category name for context
            order: Current order state (unchanged)
        """
        if not items:
            return self._format_item_type_suggestions(order)

        # Format item list naturally
        if len(items) == 1:
            item_list = items[0]
        elif len(items) == 2:
            item_list = f"{items[0]} and {items[1]}"
        else:
            item_list = ", ".join(items[:-1]) + f", and {items[-1]}"

        if category_name:
            message = f"Popular {category_name.lower()} options include {item_list}. Would you like one of these?"
        else:
            message = f"Popular options include {item_list}. Would you like one of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _format_item_type_suggestions(self, order: OrderTask) -> StateMachineResult:
        """Format a response with item type suggestions for generic recommendation requests.

        Shows up to 5 item types (plural display names), with pagination support
        for the rest via "what else" follow-ups.

        Args:
            order: Current order state
        """
        # Get all item types and their display names
        # Filter to only customer-facing item types (not ingredient categories)
        all_slugs = sorted(menu_cache.get_all_item_type_slugs())
        item_types_with_names = []

        for slug in all_slugs:
            display_name = menu_cache.get_item_type_display_name(slug, plural=True)
            # Skip if:
            # 1. No display name
            # 2. Display name is just the slug
            # 3. Display name starts with lowercase (internal/ingredient category)
            if not display_name or display_name == slug:
                continue
            if display_name[0].islower():
                continue
            item_types_with_names.append((slug, display_name))

        if not item_types_with_names:
            return StateMachineResult(
                message="We have a great selection! What are you in the mood for?",
                order=order,
            )

        # Show first 5 item types
        page_size = DEFAULT_PAGINATION_SIZE
        first_page = item_types_with_names[:page_size]
        has_more = len(item_types_with_names) > page_size

        # Format the list
        type_names = [name for _, name in first_page]
        if len(type_names) == 1:
            type_list = type_names[0]
        elif len(type_names) == 2:
            type_list = f"{type_names[0]} and {type_names[1]}"
        else:
            type_list = ", ".join(type_names[:-1]) + f", and {type_names[-1]}"

        # Build message
        message = f"We have a great selection! What are you in the mood for? We have {type_list}"
        if has_more:
            message += ", and more"
            # Store pagination state for "what else" follow-ups
            order.menu_query_pagination = {
                "type": "item_types",
                "items": [name for _, name in item_types_with_names],
                "offset": page_size,
            }
        message += "."

        return StateMachineResult(
            message=message,
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
            message = f"For {display_name.lower()}, we have {items_str}, and more. Would you like one of these, or want to hear more?"

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
        from ..cache import menu_cache

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
