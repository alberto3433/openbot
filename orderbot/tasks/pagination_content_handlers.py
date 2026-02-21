"""
Pagination Content Handlers.

Content-type-specific pagination handlers extracted from MenuPaginationHandler.
Handles pagination for ingredient searches, category queries, modifier items,
item types, attribute options, dietary items, availability items, and display groups.
"""

import logging
from typing import Callable, TYPE_CHECKING

from orderbot.cache import menu_cache

from .models import OrderTask
from .models.pending_states import PendingIngredientSearch
from .schemas import StateMachineResult
from .parsers.constants import DEFAULT_PAGINATION_SIZE
from .utils.text import format_english_list, normalize_text

if TYPE_CHECKING:
    from .menu_pagination_handler import MenuPaginationHandler

logger = logging.getLogger(__name__)


class PaginationContentHandlers:
    """Content-type-specific pagination handlers."""

    def __init__(self, parent: "MenuPaginationHandler"):
        self._parent = parent

    # ------------------------------------------------------------------
    # Shared pagination helper
    # ------------------------------------------------------------------

    def _paginate_and_respond(
        self,
        order: OrderTask,
        items: list[str],
        offset: int,
        *,
        pagination_base: dict,
        empty_message: str,
        more_message: str,
        done_message: str,
        qr_value_fn: Callable[[str], str] | None = None,
        conjunction: str = "and",
    ) -> StateMachineResult:
        """Shared pagination logic for all 'show more' handlers.

        Args:
            order: Current order state.
            items: Full list of item name strings.
            offset: Current offset into items.
            pagination_base: Base dict for pagination state (helper adds "offset").
            empty_message: Message when no items remain.
            more_message: Message template with ``{items}`` when more items exist.
            done_message: Message template with ``{items}`` for last batch.
            qr_value_fn: Optional transform for quick-reply values (default: name).
            conjunction: Word joining last item ("and" or "or").
        """
        if not items or offset >= len(items):
            order.clear_menu_pagination()
            return StateMachineResult(message=empty_message, order=order)

        batch = items[offset:offset + DEFAULT_PAGINATION_SIZE]
        remaining = len(items) - (offset + len(batch))
        has_more = remaining > 0

        if has_more:
            if conjunction == "and":
                items_str = ", ".join(batch) + f", and {remaining} more"
            else:
                items_str = (
                    format_english_list(batch, conjunction=conjunction)
                    + f", and {remaining} more"
                )
            order.menu_query_pagination = {
                **pagination_base,
                "offset": offset + DEFAULT_PAGINATION_SIZE,
            }
            message = more_message.format(items=items_str)
        else:
            items_str = format_english_list(batch, conjunction=conjunction)
            order.clear_menu_pagination()
            message = done_message.format(items=items_str)

        # Build quick replies
        if qr_value_fn:
            qr = [{"label": name, "value": qr_value_fn(name)} for name in batch]
        else:
            qr = [{"label": name, "value": name} for name in batch]
        if has_more:
            qr.append({"label": f"{remaining} more", "value": "what else?"})

        return StateMachineResult(message=message, order=order, quick_replies=qr)

    # ------------------------------------------------------------------
    # Handlers that do NOT use the shared helper
    # ------------------------------------------------------------------

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
            if self._parent.menu_inquiry_handler:
                if menu_type == "signature_items":
                    return self._parent.menu_inquiry_handler.handle_signature_menu_inquiry(menu_type, order)
                return self._parent.menu_inquiry_handler.handle_menu_query(menu_type, order)

        # Couldn't map to a known category - try a generic lookup
        logger.info("Category '%s' not in database aliases, trying generic lookup", category)
        if self._parent.menu_inquiry_handler:
            return self._parent.menu_inquiry_handler.handle_menu_query(category_lower, order)

        # Fallback if no menu_inquiry_handler
        return StateMachineResult(
            message=f"I'm not sure what {category} items we have. What else can I help you with?",
            order=order,
        )

    # ------------------------------------------------------------------
    # Handlers that use the shared helper
    # ------------------------------------------------------------------

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
        items_list = self._parent._normalize_modifier_items(items_set, category)

        return self._paginate_and_respond(
            order, items_list, offset,
            pagination_base={"category": category, "total_items": len(items_list)},
            empty_message="That's all we have. Would you like anything?",
            more_message="We also have {items}. Would you like any of these?",
            done_message="We also have {items}. That's all we have. Would you like any?",
        )

    def _handle_more_item_types(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for item type suggestions (from 'what do you recommend?')."""
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)

        return self._paginate_and_respond(
            order, items, offset,
            pagination_base={"type": "item_types", "items": items},
            empty_message="That's everything we have. What would you like to order?",
            more_message="We also have {items}. Would you like any of these?",
            done_message="We also have {items}. That's everything! What would you like?",
            qr_value_fn=lambda n: f"What {n.lower()} do you have?",
        )

    def _handle_more_attribute_options(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for attribute options (from 'what bagel types?' response)."""
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        attr_display = pagination.get("attribute_display", "options")

        return self._paginate_and_respond(
            order, items, offset,
            pagination_base={
                "type": "attribute_options",
                "attribute_slug": pagination.get("attribute_slug"),
                "attribute_display": attr_display,
                "item_type": pagination.get("item_type"),
                "items": items,
            },
            empty_message=f"That's all the {attr_display} we have. Would you like to order something?",
            more_message="We also have {items}. Would you like any of these?",
            done_message=f"We also have {{items}}. That's all the {attr_display} we have. Would you like any?",
        )

    def _handle_more_dietary_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for dietary item results (from 'what vegan options?' response)."""
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        dietary_display = pagination.get("dietary_display", "dietary")
        category = pagination.get("category")
        category_suffix = f" {category}" if category else " options"

        return self._paginate_and_respond(
            order, items, offset,
            pagination_base={
                "type": "dietary_items",
                "dietary_type": pagination.get("dietary_type"),
                "dietary_display": dietary_display,
                "category": category,
                "items": items,
            },
            empty_message=f"That's all the {dietary_display}{category_suffix} we have. Would you like to order something?",
            more_message="We also have {items}. Would you like any of these?",
            done_message=f"We also have {{items}}. That's all the {dietary_display}{category_suffix} we have. Would you like any?",
        )

    def _handle_more_availability_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for availability inquiry results."""
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)

        return self._paginate_and_respond(
            order, items, offset,
            pagination_base={"type": "availability_items", "items": items},
            empty_message="That's everything we have. Would you like to order something?",
            more_message="We also have {items}. Would you like any of these?",
            done_message="We also have {items}. That's all we have. Would you like any of these?",
        )

    def _handle_more_display_group_items(
        self,
        order: OrderTask,
        pagination: dict,
    ) -> StateMachineResult:
        """Handle 'show more' for display group items (from 'can I get a sandwich?' response)."""
        items = pagination.get("items", [])
        offset = pagination.get("offset", 0)
        display_group = pagination.get("display_group", "items")

        return self._paginate_and_respond(
            order, items, offset,
            pagination_base={
                "type": "display_group_items",
                "display_group": display_group,
                "items": items,
            },
            empty_message="That's all we have. Would you like to order something?",
            more_message="We also have {items}. Would you like any of these?",
            done_message="We also have {items}. That's all we have. Would you like any of these?",
            conjunction="or",
        )
