from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .utils.text import format_english_list, format_paginated_list, name_with_prefix
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .models.pending_states import PendingIngredientSearch
from .pending_fields import PendingField

if TYPE_CHECKING:
    from .dietary_inquiry_handler import DietaryInquiryHandler

logger = logging.getLogger(__name__)

# Pattern to detect "something/anything with X" in availability queries
_SOMETHING_WITH_RE = re.compile(
    r"(?:something|anything|items?|stuff)\s+with\s+(.+)",
    re.IGNORECASE,
)


class AvailabilityOperations:

    def __init__(self, parent: DietaryInquiryHandler):
        self._parent = parent

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
                has_more = new_offset > 0
                batch = item_names[:DEFAULT_PAGINATION_SIZE]
                remaining = len(item_names) - len(batch)
                if has_more:
                    order.menu_query_pagination = {
                        "type": "availability_items",
                        "items": item_names,
                        "offset": new_offset,
                    }
                else:
                    order.clear_menu_pagination()

                qr = [{"label": name, "value": name} for name in batch]
                if has_more:
                    qr.append({"label": f"{remaining} more", "value": "what else?"})

                # Store shown items so selection responses ("I'll take one")
                # route through handle_item_selection.
                batch_items = matching_items[:DEFAULT_PAGINATION_SIZE]
                order.pending_item_options = batch_items
                order.pending_field = PendingField.ITEM_SELECTION

                return StateMachineResult(
                    message=(
                        f"Yes! We have {items_list}. Would you like any of these?"
                    ),
                    order=order,
                    quick_replies=qr,
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
                has_more = new_offset > 0
                batch = ing_names[:DEFAULT_PAGINATION_SIZE]
                remaining = len(ing_names) - len(batch)
                if has_more:
                    order.menu_query_pagination = {
                        "type": "availability_items",
                        "items": ing_names,
                        "offset": new_offset,
                    }
                else:
                    order.clear_menu_pagination()

                qr = [{"label": name, "value": name} for name in batch]
                if has_more:
                    qr.append({"label": f"{remaining} more", "value": "what else?"})

                return StateMachineResult(
                    message=(
                        f"Yes! We have {items_list}. Would you like any of these?"
                    ),
                    order=order,
                    quick_replies=qr,
                )

        # Nothing found - use unrecognized handler for curated suggestions
        if self._parent._unrecognized_handler:
            message, category_slug, qr = self._parent._unrecognized_handler.get_not_found_response(
                item_name, order=order
            )
            if category_slug:
                order.pending_field = PendingField.CATEGORY_INQUIRY
                order.pending_config_queue = [category_slug]
            return StateMachineResult(message=message, order=order, quick_replies=qr or None)

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
                items_by_type = self._parent._menu_data.get("items_by_type", {})
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
                items_by_type = self._parent._menu_data.get("items_by_type", {})
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
        ingredient_to_items = self._parent._menu_data.get("ingredient_to_items", {})
        matches = ingredient_to_items.get(ingredient_term.lower(), [])

        if not matches:
            return None

        if len(matches) == 1:
            item_name = matches[0].get("name", "that item")
            desc = matches[0].get("description", "")
            msg = f"For items with {ingredient_term}, we have {name_with_prefix('the', item_name)}"
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
                order.pending_ingredient_search = PendingIngredientSearch(
                    ingredient=ingredient_term,
                    matches=matches,
                    offset=display_count,
                )

        # Build quick replies for inline clickable text
        if len(matches) == 1:
            qr = [{"label": item_name, "value": item_name}]
        else:
            qr = [{"label": name, "value": name} for name in item_names]
            if has_more:
                qr.append({"label": f"{len(matches) - display_count} more", "value": "what else?"})
        return StateMachineResult(message=msg, order=order, quick_replies=qr)
