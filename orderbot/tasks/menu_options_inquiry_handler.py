"""
Menu Options Inquiry Handler for Order State Machine.

This module handles inquiries about menu options including:
- Modifier inquiries ("what can I add to coffee?", "what sweeteners do you have?")
- Attribute inquiries ("what bagel types do you have?", "what sizes are available?")

Extracted from store_info_handler.py for better separation of concerns.
"""

import logging

from .models import OrderTask
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE, get_item_type_display_name
from .mixins import MenuDataMixin
from .utils.text import format_english_list
from orderbot.cache import menu_cache

logger = logging.getLogger(__name__)


class MenuOptionsInquiryHandler(MenuDataMixin):
    """
    Handles inquiries about menu options (modifiers and attributes).

    Manages questions about what modifiers can be added to items,
    and what attribute options are available (sizes, types, etc.).
    """

    def __init__(
        self,
        menu_data: dict | None = None,
    ):
        """
        Initialize the menu options inquiry handler.

        Args:
            menu_data: Menu data dictionary.
        """
        self._menu_data = menu_data or {}

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

        # Category not found in modifier_categories - try ingredient category lookup
        # This handles queries like "what sweeteners do you have?" where "sweetener"
        # is an ingredient category, not a modifier category
        ingredient_details = menu_cache.get_ingredient_details(category)
        if ingredient_details:
            return self._describe_ingredient_category(category, ingredient_details, order)

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

    def _describe_ingredient_category(
        self,
        category: str,
        ingredient_details: list[dict],
        order: OrderTask,
    ) -> StateMachineResult:
        """Describe available options for an ingredient category.

        Handles queries like "what sweeteners do you have?" where the category
        is an ingredient category (sweetener, syrup, milk, etc.) rather than
        a modifier_categories entry.

        Args:
            category: Ingredient category slug (e.g., 'sweetener', 'syrup')
            ingredient_details: List of ingredient detail dicts from cache
            order: Current order state
        """
        # Get display name for the category
        display_name = menu_cache.get_ingredient_category_display_name(category)

        # Extract ingredient names from details
        ingredient_names = sorted([
            detail.get("name", detail.get("slug", ""))
            for detail in ingredient_details
            if detail.get("name") or detail.get("slug")
        ])

        if not ingredient_names:
            order.clear_menu_pagination()
            return StateMachineResult(
                message=f"We have various {display_name.lower()} available. What would you like?",
                order=order,
            )

        if len(ingredient_names) <= DEFAULT_PAGINATION_SIZE:
            # Show all items, no pagination needed
            items_str = format_english_list(ingredient_names)
            order.clear_menu_pagination()
            message = f"For {display_name.lower()}, we have {items_str}. What would you like?"
        else:
            # Show first batch with pagination
            first_batch = ingredient_names[:DEFAULT_PAGINATION_SIZE]
            items_str = format_english_list(first_batch)

            # Set pagination state for "what else" follow-ups
            order.set_menu_pagination(category, DEFAULT_PAGINATION_SIZE, len(ingredient_names))
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

    # =========================================================================
    # Attribute Inquiry Handlers
    # =========================================================================

    def handle_attribute_inquiry(
        self,
        item_type: str | None,
        signal: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle attribute option questions like 'what bagel types do you have?'

        This is for questions about attribute VALUES (bread types, sizes), not menu items.

        Args:
            item_type: Item type slug being asked about (e.g., 'bagel', 'sized_beverage')
            signal: The linguistic signal word (e.g., 'types', 'flavors', 'sizes')
            order: Current order state (unchanged)

        Returns:
            StateMachineResult with attribute options, or fallback if can't resolve.
        """
        # Resolve attribute from the signal word and item type
        attr_slug = self._resolve_attribute_from_inquiry(item_type, signal)

        # Fallback: if we have item_type but no attr_slug, use primary attribute
        if not attr_slug and item_type:
            attr_slug = self._get_primary_attribute(item_type)

        if not attr_slug:
            # Can't determine attribute - fall through with generic message
            if item_type:
                display_name = menu_cache.get_item_type_display_name(item_type)
                return StateMachineResult(
                    message=f"We have various {display_name.lower()} options available. What would you like?",
                    order=order,
                )
            return StateMachineResult(
                message="We have lots of options! What item are you curious about?",
                order=order,
            )

        # Get options for this attribute
        return self._format_attribute_options_response(attr_slug, item_type, order)

    def _resolve_attribute_from_inquiry(
        self,
        item_type: str | None,
        signal: str | None,
    ) -> str | None:
        """Resolve signal word and item type to an attribute slug.

        Uses the attribute_inquiry_keywords table (data-driven) to map:
        - "types" + "bagel" -> "bread"
        - "sizes" + None -> "size"
        - "flavors" + "bagel" -> "bread"

        Args:
            item_type: Item type slug (optional)
            signal: Signal word from query (e.g., 'types', 'sizes', 'flavors')

        Returns:
            Attribute slug or None if not resolvable.
        """
        if not signal:
            return None

        # Normalize signal to lowercase
        signal_lower = signal.lower()

        # If signal is itself a valid global attribute slug, return it directly
        # This handles direct attribute queries like "bread", "size", "temperature"
        if menu_cache.get_global_attribute_options(signal_lower):
            return signal_lower

        # Data-driven lookup from attribute_inquiry_keywords table
        # This replaces the old hardcoded common_mappings dict
        attr_slug = menu_cache.get_attribute_for_inquiry_keyword(signal_lower, item_type)
        if attr_slug:
            return attr_slug

        # Fallback: signal word matches attribute slug directly (e.g., "size" -> "size")
        if item_type:
            attrs = menu_cache.get_item_type_attributes(item_type)
            if signal_lower in attrs:
                return signal_lower

        # If we have an item_type but couldn't resolve the signal to a specific
        # attribute, return None so caller can fall back to primary attribute.
        # If no item_type, also return None - let the caller decide.
        return None

    def _get_primary_attribute(self, item_type: str) -> str | None:
        """Get the primary (first ask_in_conversation) attribute for an item type.

        Args:
            item_type: Item type slug

        Returns:
            Attribute slug or None if not found.
        """
        attrs = menu_cache.get_item_type_attributes(item_type)
        # Find first attribute with ask_in_conversation=True
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("ask_in_conversation"):
                return attr_slug
        return None

    def _format_attribute_options_response(
        self,
        attr_slug: str,
        item_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format response showing available options for an attribute.

        Uses item-type-specific options when item_type is provided,
        falling back to global attribute options if not.

        Args:
            attr_slug: Attribute slug (e.g., 'bread', 'size')
            item_type: Item type for context (optional)
            order: Current order state

        Returns:
            StateMachineResult with formatted options list.
        """
        options = []
        attr_display = attr_slug

        # Try item-type-specific options first
        if item_type:
            attrs = menu_cache.get_item_type_attributes(item_type)
            attr_config = attrs.get(attr_slug, {})
            options = attr_config.get("options", [])
            attr_display = attr_config.get("display_name", attr_slug)

        # Fall back to global attribute options
        if not options:
            options = menu_cache.get_global_attribute_options(attr_slug)
            attr_display = menu_cache.get_attribute_display_name(attr_slug)

        if not options:
            return StateMachineResult(
                message=f"We have various {attr_display.lower()} available. What would you like?",
                order=order,
            )

        # Get display names for available options only
        option_names = sorted([
            opt.get("display_name", opt.get("slug", ""))
            for opt in options
            if opt.get("is_available", True)
        ])

        if not option_names:
            return StateMachineResult(
                message=f"We have various {attr_display.lower()} available. What would you like?",
                order=order,
            )

        # Format options list with pagination if needed
        if len(option_names) <= DEFAULT_PAGINATION_SIZE:
            options_str = format_english_list(option_names)
            order.clear_menu_pagination()
            message = f"For {attr_display.lower()}, we have {options_str}. What would you like?"
        else:
            first_batch = option_names[:DEFAULT_PAGINATION_SIZE]
            options_str = format_english_list(first_batch)

            # Store pagination state with "attribute_options" type so handle_more knows what to do
            order.menu_query_pagination = {
                "type": "attribute_options",
                "attribute_slug": attr_slug,
                "attribute_display": attr_display,
                "item_type": item_type,
                "items": option_names,  # Store all option names for pagination
                "offset": DEFAULT_PAGINATION_SIZE,
            }
            message = f"For {attr_display.lower()}, we have {options_str}, and more. Would you like one of these, or want to hear more?"

        return StateMachineResult(message=message, order=order)
