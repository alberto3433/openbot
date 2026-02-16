"""
Price Inquiry Handler.

Handles price-related questions from customers.
Extracted from menu_inquiry_handler.py for better separation of concerns.
"""

import logging

from orderbot.cache import menu_cache

from .models import OrderTask
from .schemas import StateMachineResult
from .utils.text import format_english_list

logger = logging.getLogger(__name__)


class PriceInquiryHandler:
    """Handles price inquiry requests."""

    def handle_price_inquiry(
        self,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle price inquiry for a specific item.

        Uses the data-driven resolve_price_inquiry() method from menu_cache
        to look up prices for items, categories, and modifiers.

        Args:
            item_query: The item the user is asking about (e.g., 'sesame bagel', 'lox')
            order: Current order state

        Returns:
            StateMachineResult with the price information
        """
        if not item_query:
            return StateMachineResult(
                message="What would you like to know the price of?",
                order=order,
            )

        # Extract context from order state
        current_item_type = None
        pending_item = order.get_pending_item() if hasattr(order, 'get_pending_item') else None
        if pending_item:
            current_item_type = getattr(pending_item, 'menu_item_type', None)

        last_menu_category = None
        pagination = order.get_menu_pagination() if hasattr(order, 'get_menu_pagination') else None
        if pagination:
            last_menu_category = pagination.get("category")

        # Use the unified data-driven lookup
        context = {
            "current_item_type": current_item_type,
            "last_menu_category": last_menu_category,
        }
        result = menu_cache.resolve_price_inquiry(query=item_query, context=context)

        result_type = result.get("type")

        if result_type == "category":
            return self._format_category_price_response(result, item_query, order)

        if result_type == "item":
            name = result.get("name", item_query)
            price = result.get("price", 0)
            return StateMachineResult(
                message=f"{name} is ${price:.2f}. Would you like one?",
                order=order,
            )

        if result_type == "sized_item":
            return self._format_sized_item_price_response(result, item_query, order)

        if result_type == "modifier":
            return self._format_modifier_price_response(result, item_query, order)

        if result_type == "needs_clarification":
            return self._format_clarification_response(result, item_query, order)

        # result_type == "not_found"
        return StateMachineResult(
            message=f"I'm not sure about the price for '{item_query}'. Is there something else I can help you with?",
            order=order,
        )

    def _format_category_price_response(
        self,
        result: dict,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format response for category price inquiry."""
        display_name = result.get("display_name", item_query)
        min_price = result.get("min_price", 0)
        items = result.get("items", [])

        # If there are multiple named items in the category, ask which kind
        if items and len(items) > 1:
            # Show a few examples
            examples = items[:3]
            examples_str = ", ".join(examples)
            return StateMachineResult(
                message=f"We have several kinds of {display_name} including {examples_str}. What kind of {display_name.rstrip('s')} would you like?",
                order=order,
            )

        return StateMachineResult(
            message=f"Our {display_name} start at ${min_price:.2f}. Would you like one?",
            order=order,
        )

    def _format_sized_item_price_response(
        self,
        result: dict,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format response for sized item price inquiry."""
        name = result.get("name", item_query)
        sizes = result.get("sizes", [])

        if sizes:
            # Format size options
            size_strs = [
                f"{s.get('size_name', 'Unknown')} ${s.get('price', 0):.2f}"
                for s in sizes
            ]
            sizes_text = ", ".join(size_strs)
            return StateMachineResult(
                message=f"{name} comes in: {sizes_text}. What size would you like?",
                order=order,
            )

        # Fallback if no sizes (shouldn't happen)
        return StateMachineResult(
            message=f"{name} pricing varies by size. What size would you like?",
            order=order,
        )

    def _format_modifier_price_response(
        self,
        result: dict,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format response for modifier price inquiry."""
        name = result.get("name", item_query)
        price = result.get("price", 0)
        context = result.get("context", "")

        if price > 0:
            return StateMachineResult(
                message=f"{name} is ${price:.2f} as a {context}. Would you like to add it?",
                order=order,
            )
        else:
            return StateMachineResult(
                message=f"{name} is included at no extra charge. Would you like to add it?",
                order=order,
            )

    def _format_clarification_response(
        self,
        result: dict,
        item_query: str,
        order: OrderTask,
    ) -> StateMachineResult:
        """Format response when clarification is needed."""
        name = result.get("name", item_query)
        contexts = result.get("contexts", [])

        # Format the options for clarification
        options = []
        for ctx in contexts:
            label = ctx.get("label", "")
            price = ctx.get("price", 0)
            if price > 0:
                options.append(f"{label} (${price:.2f})")
            else:
                options.append(f"{label} (included)")

        options_text = format_english_list(options, conjunction="or")

        # Build quick replies from context labels
        qr = [{"label": ctx.get("label", ""), "value": ctx.get("label", "")} for ctx in contexts if ctx.get("label")]
        return StateMachineResult(
            message=f"Are you asking about {name} as {options_text}?",
            order=order,
            quick_replies=qr,
        )
