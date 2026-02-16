"""
Dietary Inquiry Handler for Order State Machine.

This module handles dietary and allergen-related inquiries including:
- Dietary options inquiries ("do you have vegan options?")
- Specific item dietary inquiries ("is the classic gluten-free?")
- Allergen inquiries ("does X contain nuts?")
- Allergen-free options inquiries ("anything nut-free?")
- Availability inquiries ("do you have X in stock?")
- Customization inquiries ("can I customize X?")

Extracted as a specialized handler for dietary/allergen concerns.
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .mixins import MenuDataMixin
from .utils.text import format_english_list, format_paginated_list
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .pending_fields import PendingField

if TYPE_CHECKING:
    from .handler_config import HandlerConfig
    from .unrecognized_item_handler import UnrecognizedItemHandler

logger = logging.getLogger(__name__)


# Human-readable names for dietary properties
DIETARY_DISPLAY_NAMES = {
    "is_vegan": "vegan",
    "is_vegetarian": "vegetarian",
    "is_gluten_free": "gluten-free",
    "is_dairy_free": "dairy-free",
    "is_kosher": "kosher",
}

# Pattern to detect "something/anything with X" in availability queries
_SOMETHING_WITH_RE = re.compile(
    r"(?:something|anything|items?|stuff)\s+with\s+(.+)",
    re.IGNORECASE,
)


def _allergen_display_name(allergen_type: str) -> str:
    """Derive display name from allergen property (e.g., 'contains_eggs' -> 'eggs')."""
    return allergen_type.replace("contains_", "")


class DietaryInquiryHandler(MenuDataMixin):
    """
    Handles dietary and allergen-related inquiries.

    Manages dietary options listings, allergen inquiries, availability checks,
    and customization questions.
    """

    def __init__(
        self,
        config: "HandlerConfig | None" = None,
        unrecognized_handler: "UnrecognizedItemHandler | None" = None,
    ):
        """
        Initialize the dietary inquiry handler.

        Args:
            config: HandlerConfig with shared dependencies.
            unrecognized_handler: Handler for unrecognized item suggestions.
        """
        self._menu_data = config.menu_data if config else {}
        self._unrecognized_handler = unrecognized_handler

    def _resolve_category_to_item_types(self, category: str) -> list[str] | None:
        """Resolve a category term to a list of item type slugs.

        Tries multiple resolution strategies:
        1. Display group lookup (e.g., "drinks" -> display group -> item types)
        2. Category keyword mapping (e.g., "bagels" -> item type "bagel")

        Args:
            category: User category term (e.g., "drinks", "bagels", "sandwiches")

        Returns:
            List of item type slugs, or None if category can't be resolved.
        """
        if not category:
            return None

        # Try display group lookup first
        display_group = menu_cache.get_display_group_by_slug(category)
        if display_group:
            item_types = menu_cache.get_item_types_in_display_group(display_group["slug"])
            if item_types:
                return item_types

        # Try category keyword mapping
        keyword_info = menu_cache.get_category_keyword_mapping(category)
        if keyword_info and keyword_info.get("slug"):
            return [keyword_info["slug"]]

        return None

    def handle_dietary_options_inquiry(
        self,
        dietary_type: str,
        order: OrderTask,
        category: str | None = None,
    ) -> StateMachineResult:
        """Handle inquiry about dietary options ("do you have vegan options?").

        Args:
            dietary_type: The dietary property (e.g., "is_vegan", "is_gluten_free")
            order: Current order state
            category: Optional category filter (e.g., "drinks" in "what vegan drinks?")

        Returns:
            StateMachineResult with matching items or message that none are available
        """
        display_name = DIETARY_DISPLAY_NAMES.get(dietary_type, dietary_type.replace("is_", ""))

        # Resolve category to item type slugs if provided
        item_type_slugs = None
        category_display = None
        if category:
            item_type_slugs = self._resolve_category_to_item_types(category)
            category_display = category

        # Query cache for items matching this dietary property (optionally filtered)
        if item_type_slugs:
            items = menu_cache.get_items_by_dietary_property_filtered(dietary_type, item_type_slugs)
        else:
            items = menu_cache.get_items_by_dietary_property(dietary_type)

        if not items:
            # Check if we have dietary data at all
            if not menu_cache.has_dietary_data():
                category_msg = f" {category_display}" if category_display else ""
                return StateMachineResult(
                    message=(
                        f"I don't have detailed dietary information available at the moment. "
                        f"I'd recommend checking with the store directly about {display_name}{category_msg} options. "
                        f"Is there anything else I can help you with?"
                    ),
                    order=order,
                )

            if category_display:
                return StateMachineResult(
                    message=(
                        f"I don't see any {display_name} {category_display} on our menu right now. "
                        f"Would you like me to show you our {display_name} options instead?"
                    ),
                    order=order,
                )

            return StateMachineResult(
                message=(
                    f"I don't see any items specifically marked as {display_name} on our menu right now. "
                    f"Would you like me to tell you about our menu options?"
                ),
                order=order,
            )

        # Format the list of items with pagination
        item_names = [item.get("name", "Unknown") for item in items]

        items_list, new_offset = format_paginated_list(item_names, DEFAULT_PAGINATION_SIZE)
        if new_offset > 0:
            # Save pagination state for "show more" follow-ups
            order.menu_query_pagination = {
                "type": "dietary_items",
                "dietary_type": dietary_type,
                "dietary_display": display_name,
                "category": category_display,
                "items": item_names,
                "offset": new_offset,
            }
        else:
            order.clear_menu_pagination()

        # Build response message
        if category_display:
            return StateMachineResult(
                message=f"Our {display_name} {category_display} include: {items_list}. Would you like any of these?",
                order=order,
            )

        return StateMachineResult(
            message=f"Our {display_name} options include: {items_list}. Would you like any of these?",
            order=order,
        )

    def handle_dietary_item_inquiry(
        self,
        item_name: str,
        dietary_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about a specific item's dietary property ("is the classic vegan?").

        Args:
            item_name: The menu item name to check
            dietary_type: The dietary property (e.g., "is_vegan", "is_gluten_free")
            order: Current order state

        Returns:
            StateMachineResult with yes/no answer about the dietary property
        """
        display_name = DIETARY_DISPLAY_NAMES.get(dietary_type, dietary_type.replace("is_", ""))

        # Get dietary info for this item
        info = menu_cache.get_item_dietary_info(item_name)

        if not info:
            # Try to find the item via alias resolution
            canonical_name = menu_cache.resolve_menu_item_alias(item_name)
            if canonical_name:
                info = menu_cache.get_item_dietary_info(canonical_name)
                item_name = canonical_name

        if not info:
            return StateMachineResult(
                message=(
                    f"I couldn't find \"{item_name}\" on our menu. "
                    f"Would you like me to show you what we have?"
                ),
                order=order,
            )

        # Get the dietary value
        value = info.get(dietary_type)
        item_display_name = info.get("name", item_name)

        if value is None:
            return StateMachineResult(
                message=(
                    f"I don't have {display_name} information for {item_display_name} at the moment. "
                    f"I'd recommend checking with the store directly. "
                    f"Would you like to order something else?"
                ),
                order=order,
            )

        if value:
            return StateMachineResult(
                message=f"Yes, {item_display_name} is {display_name}! Would you like to add it to your order?",
                order=order,
            )
        else:
            # Set pending state so we can handle "yes" response
            order.pending_dietary_followup = {
                "dietary_type": dietary_type,
                "category": None,
            }
            order.pending_field = PendingField.CONFIRM_DIETARY_FOLLOWUP
            return StateMachineResult(
                message=(
                    f"No, {item_display_name} is not {display_name}. "
                    f"Would you like me to show you our {display_name} options instead?"
                ),
                order=order,
            )

    def handle_allergen_inquiry(
        self,
        item_name: str,
        allergen_type: str | None,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about allergens in a specific item ("does X contain nuts?").

        Args:
            item_name: The menu item name to check
            allergen_type: The allergen property (e.g., "contains_nuts") or None for all allergens
            order: Current order state

        Returns:
            StateMachineResult with allergen information
        """
        # Get dietary info for this item
        info = menu_cache.get_item_dietary_info(item_name)

        if not info:
            # Try to find the item via alias resolution
            canonical_name = menu_cache.resolve_menu_item_alias(item_name)
            if canonical_name:
                info = menu_cache.get_item_dietary_info(canonical_name)
                item_name = canonical_name

        if not info:
            return StateMachineResult(
                message=(
                    f"I couldn't find \"{item_name}\" on our menu. "
                    f"Would you like me to show you what we have?"
                ),
                order=order,
            )

        item_display_name = info.get("name", item_name)

        if allergen_type:
            # Asking about a specific allergen
            allergen_display = _allergen_display_name(allergen_type)
            value = info.get(allergen_type)

            if value is None:
                return StateMachineResult(
                    message=(
                        f"I don't have allergen information about {allergen_display} for {item_display_name}. "
                        f"Please check with the store directly for accurate allergen information. "
                        f"Can I help you with anything else?"
                    ),
                    order=order,
                )

            if value:
                return StateMachineResult(
                    message=(
                        f"Yes, {item_display_name} contains {allergen_display}. "
                        f"Would you like me to suggest alternatives without {allergen_display}?"
                    ),
                    order=order,
                )
            else:
                return StateMachineResult(
                    message=(
                        f"No, {item_display_name} does not contain {allergen_display}. "
                        f"Would you like to add it to your order?"
                    ),
                    order=order,
                )
        else:
            # Asking about all allergens
            allergens = menu_cache.get_item_allergens(item_name)

            if not allergens:
                # Get all allergen properties from the info dict (keys starting with "contains_")
                allergen_props = [k for k in info.keys() if k.startswith("contains_")]

                # Check if we have any allergen data at all
                has_any_allergen_data = any(
                    info.get(prop) is not None for prop in allergen_props
                )

                if not has_any_allergen_data:
                    return StateMachineResult(
                        message=(
                            f"I don't have allergen information for {item_display_name}. "
                            f"Please check with the store directly for accurate allergen information. "
                            f"Can I help you with anything else?"
                        ),
                        order=order,
                    )

                # Build tracked allergens list dynamically from properties
                tracked_allergens = [_allergen_display_name(p) for p in allergen_props]
                tracked_list = ", ".join(tracked_allergens)

                return StateMachineResult(
                    message=(
                        f"{item_display_name} doesn't contain any of the common allergens we track "
                        f"({tracked_list}). "
                        f"Would you like to add it to your order?"
                    ),
                    order=order,
                )

            allergen_list = format_english_list(allergens)
            return StateMachineResult(
                message=(
                    f"{item_display_name} contains: {allergen_list}. "
                    f"Would you like me to suggest alternatives?"
                ),
                order=order,
            )

    def handle_allergen_free_options_inquiry(
        self,
        allergen_type: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about allergen-free options ("anything nut-free?").

        Args:
            allergen_type: The allergen property (e.g., "contains_nuts")
            order: Current order state

        Returns:
            StateMachineResult with allergen-free items
        """
        allergen_display = _allergen_display_name(allergen_type)

        # Convert to the "free" property name for cache lookup
        free_property = allergen_type.replace("contains_", "") + "_free"

        # Query cache for items without this allergen
        items = menu_cache.get_items_by_dietary_property(free_property)

        if not items:
            # Check if we have dietary data at all
            if not menu_cache.has_dietary_data():
                return StateMachineResult(
                    message=(
                        f"I don't have detailed allergen information available at the moment. "
                        f"I'd recommend checking with the store directly about {allergen_display}-free options. "
                        f"Is there anything else I can help you with?"
                    ),
                    order=order,
                )

            return StateMachineResult(
                message=(
                    f"I don't see any items specifically marked as {allergen_display}-free on our menu right now. "
                    f"Would you like me to tell you about our menu options?"
                ),
                order=order,
            )

        # Format the list of items
        item_names = [item.get("name", "Unknown") for item in items]

        items_list, new_offset = format_paginated_list(item_names, DEFAULT_PAGINATION_SIZE)
        if new_offset > 0:
            order.set_menu_pagination(f"allergen_{free_property}", new_offset, len(item_names))
        else:
            order.clear_menu_pagination()

        return StateMachineResult(
            message=f"Our {allergen_display}-free options include: {items_list}. Would you like any of these?",
            order=order,
        )

    def _search_category_items(self, term: str) -> list[dict]:
        """Search for menu items by category/display-group matching.

        Checks if the term matches a display group or category keyword,
        and returns the items belonging to that group.

        Args:
            term: Search term (e.g., "breakfast", "drinks")

        Returns:
            List of menu item dicts with at least a "name" key.
        """
        # Try display group first (e.g., "breakfast" -> display group -> item types)
        display_group = menu_cache.get_display_group_by_slug(term)
        if display_group:
            item_types = menu_cache.get_item_types_in_display_group(display_group["slug"])
            if item_types:
                items_by_type = self._menu_data.get("items_by_type", {})
                results = []
                for it_slug in item_types:
                    results.extend(items_by_type.get(it_slug, []))
                return results

        # Try category keyword mapping (e.g., "bagels" -> item_type or category)
        keyword_info = menu_cache.get_category_keyword_mapping(term)
        if keyword_info:
            slug = keyword_info.get("slug", "")
            lookup_type = keyword_info.get("lookup_type", "")
            if lookup_type == "category":
                return menu_cache.get_items_by_category(slug)
            elif lookup_type == "item_type":
                items_by_type = self._menu_data.get("items_by_type", {})
                return list(items_by_type.get(slug, []))

        return []

    def _handle_ingredient_items_search(
        self,
        ingredient_term: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Search for menu items containing a given ingredient and return a listing.

        Uses the ingredient_to_items mapping to find menu items that contain
        the specified ingredient. Mirrors the response format from
        TakingItemsHandler._handle_ingredient_search().

        Args:
            ingredient_term: The ingredient to search for (e.g., "ham", "bacon")
            order: Current order state

        Returns:
            StateMachineResult listing matching items, or None if no items found.
        """
        ingredient_to_items = self._menu_data.get("ingredient_to_items", {})
        matches = ingredient_to_items.get(ingredient_term.lower(), [])

        if not matches:
            return None

        if len(matches) == 1:
            item_name = matches[0].get("name", "that item")
            desc = matches[0].get("description", "")
            msg = f"For items with {ingredient_term}, we have the {item_name}"
            if desc:
                msg += f" ({desc})"
            msg += ". Would you like one?"
            order.pending_suggested_item = item_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
        else:
            display_count = min(6, len(matches))
            item_names = [m.get("name", "item") for m in matches[:display_count]]
            has_more = len(matches) > display_count

            if len(item_names) == 1:
                items_list = item_names[0]
            elif len(item_names) == 2:
                items_list = f"{item_names[0]} or {item_names[1]}"
            elif has_more:
                items_list = ", ".join(item_names)
                items_list += f", and {len(matches) - display_count} more"
            else:
                items_list = format_english_list(item_names, conjunction="or")

            msg = f"For items with {ingredient_term}, we have: {items_list}. Which would you like?"

            if has_more:
                order.pending_ingredient_search = {
                    "ingredient": ingredient_term,
                    "matches": matches,
                    "offset": display_count,
                }

        return StateMachineResult(message=msg, order=order)

    def handle_availability_inquiry(
        self,
        item_name: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about item availability ("do you have X in stock?").

        Args:
            item_name: The item user is asking about
            order: Current order state

        Returns:
            StateMachineResult with availability information
        """
        # Detect "something/anything with X" and list items containing that ingredient
        something_match = _SOMETHING_WITH_RE.search(item_name)
        if something_match:
            ingredient_term = something_match.group(1).strip()
            result = self._handle_ingredient_items_search(ingredient_term, order)
            if result:
                return result
            # Fall through to normal availability logic if no items found

        # Try exact alias resolution first
        canonical_name = menu_cache.resolve_menu_item_alias(item_name)

        if canonical_name:
            # Exact match found - set up pending state for "yes" confirmation
            order.pending_suggested_item = canonical_name
            order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
            return StateMachineResult(
                message=(
                    f"Yes, {canonical_name} is available! Would you like to add it to your order?"
                ),
                order=order,
            )

        # Fallback: word-boundary search (handles "tea" -> "Hot Tea", "Iced Tea")
        matching_items = menu_cache.search_menu_items_by_term(item_name)

        # Also search by category/display-group and merge results
        category_items = self._search_category_items(item_name)
        if category_items:
            seen_names = {item.get("name", "").lower() for item in matching_items}
            for item in category_items:
                name_lower = item.get("name", "").lower()
                if name_lower not in seen_names:
                    seen_names.add(name_lower)
                    matching_items.append(item)

        if matching_items:
            if len(matching_items) == 1:
                # Single match - set up pending state for "yes" confirmation
                item_display = matching_items[0].get("name", item_name)
                order.pending_suggested_item = item_display
                order.pending_field = PendingField.CONFIRM_SUGGESTED_ITEM
                return StateMachineResult(
                    message=(
                        f"Yes, we have {item_display}! Would you like to add it to your order?"
                    ),
                    order=order,
                )
            else:
                # Multiple matches - paginate
                item_names = [item.get("name", "") for item in matching_items]
                items_list, new_offset = format_paginated_list(
                    item_names, DEFAULT_PAGINATION_SIZE
                )
                if new_offset > 0:
                    order.menu_query_pagination = {
                        "type": "availability_items",
                        "items": item_names,
                        "offset": new_offset,
                    }
                else:
                    order.clear_menu_pagination()
                return StateMachineResult(
                    message=(
                        f"Yes! We have {items_list}. Would you like any of these?"
                    ),
                    order=order,
                )

        # Nothing found in menu items — check if the term matches a known ingredient
        ingredient_matches = menu_cache.find_matching_ingredients(item_name)
        if ingredient_matches:
            if len(ingredient_matches) == 1:
                ing = ingredient_matches[0]
                ing_name = ing.get("name", item_name)
                # Try listing menu items that contain this ingredient
                result = self._handle_ingredient_items_search(ing_name, order)
                if result:
                    return result
                # Fallback if no menu items found for this ingredient
                return StateMachineResult(
                    message=(
                        f"Yes, we have {ing_name}! Would you like to order something with {ing_name}?"
                    ),
                    order=order,
                )
            else:
                ing_names = [m.get("name", "") for m in ingredient_matches]
                items_list, new_offset = format_paginated_list(
                    ing_names, DEFAULT_PAGINATION_SIZE
                )
                if new_offset > 0:
                    order.menu_query_pagination = {
                        "type": "availability_items",
                        "items": ing_names,
                        "offset": new_offset,
                    }
                else:
                    order.clear_menu_pagination()
                return StateMachineResult(
                    message=(
                        f"Yes! We have {items_list}. Would you like any of these?"
                    ),
                    order=order,
                )

        # Nothing found - use unrecognized handler for curated suggestions
        if self._unrecognized_handler:
            message, category_slug = self._unrecognized_handler.get_not_found_response(
                item_name, order=order
            )
            if category_slug:
                order.pending_menu_category = category_slug
                order.pending_field = PendingField.CONFIRM_MENU_CATEGORY
            return StateMachineResult(message=message, order=order)

        # Fallback if no unrecognized handler
        return StateMachineResult(
            message=(
                f"I couldn't find \"{item_name}\" on our menu. "
                f"Would you like me to show you what we have?"
            ),
            order=order,
        )

    def handle_customization_inquiry(
        self,
        item_name: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about customization options ("can I customize X?").

        Args:
            item_name: The item user is asking about
            order: Current order state

        Returns:
            StateMachineResult with customization information
        """
        # Try to resolve the item name to get its item type
        canonical_name = menu_cache.resolve_menu_item_alias(item_name)

        if not canonical_name:
            return StateMachineResult(
                message=(
                    f"I couldn't find \"{item_name}\" on our menu. "
                    f"Would you like me to show you what we have?"
                ),
                order=order,
            )

        # Get the item type for this menu item
        item_type_slug = menu_cache.get_item_type_for_menu_item(canonical_name)

        if not item_type_slug:
            # Item exists but no item type - probably not customizable
            return StateMachineResult(
                message=(
                    f"{canonical_name} comes as-is and isn't customizable. "
                    f"Would you like to add it to your order?"
                ),
                order=order,
            )

        # Check if this item type is configurable (has ask_in_conversation attributes)
        configurable_types = menu_cache.get_configurable_item_type_slugs()

        if item_type_slug not in configurable_types:
            return StateMachineResult(
                message=(
                    f"{canonical_name} comes as-is. Would you like to add it to your order?"
                ),
                order=order,
            )

        # Get the attributes for this item type to describe customization options
        attrs = menu_cache.get_item_type_attributes(item_type_slug)

        if not attrs:
            return StateMachineResult(
                message=(
                    f"Yes, {canonical_name} can be customized! "
                    f"Just add it to your order and I'll ask you about the options."
                ),
                order=order,
            )

        # List the customizable attributes
        attr_names = []
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("ask_in_conversation"):
                display_name = attr_config.get("display_name", attr_slug.replace("_", " "))
                attr_names.append(display_name.lower())

        if attr_names:
            attrs_list = format_english_list(attr_names)
            return StateMachineResult(
                message=(
                    f"Yes! For {canonical_name}, you can customize: {attrs_list}. "
                    f"Would you like to add it to your order?"
                ),
                order=order,
            )

        return StateMachineResult(
            message=(
                f"Yes, {canonical_name} can be customized! "
                f"Just add it to your order and I'll walk you through the options."
            ),
            order=order,
        )
