"""Menu Display Handler - Item descriptions and signature menu inquiries."""

import logging
from typing import TYPE_CHECKING

from orderbot.cache.base import pluralize

from .models import OrderTask
from .pending_fields import PendingField
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .utils.text import format_english_list, normalize_text
from .category_resolver import get_available_menu_categories_message

if TYPE_CHECKING:
    from .menu_inquiry_handler import MenuInquiryHandler

logger = logging.getLogger(__name__)


class MenuDisplayHandler:
    """Handles item description and signature menu inquiries."""

    def __init__(self, parent: "MenuInquiryHandler"):
        self._parent = parent

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
        item_descriptions = self._parent.menu_data.get("item_descriptions", {}) if self._parent.menu_data else {}

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
            if self._parent.menu_data:
                items_by_type = self._parent.menu_data.get("items_by_type", {})
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
            available_categories = get_available_menu_categories_message()
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
        items_by_type = self._parent.menu_data.get("items_by_type", {}) if self._parent.menu_data else {}

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
