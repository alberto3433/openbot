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

from sandwich_bot.menu_data_cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_item_type_display_name,
)

logger = logging.getLogger(__name__)

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)


class MenuInquiryHandler:
    """
    Handles menu-related inquiries.

    Manages menu listings, price inquiries, item descriptions, and signature menu queries.
    """

    # Note: ITEM_DESCRIPTIONS has been moved to the database (menu_items.description column)
    # Item descriptions are now loaded via menu_data["item_descriptions"]

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        list_by_pound_category: Callable[[str, OrderTask], StateMachineResult] | None = None,
        **kwargs,
    ):
        """
        Initialize the menu inquiry handler.

        Args:
            config: HandlerConfig with shared dependencies.
            list_by_pound_category: Callback to list items in a by-the-pound category.
            **kwargs: Legacy parameter support.
        """
        if config:
            self._menu_data = config.menu_data or {}
            self.pricing = config.pricing
        else:
            # Legacy support for direct parameters
            self._menu_data = kwargs.get("menu_data") or {}
            self.pricing = kwargs.get("pricing")

        # Handler-specific callback
        self._list_by_pound_category = list_by_pound_category or kwargs.get("list_by_pound_category")

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}

    def _get_sandwich_subtypes_message(self) -> str:
        """Build a message listing sandwich sub-types from database.

        Returns a formatted string like "egg sandwiches, fish sandwiches, and more"
        based on available item types that contain "sandwich" in their display name.
        """
        try:
            # Get all category keywords and filter for sandwich-related types
            category_info = menu_cache.get_category_keyword_mapping("sandwich")
            if category_info and category_info.get("expands_to"):
                # Get display names for the expanded types
                subtypes = []
                for slug in category_info["expands_to"]:
                    subtype_info = menu_cache.get_category_keyword_mapping(slug)
                    if subtype_info:
                        display = subtype_info.get("display_name_plural") or subtype_info.get("display_name", slug)
                        subtypes.append(display)

                if subtypes:
                    if len(subtypes) <= 3:
                        return ", ".join(subtypes)
                    else:
                        return ", ".join(subtypes[:4]) + ", and more"
        except Exception as e:
            logger.warning("Failed to get sandwich subtypes from database: %s", e)

        # Fallback message
        return "egg sandwiches, fish sandwiches, cream cheese sandwiches, deli sandwiches, and more"

    def _get_category_subtypes_message(self, category_info: dict) -> str:
        """Build a message listing sub-types for any virtual category from database.

        Args:
            category_info: Category info dict with expands_to list of sub-category slugs.

        Returns a formatted string like "egg sandwiches, fish sandwiches, and more"
        based on the category's expanded types.
        """
        try:
            expands_to = category_info.get("expands_to", [])
            if expands_to:
                # Get display names for the expanded types
                subtypes = []
                for slug in expands_to:
                    subtype_info = menu_cache.get_category_keyword_mapping(slug)
                    if subtype_info:
                        display = subtype_info.get("display_name_plural") or subtype_info.get("display_name", slug)
                        subtypes.append(display)

                if subtypes:
                    if len(subtypes) <= 3:
                        return ", ".join(subtypes)
                    else:
                        return ", ".join(subtypes[:4]) + ", and more"
        except Exception as e:
            logger.warning("Failed to get category subtypes from database: %s", e)

        # Fallback - use the category's display name
        display_name = category_info.get("display_name_plural", category_info.get("display_name", "items"))
        return f"various {display_name}"

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

    def _get_items_for_category(self, menu_query_type: str) -> tuple[list, str]:
        """Get items and display name for a menu category.

        Uses DB-driven approach:
        1. Look up category in menu_cache.get_category_keyword_mapping()
        2. If found with expands_to, collect items from all those slugs
        3. If found with name_filter, filter items by that substring
        4. Otherwise, use the slug directly
        5. Fall back to partial string matching on all drinks

        Returns:
            Tuple of (items list, category_key for pagination)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # Look up category info from DB-loaded cache
        category_info = menu_cache.get_category_keyword_mapping(menu_query_type)

        if category_info:
            slug = category_info["slug"]
            expands_to = category_info.get("expands_to")
            name_filter = category_info.get("name_filter")

            if expands_to:
                # Meta-category: collect items from all expanded slugs
                all_items = []
                for target_slug in expands_to:
                    all_items.extend(items_by_type.get(target_slug, []))

                # Apply name_filter if present (e.g., for "tea" category)
                if name_filter:
                    filter_term = name_filter.lower()
                    all_items = [
                        item for item in all_items
                        if filter_term in item.get("name", "").lower()
                    ]

                return all_items, slug
            else:
                # Direct category: use the slug directly
                items = items_by_type.get(slug, [])

                # Apply name_filter if present
                if name_filter:
                    filter_term = name_filter.lower()
                    items = [
                        item for item in items
                        if filter_term in item.get("name", "").lower()
                    ]

                return items, slug

        # HYBRID APPROACH: For any other term, try partial string matching on all drinks
        # This handles "juice", "snapple", "mocha", "chai", "iced", etc.
        sized_items = items_by_type.get("sized_beverage", [])
        cold_items = items_by_type.get("beverage", [])
        all_drinks = sized_items + cold_items
        search_term = menu_query_type.lower()
        filtered = [
            item for item in all_drinks
            if search_term in item.get("name", "").lower()
        ]
        if filtered:
            return filtered, menu_query_type

        # No drink matches - fall back to checking other item types (bagels, etc.)
        return items_by_type.get(menu_query_type, []), menu_query_type

    def _format_items_list(
        self,
        items: list,
        offset: int,
        show_prices: bool,
        lookup_type: str,
    ) -> tuple[str, bool]:
        """Format a batch of items for display.

        Args:
            items: Full list of items
            offset: Starting index for this batch
            show_prices: Whether to include prices
            lookup_type: The item type (for price lookups)

        Returns:
            Tuple of (formatted string, has_more_items)
        """
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        if show_prices:
            item_list = []
            # Check if this item type uses attribute-based pricing (has "bread" attribute)
            item_type_attrs = menu_cache.get_item_type_attributes(lookup_type)
            uses_attribute_pricing = "bread" in item_type_attrs
            for item in batch:
                name = item.get('name', 'Unknown')
                if uses_attribute_pricing and self.pricing:
                    # Item type uses base + attribute upcharge pricing
                    # Extract the attribute value from the item name (e.g., "Plain Bagel" -> "plain")
                    attr_value = name.lower().replace(f" {lookup_type}", "").strip()
                    try:
                        base_price = self.pricing.lookup_base_price(lookup_type.title())
                        upcharge = self.pricing.lookup_attribute_option_upcharge(lookup_type, "bread", attr_value)
                        price = base_price + upcharge
                    except ValueError:
                        price = item.get('price') or item.get('base_price') or 0
                else:
                    price = item.get('price') or item.get('base_price') or 0
                item_list.append(f"{name} (${price:.2f})")
        else:
            item_list = [item.get("name", "Unknown") for item in batch]

        if has_more:
            item_list.append(f"...and {remaining} more")

        if len(item_list) == 1:
            return item_list[0], has_more
        elif len(item_list) == 2:
            return f"{item_list[0]} and {item_list[1]}", has_more
        else:
            return ", ".join(item_list[:-1]) + f", and {item_list[-1]}", has_more

    def handle_more_menu_items(self, order: OrderTask, category: str | None = None) -> StateMachineResult:
        """Handle 'show more' menu requests.

        Continues listing items from where the previous menu query left off.
        Supports both menu item categories, modifier categories (toppings, proteins, etc.),
        and ingredient search results.

        Args:
            order: The current order state
            category: Optional category extracted from "what other X" queries. If provided
                and there's no existing pagination, this triggers a fresh query for that category.
        """
        # Check for ingredient search pagination first
        ingredient_search = order.pending_ingredient_search
        if ingredient_search:
            return self._handle_more_ingredient_search_items(order, ingredient_search)

        pagination = order.get_menu_pagination()

        if not pagination:
            # No previous menu query - check if we have a category from "what other X"
            if category:
                # Treat as a fresh menu query for this category
                logger.info("MORE MENU ITEMS: No pagination, treating '%s' as fresh query", category)
                return self._handle_category_as_menu_query(category, order)

            # No category either - ask what they want to see more of
            return StateMachineResult(
                message="More of what? What would you like me to list?",
                order=order,
            )

        category = pagination.get("category")
        offset = pagination.get("offset", 0)
        total_items = pagination.get("total_items", 0)

        # Check if this is a modifier category (toppings, proteins, cheeses, spreads, milks, etc.)
        # Use data-driven lookup from modifier_categories table
        modifier_categories = menu_cache.get_modifier_categories_for_inquiry()

        if category in modifier_categories:
            # Use generic data-driven getter for modifier items
            get_items = lambda: menu_cache.get_modifier_category_items(category)
            return self._handle_more_modifier_items(category, get_items, offset, order)

        # Get items for this category (menu items)
        items, lookup_type = self._get_items_for_category(category)

        if not items or offset >= len(items):
            # No more items to show
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like to order anything?",
                order=order,
            )

        # Format the next batch
        items_str, has_more = self._format_items_list(items, offset, False, lookup_type)

        # Update pagination state
        new_offset = offset + DEFAULT_PAGINATION_SIZE
        if has_more:
            order.set_menu_pagination(category, new_offset, len(items))
        else:
            order.clear_menu_pagination()

        # Build response message
        if has_more:
            message = f"We also have: {items_str}. Would you like any of these?"
        else:
            message = f"We also have: {items_str}. That's all we have. Would you like any of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _handle_more_ingredient_search_items(
        self,
        order: OrderTask,
        ingredient_search: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for ingredient search results.

        Shows the next batch of items that contain the searched ingredient.
        """
        ingredient = ingredient_search.get("ingredient", "that ingredient")
        matches = ingredient_search.get("matches", [])
        offset = ingredient_search.get("offset", 0)

        if offset >= len(matches):
            # No more items to show
            order.pending_ingredient_search = None
            return StateMachineResult(
                message=f"That's all the items we have with {ingredient}. Which would you like?",
                order=order,
            )

        # Get next batch of items (show 6 at a time)
        batch_size = 6
        next_items = matches[offset:offset + batch_size]
        item_names = [m.get("name", "item") for m in next_items]
        remaining = len(matches) - (offset + len(next_items))

        # Format the list
        if len(item_names) == 1:
            items_list = item_names[0]
        elif len(item_names) == 2:
            items_list = f"{item_names[0]} and {item_names[1]}"
        else:
            items_list = ", ".join(item_names[:-1]) + f", and {item_names[-1]}"

        # Update or clear pagination state
        if remaining > 0:
            order.pending_ingredient_search = {
                "ingredient": ingredient,
                "matches": matches,
                "offset": offset + batch_size,
            }
            message = f"We also have: {items_list}, and {remaining} more. Which would you like?"
        else:
            order.pending_ingredient_search = None
            message = f"We also have: {items_list}. That's all the items with {ingredient}. Which would you like?"

        return StateMachineResult(
            message=message,
            order=order,
        )

    def _handle_category_as_menu_query(
        self,
        category: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle a category from 'what other X' as a fresh menu query.

        Uses data-driven ItemType aliases from the database to map category phrases
        to the appropriate menu type and handler.
        """
        category_lower = category.lower().strip()

        # Use data-driven lookup from ItemType aliases
        category_info = menu_cache.get_category_keyword_mapping(category_lower)

        if category_info:
            menu_type = category_info.get("slug")
            logger.info("Category '%s' mapped to menu type '%s' via database", category, menu_type)
            # Use signature menu handler for signature items
            if menu_type == "signature_items":
                return self.handle_signature_menu_inquiry(menu_type, order)
            # Use regular menu query handler for other types
            return self.handle_menu_query(menu_type, order)

        # Couldn't map to a known category - try a generic lookup
        logger.info("Category '%s' not in database aliases, trying generic lookup", category)
        return self.handle_menu_query(category_lower, order)

    def _handle_more_modifier_items(
        self,
        category: str,
        getter_fn: Callable,
        offset: int,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle 'show more' for modifier categories (toppings, proteins, etc.)."""
        try:
            items_set = getter_fn()
        except RuntimeError:
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like anything?",
                order=order,
            )

        if not items_set:
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like anything?",
                order=order,
            )

        # Normalize items (same logic as store_info_handler)
        items_list = self._normalize_modifier_items(items_set, category)

        if not items_list or offset >= len(items_list):
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like anything?",
                order=order,
            )

        # Get next batch
        batch = items_list[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items_list) - (offset + len(batch))
        has_more = remaining > 0

        # Format the list
        if has_more:
            if len(batch) == 1:
                items_str = batch[0]
            elif len(batch) == 2:
                items_str = f"{batch[0]}, {batch[1]}"
            else:
                items_str = ", ".join(batch)
            items_str += f", and {remaining} more"

            # Update pagination for next "what else"
            new_offset = offset + DEFAULT_PAGINATION_SIZE
            order.set_menu_pagination(category, new_offset, len(items_list))
        else:
            # Last batch
            if len(batch) == 1:
                items_str = batch[0]
            elif len(batch) == 2:
                items_str = f"{batch[0]} and {batch[1]}"
            else:
                items_str = ", ".join(batch[:-1]) + f", and {batch[-1]}"
            order.clear_menu_pagination()

        # Build response
        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            message = f"We also have {items_str}. That's all we have. Would you like any?"

        return StateMachineResult(message=message, order=order)

    def _normalize_modifier_items(self, items_set: set, category: str) -> list[str]:
        """Normalize and deduplicate modifier items for display.

        Removes plural variants, filters out very similar items,
        and returns a clean sorted list for user display.
        """
        seen_base = set()
        normalized = []

        for item in sorted(items_set):
            item_lower = item.lower()

            # Skip plural forms if singular exists
            if item_lower.endswith('s') and not item_lower.endswith('ss'):
                singular = item_lower.rstrip('s')
                if singular in seen_base:
                    continue

            # Skip "es" plural forms
            if item_lower.endswith('es'):
                singular = item_lower[:-2]
                if singular in seen_base:
                    continue

            # For cheeses category, filter out items that belong in spreads
            # Use data-driven category lookup to check if item is a spread
            category_info = menu_cache.get_category_keyword_mapping(category)
            is_cheese_category = category_info and category_info.get("slug") == "cheeses"
            if is_cheese_category:
                # Check if this item belongs in the spread category via database lookup
                item_category = menu_cache.get_ingredient_category(item_lower)
                if item_category == "spread":
                    continue

            # Track base form
            base = item_lower.rstrip('s')
            if base in seen_base:
                continue
            seen_base.add(base)
            seen_base.add(item_lower)

            # Capitalize for display
            normalized.append(item.title() if item.islower() else item)

        return normalized

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
            display_names = self.menu_data.get("item_type_display_names", {}) if self.menu_data else {}
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

        # Handle by-the-pound categories (spread, cream cheese, etc.)
        # Check if this category routes to by-pound handler via database
        category_info = menu_cache.get_category_keyword_mapping(menu_query_type)
        if category_info and category_info.get("is_by_pound"):
            category_slug = category_info.get("slug")
            if self._list_by_pound_category:
                return self._list_by_pound_category(category_slug, order)
            display_name = category_info.get("display_name_plural", "items")
            return StateMachineResult(
                message=f"We have various {display_name}. Would you like to hear about them?",
                order=order,
            )

        # Handle beverage queries - use category info from database
        if not category_info:
            category_info = menu_cache.get_category_keyword_mapping(menu_query_type)
        if category_info and menu_cache.get_modifier_category(category_info.get("slug", "")) == "beverage":
            items, category_key = self._get_items_for_category(menu_query_type)
            display_name = category_info.get("display_name_plural", "beverages")
            if items:
                items_str, has_more = self._format_items_list(items, 0, show_prices, category_key)
                # Save pagination state if there are more items
                if has_more:
                    order.set_menu_pagination(category_key, DEFAULT_PAGINATION_SIZE, len(items))
                else:
                    order.clear_menu_pagination()
                return StateMachineResult(
                    message=f"Our {display_name} include: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message=f"I don't have any {display_name} on the menu right now. Is there anything else I can help you with?",
                order=order,
            )

        # Handle virtual categories (those with expands_to) - too broad, need to ask what kind
        if not category_info:
            category_info = menu_cache.get_category_keyword_mapping(menu_query_type)
        if category_info and category_info.get("expands_to"):
            # Build sub-types message from database using the expanded types
            subtypes_message = self._get_category_subtypes_message(category_info)
            display_name = category_info.get("display_name", menu_query_type)
            return StateMachineResult(
                message=f"We have {subtypes_message}. What kind of {display_name} would you like?",
                order=order,
            )

        # Use helper method to get items for this category
        items, lookup_type = self._get_items_for_category(menu_query_type)

        if not items:
            # Try to suggest what we do have
            display_names = self.menu_data.get("item_type_display_names", {}) if self.menu_data else {}
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

        # Format the items list using helper method
        type_name = menu_query_type.replace("_", " ")
        # Proper pluralization - check if already plural first
        if type_name.endswith("s") and not type_name.endswith("ss"):
            type_display = type_name  # Already plural (e.g., "signature items")
        elif type_name.endswith("ch") or type_name.endswith("sh") or type_name.endswith("x"):
            type_display = type_name + "es"
        else:
            type_display = type_name + "s"

        items_str, has_more = self._format_items_list(items, 0, show_prices, lookup_type)

        # Save pagination state if there are more items
        if has_more:
            order.set_menu_pagination(menu_query_type, DEFAULT_PAGINATION_SIZE, len(items))
        else:
            order.clear_menu_pagination()

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            order=order,
        )

    def handle_soda_clarification(
        self,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle when user orders a generic 'soda' without specifying type.

        Asks what kind of soda they want, listing available options from the 'soda' category.
        """
        return self.handle_category_clarification("soda", order, fallback_message="Coke, Diet Coke, Sprite, and others")

    def handle_category_clarification(
        self,
        category_slug: str,
        order: OrderTask,
        fallback_message: str = "various options",
    ) -> StateMachineResult:
        """Handle when user orders a generic category without specifying type.

        Generic method that asks what kind of item they want, listing available
        options from the specified category.

        Args:
            category_slug: The category slug to look up items from (e.g., "soda", "tea")
            order: Current order state
            fallback_message: Message to show if no items found in category

        Returns:
            StateMachineResult asking for clarification with available options
        """
        # Get items from category-based lookup
        category_items = menu_cache.get_items_by_category(category_slug)

        if category_items:
            # Get just the names of a few items (max 6)
            item_names = [item.get("name", "") for item in category_items[:6]]
            # Filter out empty names and format nicely
            item_names = [name for name in item_names if name]
            if len(item_names) > 3:
                items_list = ", ".join(item_names[:3]) + ", and others"
            elif len(item_names) > 1:
                items_list = ", ".join(item_names[:-1]) + f", and {item_names[-1]}"
            else:
                items_list = item_names[0] if item_names else fallback_message

            return StateMachineResult(
                message=f"What kind? We have {items_list}.",
                order=order,
            )

        # Fallback if no items in category
        return StateMachineResult(
            message=f"What kind? We have {fallback_message}.",
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

        # Use data-driven lookup from ItemType aliases for category handling
        category_info = menu_cache.get_category_keyword_mapping(query_lower)

        # Handle virtual categories (those with expands_to) - too broad, need to ask what kind
        if category_info and category_info.get("expands_to"):
            subtypes_message = self._get_category_subtypes_message(category_info)
            display_name = category_info.get("display_name", query_lower)
            return StateMachineResult(
                message=f"We have {subtypes_message}. What kind of {display_name} would you like?",
                order=order,
            )
        if category_info and self.pricing:
            item_type = category_info.get("slug")
            display_name_plural = category_info.get("display_name_plural", f"{query_lower}s")
            min_price = self.pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name_plural} start at ${min_price:.2f}. Would you like one?",
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

        # Check for items that use attribute-based pricing (e.g., items with "bread" attribute)
        # These items may not have direct prices in items_by_type
        matched_item_type = None
        for item_type_slug in items_by_type.keys():
            item_type_attrs = menu_cache.get_item_type_attributes(item_type_slug)
            if "bread" in item_type_attrs and item_type_slug in query_lower:
                items_for_type = items_by_type.get(item_type_slug, [])
                if not best_match and items_for_type:
                    # Try to find a matching item
                    for item in items_for_type:
                        item_name = item.get("name", "").lower()
                        if query_lower in item_name or item_name in query_lower:
                            best_match = item
                            best_match_score = 75
                            matched_item_type = item_type_slug
                            break
                    # If they asked about a specific type but we didn't find it,
                    # give the general price if available
                    if not best_match and items_for_type:
                        best_match = items_for_type[0]
                        best_match_score = 50
                        matched_item_type = item_type_slug
                break

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
            # Check if item type uses attribute-based pricing (base + upcharge)
            item_type_slug = matched_item_type or best_match.get("item_type")
            if item_type_slug:
                item_type_attrs = menu_cache.get_item_type_attributes(item_type_slug)
                uses_attribute_pricing = "bread" in item_type_attrs
            else:
                uses_attribute_pricing = False

            if uses_attribute_pricing and item_type_slug and self.pricing:
                # Extract attribute value from name (e.g., "Plain Bagel" -> "plain")
                attr_value = name.lower().replace(f" {item_type_slug}", "").strip()
                try:
                    base_price = self.pricing.lookup_base_price(item_type_slug.title())
                    upcharge = self.pricing.lookup_attribute_option_upcharge(item_type_slug, "bread", attr_value)
                    price = base_price + upcharge
                except ValueError:
                    price = best_match.get("price") or best_match.get("base_price") or 0
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

        # Get item descriptions from menu_data (loaded from database)
        item_descriptions = self.menu_data.get("item_descriptions", {}) if self.menu_data else {}

        # Try to find an exact match or close match in descriptions
        description = item_descriptions.get(item_query_lower)

        if not description:
            # Try partial matching - look for item_query in keys
            for key, desc in item_descriptions.items():
                if item_query_lower in key or key in item_query_lower:
                    description = desc
                    break

        if not description:
            # Also search menu_data for item names and their descriptions
            if self.menu_data:
                items_by_type = self.menu_data.get("items_by_type", {})
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
            # Format with proper capitalization
            formatted_name = item_query.title()
            message = f"{formatted_name} has {description}. Would you like to order one?"

            # Store context so "yes" / "give me one" adds this item
            order.pending_suggested_item = formatted_name
            order.pending_field = "confirm_suggested_item"
        else:
            # Item not found - offer to help find it
            # Get available categories for a helpful suggestion
            available_categories = self._get_available_menu_categories_message()
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                f"Would you like me to tell you what {available_categories} we have?"
            )

        return StateMachineResult(message=message, order=order)

    def handle_signature_menu_inquiry(
        self,
        menu_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about signature menu items.

        Args:
            menu_type: Specific type like 'signature_items', 'egg_sandwich', or 'signature_item',
                      or None for all signature items
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # If a specific type is requested, look it up directly
        if menu_type:
            items = items_by_type.get(menu_type, [])
            category_key = menu_type
            # Get the display name from the type slug (proper pluralization)
            type_name = menu_type.replace("_", " ")
            # Check if already plural (ends with "s" but not "ss" like "grass")
            if type_name.endswith("s") and not type_name.endswith("ss"):
                type_display_name = type_name  # Already plural
            elif type_name.endswith("ch"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # No specific type - get all signature items
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
            if len(item_names) == 1:
                items_list = item_names[0]
            elif len(item_names) == 2:
                items_list = f"{item_names[0]} and {item_names[1]}"
            else:
                items_list = ", ".join(item_names[:-1]) + f", and {item_names[-1]}"

            order.clear_menu_pagination()

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )
