from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .utils.text import format_english_list, format_paginated_list
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .models.pending_states import PendingDietaryFollowup
from .pending_fields import PendingField

if TYPE_CHECKING:
    from .dietary_inquiry_handler import DietaryInquiryHandler

logger = logging.getLogger(__name__)


# Human-readable names for dietary properties
DIETARY_DISPLAY_NAMES = {
    "is_vegan": "vegan",
    "is_vegetarian": "vegetarian",
    "is_gluten_free": "gluten-free",
    "is_dairy_free": "dairy-free",
    "is_kosher": "kosher",
}


def _allergen_display_name(allergen_type: str) -> str:
    """Derive display name from allergen property (e.g., 'contains_eggs' -> 'eggs')."""
    return allergen_type.replace("contains_", "")


class DietaryOperations:

    def __init__(self, parent: DietaryInquiryHandler):
        self._parent = parent

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
            item_type_slugs = self._parent._resolve_category_to_item_types(category)
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
                # Set pending state so "yes" routes back to show all dietary options
                order.pending_dietary_followup = PendingDietaryFollowup(
                    dietary_type=dietary_type,
                    category=None,
                )
                order.pending_field = PendingField.CONFIRM_DIETARY_FOLLOWUP
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
        has_more = new_offset > 0
        batch = item_names[:DEFAULT_PAGINATION_SIZE]
        remaining = len(item_names) - len(batch)
        if has_more:
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

        # Build quick replies for inline clickable text
        from .handler_utils import build_quick_replies
        qr = build_quick_replies(batch)
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        # Build response message
        if category_display:
            return StateMachineResult(
                message=f"Our {display_name} {category_display} include: {items_list}. Would you like any of these?",
                order=order,
                quick_replies=qr,
            )

        return StateMachineResult(
            message=f"Our {display_name} options include: {items_list}. Would you like any of these?",
            order=order,
            quick_replies=qr,
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
            order.pending_dietary_followup = PendingDietaryFollowup(
                dietary_type=dietary_type,
                category=None,
            )
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
        has_more = new_offset > 0
        batch = item_names[:DEFAULT_PAGINATION_SIZE]
        remaining = len(item_names) - len(batch)
        if has_more:
            order.set_menu_pagination(f"allergen_{free_property}", new_offset, len(item_names))
        else:
            order.clear_menu_pagination()

        # Build quick replies for inline clickable text
        from .handler_utils import build_quick_replies
        qr = build_quick_replies(batch)
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(
            message=f"Our {allergen_display}-free options include: {items_list}. Would you like any of these?",
            order=order,
            quick_replies=qr,
        )
