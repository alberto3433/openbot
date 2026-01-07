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
    get_toppings,
    get_proteins,
    get_cheeses,
    get_spreads,
)

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .pricing import PricingEngine

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
            for item in batch:
                name = item.get('name', 'Unknown')
                if lookup_type == "bagel":
                    bagel_type = name.lower().replace(" bagel", "").strip()
                    price = self.pricing.lookup_bagel_price(bagel_type) if self.pricing else 0
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

    def handle_more_menu_items(self, order: OrderTask) -> StateMachineResult:
        """Handle 'show more' menu requests.

        Continues listing items from where the previous menu query left off.
        Supports both menu item categories and modifier categories (toppings, proteins, etc.).
        """
        pagination = order.get_menu_pagination()

        if not pagination:
            # No previous menu query - ask what they want to see more of
            return StateMachineResult(
                message="More of what? What would you like me to list?",
                order=order,
            )

        category = pagination.get("category")
        offset = pagination.get("offset", 0)
        total_items = pagination.get("total_items", 0)

        # Check if this is a modifier category (toppings, proteins, cheeses, spreads)
        modifier_categories = {
            "toppings": get_toppings,
            "proteins": get_proteins,
            "cheeses": get_cheeses,
            "spreads": get_spreads,
        }

        if category in modifier_categories:
            return self._handle_more_modifier_items(category, modifier_categories[category], offset, order)

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

            # For cheeses category, filter out cream cheese variants (those belong in spreads)
            if category == "cheeses":
                if "cream cheese" in item_lower or " cc" in item_lower:
                    continue
                if item_lower in ("avocado spread", "lox spread"):
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

        # Handle spread/cream cheese queries as by-the-pound category
        if menu_query_type in ("spread", "cream_cheese", "cream cheese"):
            if self._list_by_pound_category:
                return self._list_by_pound_category("spread", order)
            return StateMachineResult(
                message="We have various cream cheeses and spreads. Would you like to hear about them?",
                order=order,
            )

        # Handle beverage queries (beverage_all from DB, or legacy beverage/drink terms)
        # DB maps "drinks"/"beverages" to "beverage_all" slug
        if menu_query_type in ("beverage_all", "beverage", "drink"):
            items, category_key = self._get_items_for_category(menu_query_type)
            if items:
                items_str, has_more = self._format_items_list(items, 0, show_prices, category_key)
                # Save pagination state if there are more items
                if has_more:
                    order.set_menu_pagination(category_key, DEFAULT_PAGINATION_SIZE, len(items))
                else:
                    order.clear_menu_pagination()
                return StateMachineResult(
                    message=f"Our beverages include: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any beverages on the menu right now. Is there anything else I can help you with?",
                order=order,
            )

        # Handle "sandwich" or "sandwich_all" specially - too broad, need to ask what kind
        if menu_query_type in ("sandwich", "sandwich_all"):
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle dessert queries (DB maps dessert terms to "dessert" slug)
        if menu_query_type == "dessert":
            items, category_key = self._get_items_for_category("dessert")
            if items:
                items_str, has_more = self._format_items_list(items, 0, show_prices, category_key)
                # Save pagination state if there are more items
                if has_more:
                    order.set_menu_pagination(category_key, DEFAULT_PAGINATION_SIZE, len(items))
                else:
                    order.clear_menu_pagination()
                return StateMachineResult(
                    message=f"For desserts and pastries, we have: {items_str}. Would you like any of these?",
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any desserts on the menu right now. What else can I get for you?",
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
        # Proper pluralization
        if type_name.endswith("ch") or type_name.endswith("s"):
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

        Asks what kind of soda they want, listing available options.
        """
        # Get beverages from menu data
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        beverages = items_by_type.get("beverage", [])

        if beverages:
            # Get just the names of a few common sodas
            soda_names = [item.get("name", "") for item in beverages[:6]]
            # Filter out empty names and format nicely
            soda_names = [name for name in soda_names if name]
            if len(soda_names) > 3:
                soda_list = ", ".join(soda_names[:3]) + ", and others"
            elif len(soda_names) > 1:
                soda_list = ", ".join(soda_names[:-1]) + f", and {soda_names[-1]}"
            else:
                soda_list = soda_names[0] if soda_names else "Coke, Diet Coke, Sprite"

            return StateMachineResult(
                message=f"What kind? We have {soda_list}.",
                order=order,
            )

        # Fallback if no beverages in menu data
        return StateMachineResult(
            message="What kind? We have Coke, Diet Coke, Sprite, and others.",
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

        # Check if this is a generic category inquiry (e.g., "a bagel", "coffee", "sandwich")
        # Map generic terms to their item_type and display name
        generic_category_map = {
            "bagel": ("bagel", "bagels"),
            "coffee": ("sized_beverage", "coffees"),
            "latte": ("sized_beverage", "lattes"),
            "cappuccino": ("sized_beverage", "cappuccinos"),
            "espresso": ("sized_beverage", "espressos"),
            "tea": ("sized_beverage", "teas"),
            "drink": ("beverage", "drinks"),
            "beverage": ("beverage", "beverages"),
            "soda": ("beverage", "sodas"),
            "omelette": ("omelette", "omelettes"),
            "side": ("side", "sides"),
        }

        # Special handling for "sandwich" - too broad, need to ask what kind
        if query_lower == "sandwich":
            return StateMachineResult(
                message="We have egg sandwiches, fish sandwiches, cream cheese sandwiches, signature sandwiches, deli sandwiches, and more. What kind of sandwich would you like?",
                order=order,
            )

        # Handle specific sandwich types
        sandwich_type_map = {
            "egg sandwich": ("egg_sandwich", "egg sandwiches"),
            "fish sandwich": ("fish_sandwich", "fish sandwiches"),
            "cream cheese sandwich": ("spread_sandwich", "cream cheese sandwiches"),
            "spread sandwich": ("spread_sandwich", "spread sandwiches"),
            "salad sandwich": ("salad_sandwich", "salad sandwiches"),
            "deli sandwich": ("deli_sandwich", "deli sandwiches"),
            "signature sandwich": ("signature_items", "signature sandwiches"),
        }

        if query_lower in sandwich_type_map and self.pricing:
            item_type, display_name = sandwich_type_map[query_lower]
            min_price = self.pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
                    order=order,
                )

        if query_lower in generic_category_map and self.pricing:
            item_type, display_name = generic_category_map[query_lower]
            min_price = self.pricing.get_min_price_for_category(item_type)
            if min_price > 0:
                return StateMachineResult(
                    message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
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

        # Check bagels specifically (they may not be in items_by_type with prices)
        bagel_items = items_by_type.get("bagel", [])
        is_bagel_query = "bagel" in query_lower
        if is_bagel_query and not best_match:
            # Try to find a matching bagel
            for bagel in bagel_items:
                bagel_name = bagel.get("name", "").lower()
                if query_lower in bagel_name or bagel_name in query_lower:
                    best_match = bagel
                    best_match_score = 75
                    break

            # If they asked about a specific bagel type but we didn't find it,
            # give the general bagel price if available
            if not best_match and bagel_items:
                # Use the first bagel price as the general price
                best_match = bagel_items[0]
                best_match_score = 50

        if best_match and best_match_score >= 50:
            name = best_match.get("name", "Unknown")
            # Bagels use _lookup_bagel_price since they don't store price in items_by_type
            if is_bagel_query or "bagel" in name.lower():
                bagel_type = name.lower().replace(" bagel", "").strip()
                price = self.pricing.lookup_bagel_price(bagel_type) if self.pricing else 0
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
            message = (
                f"I don't have detailed information about \"{item_query}\" right now. "
                "Would you like me to tell you what sandwiches or egg dishes we have?"
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
            # Get the display name from the type slug (proper pluralization)
            type_name = menu_type.replace("_", " ")
            if type_name.endswith("ch") or type_name.endswith("s"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # No specific type - get all signature items
            items = items_by_type.get("signature_items", [])
            type_display_name = "signature menu options"

        if not items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                order=order,
            )

        # Build a nice list of items (without prices - prices only shown when specifically asked)
        item_descriptions = [item.get("name", "Unknown") for item in items]

        # Format the response
        if len(item_descriptions) == 1:
            items_list = item_descriptions[0]
        elif len(item_descriptions) == 2:
            items_list = f"{item_descriptions[0]} and {item_descriptions[1]}"
        else:
            items_list = ", ".join(item_descriptions[:-1]) + f", and {item_descriptions[-1]}"

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

        return StateMachineResult(
            message=message,
            order=order,
        )
