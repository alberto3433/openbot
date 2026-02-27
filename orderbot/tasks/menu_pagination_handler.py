"""
Menu Pagination Handler for Order State Machine.

This module handles pagination for menu-related queries including:
- "Show more" / "What else" requests
- Ingredient search result pagination
- Modifier category pagination
- Item type pagination
- Attribute options pagination

Extracted from menu_inquiry_handler.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .mixins import MenuDataMixin
from .pagination_content_handlers import PaginationContentHandlers
from .utils.text import format_english_list

if TYPE_CHECKING:
    from .menu_inquiry_handler import MenuInquiryHandler

logger = logging.getLogger(__name__)


class MenuPaginationHandler(MenuDataMixin):
    """
    Handles pagination for menu-related queries.

    Manages "show more" requests for menu items, modifiers, item types,
    and attribute options.
    """

    def __init__(
        self,
        menu_data: dict | None = None,
        menu_inquiry_handler: "MenuInquiryHandler | None" = None,
    ):
        """
        Initialize the menu pagination handler.

        Args:
            menu_data: Shared menu data dictionary.
            menu_inquiry_handler: Reference to MenuInquiryHandler for delegation.
        """
        self._menu_data = menu_data or {}
        self.menu_inquiry_handler = menu_inquiry_handler
        self._content = PaginationContentHandlers(self)

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
            return self._content._handle_more_ingredient_search_items(order, ingredient_search)

        pagination = order.get_menu_pagination()

        if not pagination:
            # No previous menu query - check if we have a category from "what other X"
            if category:
                # Treat as a fresh menu query for this category
                return self._content._handle_category_as_menu_query(category, order)

            # No category either - treat as a general menu query
            # "what else do you have?" without context means show the general menu
            if self.menu_inquiry_handler:
                return self.menu_inquiry_handler.handle_menu_query(None, order)

            # Fallback if no menu_inquiry_handler
            return StateMachineResult(
                message="What would you like to know more about?",
                order=order,
            )

        # Handle item_types pagination (from "what do you recommend?" response)
        if pagination.get("type") == "item_types":
            return self._content._handle_more_item_types(order, pagination)

        # Handle attribute_options pagination (from "what bagel types?" response)
        if pagination.get("type") == "attribute_options":
            return self._content._handle_more_attribute_options(order, pagination)

        # Handle dietary_items pagination (from "what vegan options?" response)
        if pagination.get("type") == "dietary_items":
            return self._content._handle_more_dietary_items(order, pagination)

        # Handle display_group_subgroups pagination (from "what drinks?" with sub-groups)
        if pagination.get("type") == "display_group_subgroups":
            return self._content._handle_more_display_group_subgroups(order, pagination)

        # Handle display_group_items pagination (from "can I get a sandwich?" response)
        if pagination.get("type") == "display_group_items":
            return self._content._handle_more_display_group_items(order, pagination)

        # Handle availability_items pagination (from "do you have X?" response)
        if pagination.get("type") == "availability_items":
            return self._content._handle_more_availability_items(order, pagination)

        category = pagination.get("category")
        offset = pagination.get("offset", 0)

        # Check modifier categories FIRST (more specific than display groups)
        # A category like "spread" can match both a modifier category and a display group;
        # if pagination was set by a modifier inquiry, we want modifier items, not display group items
        modifier_categories = menu_cache.get_modifier_categories_for_inquiry()
        if category in modifier_categories:
            get_items = lambda: menu_cache.get_modifier_category_items(category)
            return self._content._handle_more_modifier_items(category, get_items, offset, order)

        # Try to get menu items for this category (display groups, item types, etc.)
        items, lookup_type = self._get_items_for_category(category)

        if not items or offset >= len(items):
            # No more items to show
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like to order anything?",
                order=order,
            )

        # Format the next batch
        items_str, has_more, batch_names = self._format_items_list(items, offset, False, lookup_type)

        # Update pagination state
        new_offset = offset + DEFAULT_PAGINATION_SIZE
        remaining = len(items) - (offset + len(batch_names))
        if has_more:
            order.set_menu_pagination(category, new_offset, len(items))
        else:
            order.clear_menu_pagination()

        # Build response message
        if has_more:
            message = f"We also have: {items_str}. Would you like any of these?"
        else:
            message = f"We also have: {items_str}. That's all we have. Would you like any of these?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch_names]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr,
        )

    def _normalize_modifier_items(self, items_set: set, category: str) -> list[str]:
        """Normalize and deduplicate modifier items for display.

        Removes plural variants, filters out very similar items,
        and returns a clean sorted list for user display.

        Uses centralized singularize function from cache/base.py for proper
        handling of irregular plurals.
        """
        seen_base = set()
        normalized = []

        for item in sorted(items_set):
            item_lower = item.lower()

            # Get the singular form using the centralized function
            singular = singularize(item_lower)

            # Skip if we've seen this base form
            if singular in seen_base:
                continue

            # Track both forms
            seen_base.add(singular)
            seen_base.add(item_lower)

            # Capitalize for display
            normalized.append(item.title() if item.islower() else item)

        return normalized

    def _get_items_for_category(self, menu_query_type: str) -> tuple[list, str]:
        """Get items and display name for a menu category.

        Delegates to menu_inquiry_handler if available, otherwise uses local lookup.

        Returns:
            Tuple of (items list, category_key for pagination)
        """
        if self.menu_inquiry_handler:
            return self.menu_inquiry_handler._get_items_for_category(menu_query_type)

        # Fallback: simple items_by_type lookup
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        if menu_query_type in items_by_type:
            return items_by_type[menu_query_type], menu_query_type
        return [], menu_query_type

    def _format_items_list(
        self,
        items: list,
        offset: int,
        show_prices: bool,
        lookup_type: str,
    ) -> tuple[str, bool, list[str]]:
        """Format a batch of items for display.

        Delegates to menu_inquiry_handler if available.

        Args:
            items: Full list of items
            offset: Starting index for this batch
            show_prices: Whether to include prices
            lookup_type: The item type (for price lookups)

        Returns:
            Tuple of (formatted string, has_more_items, raw_item_names)
        """
        if self.menu_inquiry_handler:
            return self.menu_inquiry_handler._format_items_list(items, offset, show_prices, lookup_type)

        # Fallback: simple formatting
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        item_list = [item.get("name", "Unknown") for item in batch]
        raw_names = list(item_list)
        if has_more:
            item_list.append(f"...and {remaining} more")

        return format_english_list(item_list), has_more, raw_names
