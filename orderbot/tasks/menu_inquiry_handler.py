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
import re
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

    def _get_available_menu_categories_message(self) -> str:
        """Build a message listing a few available menu categories from database.

        Returns a formatted string like "sandwiches or drinks" for use in
        helpful suggestions when an item isn't found.

        Uses high-level display groups (Breads, Sandwiches, Drinks) instead of
        granular item types (Bagels, Chai Drinks, etc.) for cleaner UX.
        """
        try:
            # Get high-level display groups (e.g., Breads, Sandwiches, Drinks)
            display_groups = menu_cache.get_menu_display_groups()
            if display_groups:
                # Pick 2-3 main categories
                display_names = [g["display_name"] for g in display_groups][:3]
                if len(display_names) == 1:
                    return display_names[0].lower()
                elif len(display_names) == 2:
                    return f"{display_names[0].lower()} or {display_names[1].lower()}"
                else:
                    return f"{display_names[0].lower()}, {display_names[1].lower()}, or {display_names[2].lower()}"
        except Exception as e:
            logger.warning("Failed to get display groups from database: %s", e)

        # Fallback message
        return "our menu items"

    def _find_matching_item_types(self, query: str, items_by_type: dict) -> list[str]:
        """Find item types that match a query term.

        Checks for:
        1. Exact slug match (query == item_type_slug)
        2. Singular form match (singularize(query) == item_type_slug)
        3. Slug contains singular query as a word (e.g., "tea" matches "iced_tea")

        Returns:
            List of matching item type slugs, empty if none found.
        """
        query_lower = normalize_text(query)
        singular = singularize(query_lower)

        matching = []
        for item_type_slug in items_by_type.keys():
            # Exact match
            if item_type_slug == query_lower or item_type_slug == singular:
                matching.append(item_type_slug)
            # Partial match: item type contains the query as a word
            # e.g., "tea" matches "iced_tea" (tea is a word in iced_tea)
            elif singular in item_type_slug.split('_'):
                matching.append(item_type_slug)

        return matching

    def _get_items_for_category(self, menu_query_type: str) -> tuple[list, str]:
        """Get items and display name for a menu category.

        Uses DB-driven approach with lookup_type:
        1. Check if query matches item type slugs (more specific than display groups)
        2. Check if query matches a display group slug (e.g., "breads")
        3. Look up category in menu_cache.get_category_keyword_mapping()
        4. If lookup_type=="category", query via MenuItemCategory join table
        5. If lookup_type=="item_type", query by item_type_id
        6. Fall back to direct slug in items_by_type (for pagination state)
        7. Fall back to partial string matching on all items

        Returns:
            Tuple of (items list, category_key for pagination)
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # Check display groups first (e.g., "breads", "sandwiches", "drinks")
        # Display groups aggregate multiple item types and handle hierarchical queries
        display_group = menu_cache.get_display_group_by_slug(menu_query_type)
        if display_group:
            item_type_slugs = menu_cache.get_item_types_in_display_group(display_group["slug"])
            if item_type_slugs:
                # Collect items from all item types in this display group
                items = []
                for item_type_slug in item_type_slugs:
                    items.extend(items_by_type.get(item_type_slug, []))
                if items:
                    logger.info(
                        "Menu query: '%s' matched display group with %d item types, %d total items",
                        menu_query_type, len(item_type_slugs), len(items)
                    )
                    return items, display_group["slug"]

        # Check for item type matches (slug-based matching)
        matching_item_types = self._find_matching_item_types(menu_query_type, items_by_type)
        if matching_item_types:
            items = []
            for item_type_slug in matching_item_types:
                items.extend(items_by_type.get(item_type_slug, []))

            # Also search by name to catch items like "Snapple Iced Tea" when searching for "tea"
            # This finds items with the search term in their name, regardless of item type
            name_matched_items = menu_cache.search_menu_items_by_term(menu_query_type)
            if name_matched_items:
                # Add name-matched items that aren't already included (avoid duplicates)
                # Use lowercase names for deduplication since items may not have IDs
                existing_names = {item.get("name", "").lower() for item in items}
                for item in name_matched_items:
                    item_name = item.get("name", "").lower()
                    if item_name and item_name not in existing_names:
                        items.append(item)
                        existing_names.add(item_name)

            if items:
                logger.info(
                    "Menu query: '%s' matched %d item type(s): %s with %d items (including name matches)",
                    menu_query_type, len(matching_item_types), matching_item_types, len(items)
                )
                # Use first matching type as the category key for pagination
                return items, matching_item_types[0]

        # Look up category info from DB-loaded cache
        # This ensures "beverage" maps to sized_beverage/espresso_based_beverage per DB config
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

        # Fall back to direct item_type slug (used in pagination state)
        if menu_query_type in items_by_type:
            return items_by_type[menu_query_type], menu_query_type

        # FALLBACK: For unrecognized terms, search by word-boundary in names AND aliases
        # This handles "what lattes do you have?" by finding Hot Latte, Iced Latte, etc.
        # Uses word-boundary matching (not substring) and singularizes the search term
        filtered = menu_cache.search_menu_items_by_term(menu_query_type)
        if filtered:
            logger.info(
                "Menu query fallback: '%s' matched %d items via word-boundary search",
                menu_query_type, len(filtered)
            )
            return filtered, menu_query_type

        # FALLBACK 2: Check if first word is a known name prefix (e.g., "iced", "hot")
        # This handles "what iced drinks do you have?" by finding items like "Iced Coffee"
        words = menu_query_type.split()
        if words:
            first_word = words[0].lower()
            prefix_items = menu_cache.get_menu_items_by_name_prefix(first_word)
            if prefix_items:
                # If there's a category filter (remaining words), apply it
                if len(words) >= 2:
                    category_filter = " ".join(words[1:])
                    # Try to look up the category to filter by item types
                    display_group = menu_cache.get_display_group_by_slug(category_filter)
                    if display_group:
                        # Filter prefix_items to only those in the display group's item types
                        allowed_types = set(
                            menu_cache.get_item_types_in_display_group(display_group["slug"])
                        )
                        prefix_items = [
                            item for item in prefix_items
                            if item.get("item_type") in allowed_types
                        ]
                    else:
                        # Try category keyword mapping
                        category_info = menu_cache.get_category_keyword_mapping(category_filter)
                        if category_info:
                            slug = category_info["slug"]
                            lookup_type = category_info.get("lookup_type", "item_type")
                            if lookup_type == "item_type":
                                prefix_items = [
                                    item for item in prefix_items
                                    if item.get("item_type") == slug
                                ]

                if prefix_items:
                    logger.info(
                        "Menu query prefix: '%s' -> prefix='%s' matched %d items",
                        menu_query_type, first_word, len(prefix_items)
                    )
                    return prefix_items, menu_query_type

        # FALLBACK 3: Handle "adjective + category" patterns (legacy approach)
        # Try splitting into prefix word(s) + base category, then filter by name containing prefix
        # This is less precise than prefix index but catches items where prefix isn't the first word
        if len(words) >= 2:
            # Try the last word as category (e.g., "drinks" from "iced drinks")
            base_category = words[-1]
            prefix_filter = " ".join(words[:-1])  # e.g., "iced"

            category_info = menu_cache.get_category_keyword_mapping(base_category)
            if category_info:
                slug = category_info["slug"]
                lookup_type = category_info.get("lookup_type", "item_type")

                if lookup_type == "category":
                    all_items = menu_cache.get_items_by_category(slug)
                else:
                    all_items = items_by_type.get(slug, [])

                # Filter items by prefix (e.g., items containing "iced")
                if all_items and prefix_filter:
                    filter_pattern = re.compile(rf'\b{re.escape(prefix_filter)}\b', re.IGNORECASE)
                    filtered = [
                        item for item in all_items
                        if filter_pattern.search(item.get("name", ""))
                    ]
                    if filtered:
                        logger.info(
                            "Menu query fallback: '%s' -> base='%s' + filter='%s' matched %d items",
                            menu_query_type, base_category, prefix_filter, len(filtered)
                        )
                        return filtered, menu_query_type

        # No matches found
        return [], menu_query_type

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
                if has_more:
                    qr.append({"label": "more", "value": "what else?"})

                return StateMachineResult(
                    message=f"We have a great selection! What are you in the mood for? We have {categories_text}.",
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
                    message=f"We don't have {type_display}, but we do have {categories_text}. What are you in the mood for?",
                    order=order,
                    quick_replies=qr,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display} on the menu. What else can I help you with?",
                order=order,
            )

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
                phrases = [p.strip().lower() for p in required_phrases.split(",") if p.strip()]
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

        item_query_lower = normalize_text(item_query)

        # Get item descriptions from menu_data (loaded from database)
        item_descriptions = self.menu_data.get("item_descriptions", {}) if self.menu_data else {}

        # Try to find an exact match or close match in descriptions
        description = item_descriptions.get(item_query_lower)
        found_item_name = None  # Track the actual item name found

        if description:
            # Exact match - the key is the item name
            found_item_name = item_query_lower

        if not description:
            # Try partial matching - look for item_query in keys
            for key, desc in item_descriptions.items():
                if item_query_lower in key or key in item_query_lower:
                    description = desc
                    found_item_name = key  # Capture the actual key (item name)
                    break

        if not description:
            # Also search menu_data for item names and their descriptions
            if self.menu_data:
                items_by_type = self.menu_data.get("items_by_type", {})
                for item_type, items in items_by_type.items():
                    for item in items:
                        item_name = item.get("name", "").lower()
                        if item_query_lower in item_name or item_name in item_query_lower:
                            # Capture the actual item name from menu data
                            found_item_name = item.get("name", "")
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
            # Use the actual item name found, or fall back to user query
            formatted_name = found_item_name.title() if found_item_name else item_query.title()
            message = f"{formatted_name} has {description}. Would you like to order one?"

            # Store context so "yes" / "give me one" adds this item
            # Use the actual item name, not the user's query
            order.pending_suggested_item = formatted_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
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
            # Get the display name from the type slug (use proper pluralization via inflect)
            type_name = menu_type.replace("_", " ")
            type_display_name = pluralize(type_name)
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
            items_list = format_english_list(item_names)

            order.clear_menu_pagination()

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in item_names]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr,
        )
