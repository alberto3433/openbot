"""
Query Handler for Informational Inquiries.

This module handles all informational queries about the menu, prices,
store information, recommendations, and item descriptions.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache

from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_item_type_display_name,
)
from .mixins import MenuDataMixin

# All category behavior is now data-driven via database:
# - Category table + MenuItemCategory join: groups items by category (e.g., "sandwich", "drink")
# - ItemType aliases: maps user terms to item type slugs

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


class QueryHandler(MenuDataMixin):
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
    def store_info(self) -> dict:
        return self._store_info

    @store_info.setter
    def store_info(self, value: dict | None):
        self._store_info = value or {}

    # =========================================================================
    # Helper Methods for Data-Driven Messages
    # =========================================================================

    def _get_available_menu_categories_message(self) -> str:
        """Build a message listing a few available menu categories from database.

        Returns a formatted string like "sandwiches or beverages" for use in
        helpful suggestions when an item isn't found.
        """
        try:
            # Get a few main categories to suggest
            categories = menu_cache.get_available_menu_categories()
            if categories:
                # Pick 2-3 main categories
                display_names = list(categories.values())[:3]
                if len(display_names) == 1:
                    return display_names[0].lower()
                elif len(display_names) == 2:
                    return f"{display_names[0].lower()} or {display_names[1].lower()}"
                else:
                    return f"{display_names[0].lower()}, {display_names[1].lower()}, or {display_names[2].lower()}"
        except Exception as e:
            logger.warning("Failed to get available categories from database: %s", e)

        # Fallback message
        return "sandwiches or egg dishes"

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
        """Handle inquiry about menu items by type.

        Uses a single generic flow for all categories:
        1. Try to find category match via database (ItemType or Category)
        2. If found, get items based on lookup_type:
           - "item_type": query by item_type_id (from items_by_type)
           - "category": query via MenuItemCategory (from menu_cache.get_items_by_category)
        3. If not found, fall back to partial string matching across all items
        """
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

        # 1. Try to find category match via database (aliases, keywords)
        category_info = menu_cache.get_category_keyword_mapping(menu_query_type.lower())

        if category_info:
            # Get display name from database
            display_name = category_info.get("display_name_plural") or category_info.get("display_name", menu_query_type)
            slug = category_info.get("slug")
            lookup_type = category_info.get("lookup_type", "item_type")

            # Get items based on lookup_type
            items = []
            if lookup_type == "category":
                # Query via MenuItemCategory join table
                items = menu_cache.get_items_by_category(slug)
            else:
                # Query by item_type_id (from items_by_type)
                items = items_by_type.get(slug, [])
                # Also check original query term for mock data compatibility
                if not items:
                    query_key = menu_query_type.lower()
                    if query_key in items_by_type:
                        items = items_by_type.get(query_key, [])

            if items:
                items_str = self._format_items_with_prices(items[:15], show_prices, slug)
                if len(items) > 15:
                    items_str += f", and {len(items) - 15} more"

                message = f"Our {display_name} include: {items_str}. Would you like any of these?"
                return StateMachineResult(message=message, order=order)

        # 2. Fallback: Check if query matches keys in items_by_type
        # This handles mock data in tests and direct type slug lookups
        search_term = menu_query_type.lower()

        # First try exact key match
        if search_term in items_by_type:
            items = items_by_type.get(search_term, [])
            if items:
                items_str = self._format_items_with_prices(items[:15], show_prices, search_term)
                if len(items) > 15:
                    items_str += f", and {len(items) - 15} more"
                type_display = self._pluralize(menu_query_type)
                return StateMachineResult(
                    message=f"Our {type_display} include: {items_str}. Would you like any of these?",
                    order=order,
                )

        # Then try aggregating from keys that contain the search term
        # e.g., "beverage" matches "sized_beverage" and "beverage"
        aggregated_items = []
        for type_slug, items in items_by_type.items():
            if search_term in type_slug or type_slug in search_term:
                aggregated_items.extend(items)

        if aggregated_items:
            items_str = self._format_items_with_prices(aggregated_items[:15], show_prices)
            if len(aggregated_items) > 15:
                items_str += f", and {len(aggregated_items) - 15} more"
            type_display = self._pluralize(menu_query_type)
            return StateMachineResult(
                message=f"Our {type_display} include: {items_str}. Would you like any of these?",
                order=order,
            )

        # 4. Fallback: partial string match across ALL menu items (item names)
        matching_items = []
        for type_slug, items in items_by_type.items():
            for item in items:
                if search_term in item.get("name", "").lower():
                    matching_items.append(item)

        if matching_items:
            items_str = self._format_items_with_prices(matching_items[:15], show_prices)
            if len(matching_items) > 15:
                items_str += f", and {len(matching_items) - 15} more"
            type_display = self._pluralize(menu_query_type)
            return StateMachineResult(
                message=f"Our {type_display} include: {items_str}. Would you like any of these?",
                order=order,
            )

        # 5. Not found - show available types
        display_names = self._menu_data.get("item_type_display_names", {}) if self._menu_data else {}
        available_types = [get_item_type_display_name(t, display_names) for t, i in items_by_type.items() if i]
        type_display = get_item_type_display_name(menu_query_type, display_names)
        if available_types:
            return StateMachineResult(
                message=f"I couldn't find {type_display}. We have {', '.join(available_types)}. What would you like?",
                order=order,
            )
        return StateMachineResult(
            message=f"I'm sorry, I don't have any {type_display} on the menu. What else can I help you with?",
            order=order,
        )

    def _format_items_with_prices(
        self,
        items: list,
        show_prices: bool,
        item_type_slug: str | None = None,
    ) -> str:
        """Format a list of items, optionally with prices."""
        if show_prices:
            item_list = []
            for item in items:
                name = item.get('name', 'Unknown')
                price = item.get('price') or item.get('base_price') or 0
                item_list.append(f"{name} (${price:.2f})")
        else:
            item_list = [item.get("name", "Unknown") for item in items]
        return self._format_item_list(item_list)

    def _pluralize(self, word: str) -> str:
        """Pluralize a word for display."""
        word = word.replace("_", " ")
        if word.endswith("s") and not word.endswith("ss"):
            return word  # Already plural
        elif word.endswith("ch") or word.endswith("sh") or word.endswith("x"):
            return word + "es"
        else:
            return word + "s"

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

        # Use data-driven lookup from ItemType/Category for category price inquiries
        category_info = menu_cache.get_category_keyword_mapping(query_lower)
        if category_info:
            slug = category_info.get("slug")
            lookup_type = category_info.get("lookup_type", "item_type")
            display_name_plural = category_info.get("display_name_plural", f"{query_lower}s")

            # Get items based on lookup_type to find minimum price
            items = []
            if lookup_type == "category":
                items = menu_cache.get_items_by_category(slug)
            else:
                items = items_by_type.get(slug, [])

            if items:
                # Find minimum price from items
                prices = [item.get("price") or item.get("base_price") or 0 for item in items]
                prices = [p for p in prices if p > 0]
                if prices:
                    min_price = min(prices)
                    return StateMachineResult(
                        message=f"Our {display_name_plural} start at ${min_price:.2f}. Would you like one?",
                        order=order,
                    )

            # Try pricing engine as fallback
            if self._pricing:
                try:
                    min_price = self._pricing.get_min_price_for_category(slug)
                    if min_price > 0:
                        return StateMachineResult(
                            message=f"Our {display_name_plural} start at ${min_price:.2f}. Would you like one?",
                            order=order,
                        )
                except (ValueError, KeyError) as e:
                    logger.debug("Could not get min price for category %s: %s", slug, e)

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

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
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
        """Handle recommendation questions with a generic response."""
        return StateMachineResult(
            message="We have a great selection! What are you in the mood for?",
            order=order,
        )

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
            available_categories = self._get_available_menu_categories_message()
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                f"Would you like me to tell you what {available_categories} we have?"
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
