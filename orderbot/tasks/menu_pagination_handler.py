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
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from .models import OrderTask
from .models.pending_states import PendingIngredientSearch
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .mixins import MenuDataMixin
from .utils.text import format_english_list, normalize_text

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
                return self._handle_category_as_menu_query(category, order)

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
            return self._handle_more_item_types(order, pagination)

        # Handle attribute_options pagination (from "what bagel types?" response)
        if pagination.get("type") == "attribute_options":
            return self._handle_more_attribute_options(order, pagination)

        # Handle dietary_items pagination (from "what vegan options?" response)
        if pagination.get("type") == "dietary_items":
            return self._handle_more_dietary_items(order, pagination)

        # Handle display_group_items pagination (from "can I get a sandwich?" response)
        if pagination.get("type") == "display_group_items":
            return self._handle_more_display_group_items(order, pagination)

        # Handle availability_items pagination (from "do you have X?" response)
        if pagination.get("type") == "availability_items":
            return self._handle_more_availability_items(order, pagination)

        category = pagination.get("category")
        offset = pagination.get("offset", 0)

        # Try to get menu items for this category
        items, lookup_type = self._get_items_for_category(category)

        # If no menu items found, check if this is a modifier category
        if not items:
            modifier_categories = menu_cache.get_modifier_categories_for_inquiry()
            if category in modifier_categories:
                # Use generic data-driven getter for modifier items
                get_items = lambda: menu_cache.get_modifier_category_items(category)
                return self._handle_more_modifier_items(category, get_items, offset, order)

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

    def _handle_more_ingredient_search_items(
        self,
        order: OrderTask,
        ingredient_search: "PendingIngredientSearch",
    ) -> StateMachineResult:
        """Handle 'show more' for ingredient search results.

        Shows the next batch of items that contain the searched ingredient.
        """
        ingredient = ingredient_search.ingredient
        matches = ingredient_search.matches
        offset = ingredient_search.offset

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
        items_list = format_english_list(item_names)
        has_more = remaining > 0

        # Update or clear pagination state
        if has_more:
            order.pending_ingredient_search = PendingIngredientSearch(
                ingredient=ingredient,
                matches=matches,
                offset=offset + batch_size,
            )
            message = f"We also have: {items_list}, and {remaining} more. Which would you like?"
        else:
            order.pending_ingredient_search = None
            message = f"We also have: {items_list}. That's all the items with {ingredient}. Which would you like?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in item_names]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr,
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
        category_lower = normalize_text(category)

        # Use data-driven lookup from ItemType aliases
        category_info = menu_cache.get_category_keyword_mapping(category_lower)

        if category_info:
            menu_type = category_info.get("slug")
            logger.info("Category '%s' mapped to menu type '%s' via database", category, menu_type)
            # Delegate to menu_inquiry_handler for actual query handling
            if self.menu_inquiry_handler:
                if menu_type == "signature_items":
                    return self.menu_inquiry_handler.handle_signature_menu_inquiry(menu_type, order)
                return self.menu_inquiry_handler.handle_menu_query(menu_type, order)

        # Couldn't map to a known category - try a generic lookup
        logger.info("Category '%s' not in database aliases, trying generic lookup", category)
        if self.menu_inquiry_handler:
            return self.menu_inquiry_handler.handle_menu_query(category_lower, order)

        # Fallback if no menu_inquiry_handler
        return StateMachineResult(
            message=f"I'm not sure what {category} items we have. What else can I help you with?",
            order=order,
        )

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
            items_str = format_english_list(batch)
            order.clear_menu_pagination()

        # Build response
        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            message = f"We also have {items_str}. That's all we have. Would you like any?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _handle_more_item_types(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for item type suggestions (from 'what do you recommend?').

        Args:
            order: Current order state
            pagination: Pagination dict with "items" list and "offset"
        """
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's everything we have. What would you like to order?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
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
            order.menu_query_pagination = {
                "type": "item_types",
                "items": items,
                "offset": new_offset,
            }
        else:
            # Last batch
            items_str = format_english_list(batch)
            order.clear_menu_pagination()

        # Build response
        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            message = f"We also have {items_str}. That's everything! What would you like?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": f"What {name.lower()} do you have?"} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _handle_more_attribute_options(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for attribute options (from 'what bagel types?' response).

        Args:
            order: Current order state
            pagination: Pagination dict with "items" list, "offset", and attribute context
        """
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        attr_display = pagination.get("attribute_display", "options")
        item_type = pagination.get("item_type")

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(
                message=f"That's all the {attr_display} we have. Would you like to order something?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
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
            order.menu_query_pagination = {
                "type": "attribute_options",
                "attribute_slug": pagination.get("attribute_slug"),
                "attribute_display": attr_display,
                "item_type": item_type,
                "items": items,
                "offset": new_offset,
            }
        else:
            # Last batch
            items_str = format_english_list(batch)
            order.clear_menu_pagination()

        # Build response
        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            message = f"We also have {items_str}. That's all the {attr_display} we have. Would you like any?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _handle_more_dietary_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for dietary item results (from 'what vegan options?' response).

        Args:
            order: Current order state
            pagination: Pagination dict with "items" list, "offset", and dietary context
        """
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        dietary_display = pagination.get("dietary_display", "dietary")
        category = pagination.get("category")

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            category_suffix = f" {category}" if category else " options"
            return StateMachineResult(
                message=f"That's all the {dietary_display}{category_suffix} we have. Would you like to order something?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
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
            order.menu_query_pagination = {
                "type": "dietary_items",
                "dietary_type": pagination.get("dietary_type"),
                "dietary_display": dietary_display,
                "category": category,
                "items": items,
                "offset": new_offset,
            }
        else:
            # Last batch
            items_str = format_english_list(batch)
            order.clear_menu_pagination()

        # Build response
        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            category_suffix = f" {category}" if category else " options"
            message = f"We also have {items_str}. That's all the {dietary_display}{category_suffix} we have. Would you like any?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _handle_more_availability_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for availability inquiry results.

        Args:
            order: Current order state
            pagination: Pagination dict with "items" list and "offset"
        """
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's everything we have. Would you like to order something?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        if has_more:
            items_str = ", ".join(batch) + f", and {remaining} more"
            order.menu_query_pagination = {
                "type": "availability_items",
                "items": items,
                "offset": offset + DEFAULT_PAGINATION_SIZE,
            }
        else:
            items_str = format_english_list(batch)
            order.clear_menu_pagination()

        if has_more:
            message = f"We also have {items_str}. Would you like any of these?"
        else:
            message = f"We also have {items_str}. That's all we have. Would you like any of these?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _handle_more_display_group_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for display group items (from 'can I get a sandwich?' response).

        Args:
            order: Current order state
            pagination: Pagination dict with "items" list, "offset", and "display_group"
        """
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        display_group = pagination.get("display_group", "items")

        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(
                message="That's all we have. Would you like to order something?",
                order=order,
            )

        # Get next batch
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        # Format the list
        items_str = format_english_list(batch, conjunction="or")

        if has_more:
            # Update pagination for next "what else"
            new_offset = offset + DEFAULT_PAGINATION_SIZE
            order.menu_query_pagination = {
                "type": "display_group_items",
                "display_group": display_group,
                "items": items,
                "offset": new_offset,
            }
            message = f"We also have {items_str}, and {remaining} more. Would you like any of these?"
        else:
            order.clear_menu_pagination()
            message = f"We also have {items_str}. That's all we have. Would you like any of these?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

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
