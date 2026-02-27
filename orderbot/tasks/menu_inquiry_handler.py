"""
Menu Inquiry Handler for Order State Machine.

This module handles menu-related inquiries including:
- Menu listings by type (beverages, sandwiches, etc.)
- Price inquiries for specific items
- Item description questions
- Signature/speed menu inquiries
- Soda clarification

Pagination ("show more" requests) is delegated to MenuPaginationHandler.

Extracted from state_machine.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import pluralize, singularize

from .models import OrderTask
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .parsers.constants import (
    DEFAULT_PAGINATION_SIZE,
    get_item_type_display_name,
)
from .handler_config import BaseHandler
from .utils.text import format_english_list, normalize_text
from .price_inquiry_handler import PriceInquiryHandler
from .category_resolver import (
    get_available_menu_categories_message,
    find_matching_item_types,
    get_items_for_category,
)
from .menu_display_handler import MenuDisplayHandler

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .menu_pagination_handler import MenuPaginationHandler

logger = logging.getLogger(__name__)

# NOTE: Pagination uses DEFAULT_PAGINATION_SIZE from parsers.constants (uniform at 5)


class MenuInquiryHandler(BaseHandler):
    """
    Handles menu-related inquiries.

    Manages menu listings, price inquiries, item descriptions, and signature menu queries.
    """

    # Note: ITEM_DESCRIPTIONS has been moved to the database (menu_items.description column)
    # Item descriptions are now loaded via menu_data["item_descriptions"]

    def __init__(
        self,
        config: "HandlerConfig",
        pagination_handler: "MenuPaginationHandler | None" = None,
    ):
        """
        Initialize the menu inquiry handler.

        Args:
            config: HandlerConfig with shared dependencies.
            pagination_handler: Handler for pagination ("show more") requests.
        """
        super().__init__(config)
        self._price_inquiry_handler = PriceInquiryHandler()
        self.pagination_handler = pagination_handler
        self._display_handler = MenuDisplayHandler(self)

    def _get_available_menu_categories_message(self) -> str:
        return get_available_menu_categories_message()

    def _find_matching_item_types(self, query: str, items_by_type: dict) -> list[str]:
        return find_matching_item_types(query, items_by_type)

    def _get_items_for_category(self, menu_query_type: str) -> tuple[list, str]:
        return get_items_for_category(menu_query_type, self.menu_data)

    def _format_items_list(
        self,
        items: list,
        offset: int,
        show_prices: bool,
        lookup_type: str,
    ) -> tuple[str, bool, list[str]]:
        """Format a batch of items for display.

        Args:
            items: Full list of items
            offset: Starting index for this batch
            show_prices: Whether to include prices
            lookup_type: The item type (for price lookups)

        Returns:
            Tuple of (formatted string, has_more_items, raw_item_names)
        """
        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        raw_names = [item.get("name", "Unknown") for item in batch]

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
            item_list = list(raw_names)

        if has_more:
            # Don't use format_english_list when there's a "more" indicator
            # to avoid "X, and ...and N more" redundancy
            formatted = ", ".join(item_list) + f", and {remaining} more"
            return formatted, has_more, raw_names

        return format_english_list(item_list), has_more, raw_names

    def _format_attribute_options_list(
        self,
        option_names: list[str],
        display_name: str,
        category_slug: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format a global attribute or modifier category options list with pagination.

        Args:
            option_names: Sorted list of option display names.
            display_name: Human-readable category name (e.g., "Condiments").
            category_slug: Slug for pagination state tracking.
            order: Current order state.

        Returns:
            StateMachineResult with formatted message and quick replies.
        """
        if len(option_names) <= DEFAULT_PAGINATION_SIZE:
            items_str = format_english_list(option_names)
            order.clear_menu_pagination()
            batch = option_names
        else:
            batch = option_names[:DEFAULT_PAGINATION_SIZE]
            items_str = format_english_list(batch)
            remaining = len(option_names) - DEFAULT_PAGINATION_SIZE
            order.set_menu_pagination(category_slug, DEFAULT_PAGINATION_SIZE, len(option_names))

        qr = [{"label": name, "value": name} for name in batch]

        if len(option_names) > DEFAULT_PAGINATION_SIZE:
            remaining = len(option_names) - DEFAULT_PAGINATION_SIZE
            items_str += f", and {remaining} more"
            qr.append({"label": f"{remaining} more", "value": "what else?"})
            message = (
                f"For {display_name.lower()}, we have {items_str} — "
                f"would you like one of these, or want to hear more?"
            )
        else:
            message = (
                f"For {display_name.lower()}, we have {items_str}. "
                f"Would you like any of these?"
            )

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    def _format_sub_groups_response(
        self,
        child_groups: list[dict],
        parent_slug: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format a response listing sub-groups instead of individual items.

        When a display group has children (e.g., "drinks" -> Coffee, Tea, Soda),
        show the sub-group names so the user can drill down.

        Args:
            child_groups: List of child display group dicts (from cache).
            parent_slug: The parent display group slug (e.g., "drinks").
            order: Current order state.

        Returns:
            StateMachineResult with sub-group listing and quick replies.
        """
        group_names = [g["display_name"] for g in child_groups]

        if len(group_names) <= DEFAULT_PAGINATION_SIZE:
            names_str = format_english_list(group_names)
            batch = group_names
            order.clear_menu_pagination()
        else:
            batch = group_names[:DEFAULT_PAGINATION_SIZE]
            remaining = len(group_names) - DEFAULT_PAGINATION_SIZE
            names_str = ", ".join(batch) + f", and {remaining} more"
            order.menu_query_pagination = {
                "type": "display_group_subgroups",
                "parent_slug": parent_slug,
                "items": group_names,
                "offset": DEFAULT_PAGINATION_SIZE,
            }

        parent_display = parent_slug.replace("_", " ")

        qr = [
            {"label": name, "value": f"What {name.lower()} do you have?"}
            for name in batch
        ]
        if len(group_names) > DEFAULT_PAGINATION_SIZE:
            remaining = len(group_names) - DEFAULT_PAGINATION_SIZE
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=f"For {parent_display}, we have {names_str}. Which type are you interested in?",
            order=order,
            quick_replies=qr,
        )

    def handle_more_menu_items(self, order: OrderTask, category: str | None = None) -> StateMachineResult:
        """Handle 'show more' menu requests.

        Delegates to pagination_handler for actual pagination logic.
        This method is kept for backward compatibility.

        Args:
            order: The current order state
            category: Optional category extracted from "what other X" queries.
        """
        if self.pagination_handler:
            return self.pagination_handler.handle_more_menu_items(order, category)

        # Fallback if no pagination handler
        return StateMachineResult(
            message="More of what? What would you like me to list?",
            order=order,
        )

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
            # Generic "what do you have?" - list a few display groups conversationally
            display_groups = menu_cache.get_menu_display_groups()
            if display_groups:
                # Show only first few categories to avoid overwhelming the user
                max_categories_to_show = 5
                group_names = [g["display_name"] for g in display_groups]
                shown_names = group_names[:max_categories_to_show]

                has_more = len(group_names) > max_categories_to_show
                if has_more:
                    # More categories than we're showing
                    categories_text = format_english_list(shown_names) + ", and more"
                    # Save pagination state for "what else" follow-ups
                    order.menu_query_pagination = {
                        "type": "item_types",
                        "items": group_names,
                        "offset": max_categories_to_show,
                    }
                else:
                    categories_text = format_english_list(shown_names)
                    order.clear_menu_pagination()

                # Build quick replies for inline clickable text
                # Clicking a category sends a natural question like "What sandwiches do you have?"
                qr = [{"label": name, "value": f"What {name.lower()} do you have?"} for name in shown_names]
                qr.append({"label": "selection", "value": "", "url": "/static/menu.html"})
                if has_more:
                    qr.append({"label": "more", "value": "what else?"})

                return StateMachineResult(
                    message=f"We have a great selection! We have {categories_text} — what are you in the mood for?",
                    order=order,
                    quick_replies=qr,
                )
            # Fallback if no display groups configured - use generic message
            return StateMachineResult(
                message="What can I get for you?",
                order=order,
            )

        # Use helper method to get items for this category
        items, lookup_type = self._get_items_for_category(menu_query_type)

        if not items:
            # Fallback 1: check if query matches a global attribute (e.g., "condiments")
            attr_slug = singularize(normalize_text(menu_query_type))
            global_options = menu_cache.get_global_attribute_options(attr_slug)
            if global_options:
                option_names = sorted([
                    opt.get("display_name", opt.get("slug", ""))
                    for opt in global_options
                    if opt.get("is_available", True)
                ])
                if option_names:
                    attr_display = menu_cache.get_attribute_display_name(attr_slug)
                    return self._format_attribute_options_list(
                        option_names, attr_display, attr_slug, order
                    )

            # Fallback 2: check modifier categories by alias
            modifier_slug = menu_cache.get_modifier_category_by_alias(menu_query_type)
            if modifier_slug:
                modifier_items = menu_cache.get_modifier_category_items(modifier_slug)
                if modifier_items:
                    items_list = sorted(modifier_items)
                    cat_info = menu_cache.get_modifier_categories_for_inquiry().get(
                        modifier_slug, {}
                    )
                    display_name = cat_info.get(
                        "display_name", modifier_slug.replace("_", " ").title()
                    )
                    return self._format_attribute_options_list(
                        items_list, display_name, modifier_slug, order
                    )

            # Try to suggest what we do have using high-level display groups
            display_names = self.menu_data.get("item_type_display_names", {}) if self.menu_data else {}
            type_display = get_item_type_display_name(menu_query_type, display_names)

            # Use display groups for cleaner suggestions
            display_groups = menu_cache.get_menu_display_groups()
            if display_groups:
                # Show only first few categories to avoid overwhelming the user
                max_categories_to_show = 5
                group_names = [g["display_name"] for g in display_groups]
                shown_names = group_names[:max_categories_to_show]
                if len(group_names) > max_categories_to_show:
                    categories_text = format_english_list(shown_names) + ", and more"
                else:
                    categories_text = format_english_list(shown_names)
                qr = [{"label": name, "value": f"What {name.lower()} do you have?"} for name in shown_names]
                if len(group_names) > max_categories_to_show:
                    qr.append({"label": "more", "value": "what else?"})
                return StateMachineResult(
                    message=f"We don't have {type_display}, but we do have {categories_text} — what are you in the mood for?",
                    order=order,
                    quick_replies=qr,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display} on the menu. What else can I help you with?",
                order=order,
            )

        # Before listing items flat, check if the lookup_type has sub-groups
        # e.g., "drinks" has children Coffee, Tea, Soda, etc.
        child_groups = menu_cache.get_child_display_groups(lookup_type)
        if child_groups and not show_prices:
            return self._format_sub_groups_response(child_groups, lookup_type, order)

        # Format the items list using helper method
        # Use lookup_type (canonical item type slug) for display, not menu_query_type (user input)
        # This avoids double-pluralization (e.g., "teas" -> "teass")
        type_name = lookup_type.replace("_", " ")
        # Use proper pluralization via inflect library
        type_display = pluralize(type_name)

        items_str, has_more, batch_names = self._format_items_list(items, 0, show_prices, lookup_type)

        # Save pagination state if there are more items
        remaining = len(items) - DEFAULT_PAGINATION_SIZE
        if has_more:
            order.set_menu_pagination(menu_query_type, DEFAULT_PAGINATION_SIZE, len(items))
        else:
            order.clear_menu_pagination()

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in batch_names]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        # Store shown items so vague replies ("I'll take some") route through
        # handle_item_selection instead of being parsed as a new item search.
        batch_items = items[:DEFAULT_PAGINATION_SIZE]
        order.pending_item_options = batch_items
        order.pending_field = PendingField.ITEM_SELECTION

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            order=order,
            quick_replies=qr,
        )

    def handle_category_clarification(
        self,
        category_slug: str,
        order: OrderTask,
    ) -> StateMachineResult | str:
        """Handle when user orders a generic category without specifying type.

        Generic method that asks what kind of item they want, listing available
        options from the specified category. Returns a str (item name) when
        exactly one item matches after filtering, so the caller can add it
        directly to the cart.

        Args:
            category_slug: The category slug to look up items from (e.g., "soda", "tea",
                          or display group aliases like "pastry", "desserts")
            order: Current order state

        Returns:
            StateMachineResult asking for clarification with available options
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        category_items = []
        pagination_key = category_slug

        # First, check if this matches a display group (or alias like "pastry" -> "desserts_pastries")
        display_group = menu_cache.get_display_group_by_slug(category_slug)
        if display_group:
            # Check for child sub-groups before listing items flat
            child_groups = menu_cache.get_child_display_groups(display_group["slug"])
            if child_groups:
                return self._format_sub_groups_response(
                    child_groups, display_group["slug"], order
                )

            item_type_slugs = menu_cache.get_item_types_in_display_group(display_group["slug"])
            if item_type_slugs:
                # Collect items from all item types in this display group
                for item_type_slug in item_type_slugs:
                    category_items.extend(items_by_type.get(item_type_slug, []))
                pagination_key = display_group["slug"]
                logger.info(
                    "Category clarification: '%s' matched display group '%s' with %d items",
                    category_slug, display_group["slug"], len(category_items)
                )

        # Fall back to category-based lookup (MenuItemCategory junction table)
        if not category_items:
            category_items = menu_cache.get_items_by_category(category_slug)

        # Filter out items whose required_match_phrases don't match the category term
        if category_items:
            filtered_items = []
            for item in category_items:
                required_phrases = item.get("required_match_phrases")
                if not required_phrases:
                    filtered_items.append(item)
                    continue
                phrases = [normalize_text(p) for p in required_phrases.split(",") if p.strip()]
                if any(phrase in category_slug.lower() for phrase in phrases):
                    filtered_items.append(item)
            category_items = filtered_items

        if category_items:
            # Get all item names, filter out empty
            all_item_names = [item.get("name", "") for item in category_items]
            all_item_names = [name for name in all_item_names if name]

            if not all_item_names:
                # No valid item names - generic response
                return StateMachineResult(
                    message="I don't have that available right now. What else can I get you?",
                    order=order,
                )

            if len(all_item_names) == 1:
                # Single item in category - return name for direct addition
                logger.info(
                    "Category clarification: single item '%s' after filtering, adding directly",
                    all_item_names[0],
                )
                return all_item_names[0]

            # Paginate: show only DEFAULT_PAGINATION_SIZE items at a time
            batch = all_item_names[:DEFAULT_PAGINATION_SIZE]
            remaining = len(all_item_names) - len(batch)
            has_more = remaining > 0

            if has_more:
                # Format with "and others" indicator
                if len(batch) == 1:
                    items_list = f"{batch[0]}, and others"
                else:
                    items_list = ", ".join(batch) + ", and others"

                # Save pagination state for "what else" follow-ups
                order.set_menu_pagination(
                    pagination_key, DEFAULT_PAGINATION_SIZE, len(all_item_names)
                )
            else:
                # All items fit in one response
                items_list = format_english_list(batch)
                order.clear_menu_pagination()

            # Build quick replies for inline clickable text
            qr = [{"label": name, "value": name} for name in batch]
            if has_more:
                qr.append({"label": "others", "value": "what else?"})

            return StateMachineResult(
                message=f"What kind? We have {items_list}.",
                order=order,
                quick_replies=qr,
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

        Delegates to PriceInquiryHandler.

        Args:
            item_query: The item the user is asking about (e.g., 'sesame bagel', 'lox')
            order: Current order state

        Returns:
            StateMachineResult with the price information
        """
        return self._price_inquiry_handler.handle_price_inquiry(item_query, order)

    def handle_item_description_inquiry(self, item_query, order):
        return self._display_handler.handle_item_description_inquiry(item_query, order)

    def handle_signature_menu_inquiry(self, menu_type, order):
        return self._display_handler.handle_signature_menu_inquiry(menu_type, order)
