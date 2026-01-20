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
from typing import Callable, TYPE_CHECKING

from orderbot.menu_data_cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_item_type_display_name,
)
from .mixins import MenuDataMixin

if TYPE_CHECKING:
    from .handler_config import HandlerConfig

logger = logging.getLogger(__name__)

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)


class MenuInquiryHandler(MenuDataMixin):
    """
    Handles menu-related inquiries.

    Manages menu listings, price inquiries, item descriptions, and signature menu queries.
    """

    # Note: ITEM_DESCRIPTIONS has been moved to the database (menu_items.description column)
    # Item descriptions are now loaded via menu_data["item_descriptions"]

    def __init__(
        self,
        config: "HandlerConfig",
    ):
        """
        Initialize the menu inquiry handler.

        Args:
            config: HandlerConfig with shared dependencies.
        """
        self._menu_data = config.menu_data or {}
        self.pricing = config.pricing

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
        return "our menu items"

    def _get_items_for_category(self, menu_query_type: str) -> tuple[list, str]:
        """Get items and display name for a menu category.

        Uses DB-driven approach with lookup_type:
        1. Look up category in menu_cache.get_category_keyword_mapping()
        2. If lookup_type=="category", query via MenuItemCategory join table
        3. If lookup_type=="item_type", query by item_type_id
        4. Fall back to partial string matching on all drinks

        Returns:
            Tuple of (items list, category_key for pagination)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # Look up category info from DB-loaded cache
        category_info = menu_cache.get_category_keyword_mapping(menu_query_type)

        if category_info:
            slug = category_info["slug"]
            lookup_type = category_info.get("lookup_type", "item_type")

            if lookup_type == "category":
                # Query via MenuItemCategory join table
                items = menu_cache.get_items_by_category(slug)
                return items, slug
            else:
                # Query by item_type_id
                items = items_by_type.get(slug, [])
                return items, slug

        # FALLBACK: For unrecognized terms, try partial string matching on ALL menu items
        # This handles "juice", "snapple", "mocha", "chai", etc. without hardcoding item types
        all_items = []
        for item_type_items in items_by_type.values():
            all_items.extend(item_type_items)
        search_term = menu_query_type.lower()
        filtered = [
            item for item in all_items
            if search_term in item.get("name", "").lower()
        ]
        if filtered:
            return filtered, menu_query_type

        # No matches found
        return [], menu_query_type

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
            for item in batch:
                name = item.get('name', 'Unknown')
                # Use pre-computed resolved price from menu_cache
                price = menu_cache.get_resolved_item_price(name)
                if price is None:
                    # Fall back to item's own price fields
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

    def handle_category_clarification(
        self,
        category_slug: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle when user orders a generic category without specifying type.

        Generic method that asks what kind of item they want, listing available
        options from the specified category.

        Args:
            category_slug: The category slug to look up items from (e.g., "soda", "tea")
            order: Current order state

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
            elif item_names:
                items_list = item_names[0]
            else:
                # No valid item names - generic response
                return StateMachineResult(
                    message="I don't have that available right now. What else can I get you?",
                    order=order,
                )

            return StateMachineResult(
                message=f"What kind? We have {items_list}.",
                order=order,
            )

        # No items in category - generic response
        return StateMachineResult(
            message="I don't have that available right now. What else can I get you?",
            order=order,
        )

    def handle_price_inquiry(
        self,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle price inquiry for a specific item.

        Uses the data-driven resolve_price_inquiry() method from menu_cache
        to look up prices for items, categories, and modifiers.

        Args:
            item_query: The item the user is asking about (e.g., 'sesame bagel', 'lox')
            order: Current order state

        Returns:
            StateMachineResult with the price information
        """
        if not item_query:
            return StateMachineResult(
                message="What would you like to know the price of?",
                order=order,
            )

        # Extract context from order state
        current_item_type = None
        pending_item = order.get_pending_item() if hasattr(order, 'get_pending_item') else None
        if pending_item:
            current_item_type = getattr(pending_item, 'menu_item_type', None)

        last_menu_category = None
        pagination = order.get_menu_pagination() if hasattr(order, 'get_menu_pagination') else None
        if pagination:
            last_menu_category = pagination.get("category")

        # Use the unified data-driven lookup
        context = {
            "current_item_type": current_item_type,
            "last_menu_category": last_menu_category,
        }
        result = menu_cache.resolve_price_inquiry(query=item_query, context=context)

        result_type = result.get("type")

        if result_type == "category":
            display_name = result.get("display_name", item_query)
            min_price = result.get("min_price", 0)
            items = result.get("items", [])

            # If there are multiple named items in the category, ask which kind
            if items and len(items) > 1:
                # Show a few examples
                examples = items[:3]
                examples_str = ", ".join(examples)
                return StateMachineResult(
                    message=f"We have several kinds of {display_name} including {examples_str}. What kind of {display_name.rstrip('s')} would you like?",
                    order=order,
                )

            return StateMachineResult(
                message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                order=order,
            )

        if result_type == "item":
            name = result.get("name", item_query)
            price = result.get("price", 0)
            return StateMachineResult(
                message=f"{name} is ${price:.2f}. Would you like one?",
                order=order,
            )

        if result_type == "sized_item":
            name = result.get("name", item_query)
            sizes = result.get("sizes", [])
            if sizes:
                # Format size options
                size_strs = [
                    f"{s.get('size_name', 'Unknown')} ${s.get('price', 0):.2f}"
                    for s in sizes
                ]
                sizes_text = ", ".join(size_strs)
                return StateMachineResult(
                    message=f"{name} comes in: {sizes_text}. What size would you like?",
                    order=order,
                )
            # Fallback if no sizes (shouldn't happen)
            return StateMachineResult(
                message=f"{name} pricing varies by size. What size would you like?",
                order=order,
            )

        if result_type == "modifier":
            name = result.get("name", item_query)
            price = result.get("price", 0)
            context = result.get("context", "")
            if price > 0:
                return StateMachineResult(
                    message=f"{name} is ${price:.2f} as a {context}. Would you like to add it?",
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=f"{name} is included at no extra charge. Would you like to add it?",
                    order=order,
                )

        if result_type == "needs_clarification":
            name = result.get("name", item_query)
            contexts = result.get("contexts", [])
            # Format the options for clarification
            options = []
            for ctx in contexts:
                label = ctx.get("label", "")
                price = ctx.get("price", 0)
                if price > 0:
                    options.append(f"{label} (${price:.2f})")
                else:
                    options.append(f"{label} (included)")

            if len(options) == 2:
                options_text = f"{options[0]} or {options[1]}"
            else:
                options_text = ", ".join(options[:-1]) + f", or {options[-1]}"

            return StateMachineResult(
                message=f"Are you asking about {name} as {options_text}?",
                order=order,
            )

        # result_type == "not_found"
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
