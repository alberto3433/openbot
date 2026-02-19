"""
Recommendation Handler for Order State Machine.

This module handles recommendation inquiries like "what do you recommend?"
or "what bagels do you recommend?"

Extracted from store_info_handler.py for better separation of concerns.
"""

import logging

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .mixins import MenuDataMixin
from .utils.text import format_english_list
from orderbot.cache import menu_cache

logger = logging.getLogger(__name__)


class RecommendationHandler(MenuDataMixin):
    """
    Handles recommendation inquiries.

    Provides menu recommendations based on user queries, either for specific
    item types or general recommendations.
    """

    def __init__(
        self,
        menu_data: dict | None = None,
    ):
        """
        Initialize the recommendation handler.

        Args:
            menu_data: Menu data dictionary for recommendations.
        """
        self._menu_data = menu_data or {}

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
        # Build a lookup from ID to name via public cache method
        id_to_name = menu_cache.get_item_names_by_ids(set(item_ids))

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

        # Build quick replies for inline clickable text
        qr = [{"label": name, "value": name} for name in items]

        return StateMachineResult(
            message=message,
            order=order,
            quick_replies=qr,
        )

    def _format_item_type_suggestions(self, order: OrderTask) -> StateMachineResult:
        """Format a response with display group suggestions for generic recommendation requests.

        Shows up to 5 display groups (high-level categories like Breads, Sandwiches, Drinks),
        with pagination support for the rest via "what else" follow-ups.

        Args:
            order: Current order state
        """
        # Use display groups for high-level categories (same as menu inquiry handler)
        display_groups = menu_cache.get_menu_display_groups()

        if display_groups:
            page_size = DEFAULT_PAGINATION_SIZE
            group_names = [g["display_name"] for g in display_groups]
            shown_names = group_names[:page_size]
            has_more = len(group_names) > page_size

            # Format the list
            categories_text = format_english_list(shown_names)
            if has_more:
                categories_text += ", and more"
                # Store pagination state for "what else" follow-ups
                order.menu_query_pagination = {
                    "type": "item_types",
                    "items": group_names,
                    "offset": page_size,
                }
            else:
                order.clear_menu_pagination()

            # Build quick replies for inline clickable text
            qr = [{"label": name, "value": f"What {name.lower()} do you have?"} for name in shown_names]
            if has_more:
                qr.append({"label": "more", "value": "what else?"})

            return StateMachineResult(
                message=f"We have a great selection! We have {categories_text} — what are you in the mood for?",
                order=order,
                quick_replies=qr,
            )

        # Fallback if no display groups configured
        return StateMachineResult(
            message="We have a great selection! What are you in the mood for?",
            order=order,
        )
