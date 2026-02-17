"""
Order History Handler for Order State Machine.

This module handles order history viewing and reorder intents including:
- "What did I order before?" - Show order history list
- "What was in my last order?" - Show last order details
- "Just the bagel from last time" - Reorder specific item from history
- "Repeat my order but iced" - Reorder with modifications
"""

import logging
import re
from typing import TYPE_CHECKING

from .models import OrderTask, MenuItemTask
from .models.pending_states import PendingOrderHistory
from .pending_fields import PendingField
from .schemas import StateMachineResult, OrderPhase
from .parsers.inquiry_patterns import (
    ORDER_HISTORY_PATTERNS,
    VIEW_LAST_ORDER_PATTERNS,
    REORDER_ITEM_PATTERNS,
    MODIFICATION_EXTRACTOR,
    WITHOUT_PATTERN,
    get_reorder_modification_keywords,
    ORDER_NUMBER_PATTERN,
)
from .mixins import ContextMixin, MenuDataMixin
from .utils.text import normalize_text, parse_selection
from ..cache import menu_cache

if TYPE_CHECKING:
    from .context import OrderContext
    from .checkout_handler import CheckoutHandler
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Response templates
RESPONSES = {
    "history_list": "Here are your recent orders:\n{order_list}\nWhich would you like to reorder, or say a number for details?",
    "history_single": "Your last order on {date} was {summary}. Would you like that again?",
    "no_history": "I don't have any previous orders for your number. What can I get for you today?",
    "order_details": "Your order from {date} had: {items}. Total was ${total:.2f}. Want to reorder it?",
    "reorder_success": "Got it! I've added {summary} from your previous order. Anything else?",
    "reorder_modified": "I've added your previous order {modification_desc}. Anything else?",
    "item_unavailable": "The {item} from your last order isn't available right now. Would you like the rest?",
    "item_not_found": "I couldn't find '{item_ref}' in your previous orders. Want me to show your order history?",
    "multiple_matches": "I see you had a few {item_type}s in your past orders. Which one would you like?",
    "price_changed": "Just so you know, the {item} is now ${new_price:.2f} (was ${old_price:.2f}). I've added it.",
    "old_order": "I can only see the last 90 days of orders. What can I get for you today?",
    "no_phone": "I need your phone number to look up order history. What can I get for you today?",
}


class OrderHistoryHandler(ContextMixin, MenuDataMixin):
    """
    Handles order history viewing and reorder intents.

    Manages:
    - Order history inquiry
    - Last order details viewing
    - Reorder specific items from history
    - Reorder with modifications
    """

    def __init__(
        self,
        checkout_handler: "CheckoutHandler | None" = None,
    ) -> None:
        """Initialize the order history handler.

        Args:
            checkout_handler: Handler for checkout operations (repeat order).
        """
        self.checkout_handler = checkout_handler

        # ContextMixin attributes
        self._returning_customer: dict | None = None
        self._is_repeat_order: bool = False
        self._last_order_type: str | None = None
        self._store_info: dict | None = None

        # MenuDataMixin attributes
        self._menu_data: dict = {}

        # Database session (set per-request)
        self._db_session: "Session | None" = None

        # Callbacks
        self._set_repeat_info_callback = None

    def set_context(self, ctx: "OrderContext") -> None:
        """Set per-request context from unified OrderContext."""
        self._store_info = ctx.store_info
        self._returning_customer = ctx.returning_customer
        self._is_repeat_order = ctx.is_repeat_order
        self._last_order_type = ctx.last_order_type
        self._db_session = ctx.db_session
        self._set_repeat_info_callback = ctx.set_repeat_info_callback
        if ctx.menu_data:
            self._menu_data = ctx.menu_data

    # =========================================================================
    # Intent Detection
    # =========================================================================

    def is_order_history_inquiry(self, user_input: str) -> bool:
        """Check if user is asking to see their order history."""
        text = user_input.strip()
        return any(pattern.search(text) for pattern in ORDER_HISTORY_PATTERNS)

    def is_view_last_order(self, user_input: str) -> bool:
        """Check if user is asking to see details of their last order."""
        text = user_input.strip()
        return any(pattern.search(text) for pattern in VIEW_LAST_ORDER_PATTERNS)

    def is_reorder_specific_item(self, user_input: str) -> tuple[bool, str | None]:
        """Check if user wants to reorder a specific item from history.

        Returns:
            Tuple of (is_match, item_reference_or_None)
        """
        text = user_input.strip()
        for pattern in REORDER_ITEM_PATTERNS:
            match = pattern.search(text)
            if match:
                # Get first non-None group
                item_ref = next((g for g in match.groups() if g), None)
                return True, item_ref
        return False, None

    def is_reorder_with_modifications(self, user_input: str) -> tuple[bool, str | None]:
        """Check if user wants to repeat order with modifications.

        Returns:
            Tuple of (is_match, modification_text_or_None)
        """
        text = user_input.strip()
        match = MODIFICATION_EXTRACTOR.search(text)
        if match:
            return True, match.group(1)
        return False, None

    def is_order_number_reference(self, user_input: str) -> tuple[bool, int | None]:
        """Check if user references a specific order number.

        Returns:
            Tuple of (is_match, order_number_or_None)
        """
        text = user_input.strip()
        match = ORDER_NUMBER_PATTERN.search(text)
        if match:
            return True, int(match.group(1))
        return False, None

    # =========================================================================
    # Main Handlers
    # =========================================================================

    def handle_order_history_inquiry(
        self,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'What did I order before?' - Show order history list.

        Args:
            order: The current order task.

        Returns:
            StateMachineResult with order history or error message.
        """
        # Get phone from returning customer or order
        phone = self._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=RESPONSES["no_phone"],
                order=order,
            )

        # Get order history
        history = self._get_order_history(phone)
        if not history or not history.get("orders"):
            return StateMachineResult(
                message=RESPONSES["no_history"],
                order=order,
            )

        orders = history["orders"]

        # Single order case
        if len(orders) == 1:
            order_data = orders[0]
            date_str = self._format_order_date(order_data["order_date"])
            return StateMachineResult(
                message=RESPONSES["history_single"].format(
                    date=date_str,
                    summary=order_data["summary"],
                ),
                order=order,
            )

        # Multiple orders - show list
        order_list = []
        for i, order_data in enumerate(orders[:5], 1):  # Show max 5
            date_str = self._format_order_date(order_data["order_date"])
            total = order_data.get("total_price", 0)
            order_list.append(f"{i}. {date_str}: {order_data['summary']} (${total:.2f})")

        # Store order history for selection
        order.pending_order_history = PendingOrderHistory(
            orders=orders[:5],
        )
        order.pending_field = PendingField.ORDER_HISTORY_SELECTION

        # Build quick replies from order summaries
        qr = [{"label": od["summary"], "value": od["summary"]} for od in orders[:5] if od.get("summary")]
        return StateMachineResult(
            message=RESPONSES["history_list"].format(order_list="\n".join(order_list)),
            order=order,
            quick_replies=qr,
        )

    def handle_view_last_order(
        self,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'What was in my last order?' - Show last order details.

        Args:
            order: The current order task.

        Returns:
            StateMachineResult with order details or error message.
        """
        phone = self._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=RESPONSES["no_phone"],
                order=order,
            )

        # Use returning_customer data if available (already has last order)
        if self._returning_customer and self._returning_customer.get("last_order_items"):
            items = self._returning_customer["last_order_items"]
            date_str = self._format_order_date(
                self._returning_customer.get("last_order_date")
            )

            # Build items description
            items_desc = self._format_items_for_display(items)

            # Calculate total from items
            total = sum(
                item.get("price", 0) * item.get("quantity", 1)
                for item in items
            )

            # Store items for potential reorder and set pending field
            order.pending_reorder_offer_items = items
            order.pending_field = PendingField.REORDER_OFFER_CONFIRMATION

            return StateMachineResult(
                message=RESPONSES["order_details"].format(
                    date=date_str,
                    items=items_desc,
                    total=total,
                ),
                order=order,
            )

        # Fall back to fetching from DB
        history = self._get_order_history(phone, limit=1)
        if not history or not history.get("orders"):
            return StateMachineResult(
                message=RESPONSES["no_history"],
                order=order,
            )

        order_data = history["orders"][0]
        date_str = self._format_order_date(order_data["order_date"])
        items_desc = self._format_items_for_display(order_data["items"])

        # Store items for potential reorder and set pending field
        order.pending_reorder_offer_items = order_data.get("items", [])
        order.pending_field = PendingField.REORDER_OFFER_CONFIRMATION

        return StateMachineResult(
            message=RESPONSES["order_details"].format(
                date=date_str,
                items=items_desc,
                total=order_data.get("total_price", 0),
            ),
            order=order,
        )

    def handle_reorder_specific_item(
        self,
        item_ref: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'Just the bagel from last time' - Add specific item from history.

        Args:
            item_ref: The item reference from user input (e.g., "bagel", "coffee").
            order: The current order task.

        Returns:
            StateMachineResult with confirmation or error message.
        """
        phone = self._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=RESPONSES["no_phone"],
                order=order,
            )

        # Get items from returning customer or fetch history
        items = []
        if self._returning_customer and self._returning_customer.get("last_order_items"):
            items = self._returning_customer["last_order_items"]
        else:
            history = self._get_order_history(phone, limit=1)
            if history and history.get("orders"):
                items = history["orders"][0].get("items", [])

        if not items:
            return StateMachineResult(
                message=RESPONSES["no_history"],
                order=order,
            )

        # Find matching items
        item_ref_lower = normalize_text(item_ref)
        matching_items = []
        for item in items:
            name = item.get("menu_item_name", "").lower()
            item_type = item.get("item_type", "").lower()
            # Match by name or item type
            if item_ref_lower in name or item_ref_lower in item_type:
                matching_items.append(item)

        if not matching_items:
            return StateMachineResult(
                message=RESPONSES["item_not_found"].format(item_ref=item_ref),
                order=order,
            )

        if len(matching_items) == 1:
            # Single match - add it
            item_data = matching_items[0]
            return self._add_item_from_history(item_data, order)

        # Multiple matches - ask for clarification
        item_names = [item.get("menu_item_name", "item") for item in matching_items]
        order.pending_reorder_items = matching_items
        order.pending_field = PendingField.REORDER_ITEM_SELECTION

        qr = [{"label": name, "value": name} for name in item_names]
        return StateMachineResult(
            message=RESPONSES["multiple_matches"].format(item_type=item_ref)
            + f" {', '.join(item_names)}?",
            order=order,
            quick_replies=qr,
        )

    def handle_reorder_with_modifications(
        self,
        modification_text: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle 'Repeat my order but iced' - Reorder with modifications.

        Args:
            modification_text: The modification text (e.g., "iced", "without the bagel").
            order: The current order task.

        Returns:
            StateMachineResult with confirmation or error message.
        """
        phone = self._get_customer_phone(order)
        if not phone:
            return StateMachineResult(
                message=RESPONSES["no_phone"],
                order=order,
            )

        # Get items to reorder
        items = []
        if self._returning_customer and self._returning_customer.get("last_order_items"):
            items = self._returning_customer["last_order_items"]
        else:
            history = self._get_order_history(phone, limit=1)
            if history and history.get("orders"):
                items = history["orders"][0].get("items", [])

        if not items:
            return StateMachineResult(
                message=RESPONSES["no_history"],
                order=order,
            )

        # Apply modifications
        modified_items, description = self.apply_modifications(items, modification_text)

        if not modified_items:
            return StateMachineResult(
                message="After that modification, there are no items left. What can I get you?",
                order=order,
            )

        # Add modified items to order
        items_added = []
        for item_data in modified_items:
            self._add_item_from_history(item_data, order, silent=True)
            items_added.append(item_data.get("menu_item_name", "item"))

        items_str = ", ".join(items_added)
        return StateMachineResult(
            message=RESPONSES["reorder_modified"].format(
                modification_desc=f"({description}): {items_str}"
            ),
            order=order,
        )

    def handle_order_history_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user's response to order history list.

        Args:
            user_input: The user's response (e.g., "1", "the first one", "repeat order 2").
            order: The current order task.

        Returns:
            StateMachineResult with appropriate action.
        """
        pending_history = order.pending_order_history
        if not pending_history:
            order.clear_pending()
            return None

        orders = pending_history.orders
        # Try to parse order selection
        selected_idx = parse_selection(user_input, len(orders))

        if selected_idx is not None and 0 <= selected_idx < len(orders):
            # User selected an order - add its items
            selected_order = orders[selected_idx]
            order.clear_pending()

            items = selected_order.get("items", [])
            if not items:
                return StateMachineResult(
                    message="That order doesn't have any items. What can I get you?",
                    order=order,
                )

            # Add all items from selected order
            items_added = []
            for item_data in items:
                self._add_item_from_history(item_data, order, silent=True)
                qty = item_data.get("quantity", 1)
                name = item_data.get("menu_item_name", "item")
                if qty > 1:
                    items_added.append(f"{qty} {name}s")
                else:
                    items_added.append(name)

            items_str = ", ".join(items_added)
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message=RESPONSES["reorder_success"].format(summary=items_str),
                order=order,
            )

        # Didn't understand - repeat the question
        order_list = []
        for i, order_data in enumerate(orders[:5], 1):
            date_str = self._format_order_date(order_data["order_date"])
            order_list.append(f"{i}. {date_str}: {order_data['summary']}")

        # Build quick replies from order summaries
        qr = [{"label": od["summary"], "value": od["summary"]} for od in orders[:5] if od.get("summary")]
        return StateMachineResult(
            message=f"I didn't catch that. Which order would you like?\n"
            + "\n".join(order_list),
            order=order,
            quick_replies=qr,
        )

    def handle_reorder_item_selection(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user's response to reorder item clarification.

        Args:
            user_input: The user's response.
            order: The current order task.

        Returns:
            StateMachineResult with appropriate action.
        """
        pending_items = order.pending_reorder_items
        if not pending_items:
            order.pending_field = None
            return None

        text_lower = user_input.strip().lower()

        # Try to match by name
        for item in pending_items:
            name = item.get("menu_item_name", "").lower()
            if text_lower in name or name in text_lower:
                order.clear_pending()
                return self._add_item_from_history(item, order)

        # Try ordinal (1, 2, first, second, etc.)
        selected_idx = parse_selection(user_input, len(pending_items))
        if selected_idx is not None and 0 <= selected_idx < len(pending_items):
            order.clear_pending()
            return self._add_item_from_history(pending_items[selected_idx], order)

        # Didn't understand
        item_names = [item.get("menu_item_name", "item") for item in pending_items]
        qr = [{"label": name, "value": name} for name in item_names]
        return StateMachineResult(
            message=f"I didn't catch that. Which one would you like: {', '.join(item_names)}?",
            order=order,
            quick_replies=qr,
        )

    def handle_reorder_offer_response(
        self,
        user_input: str,
        order: OrderTask,
    ) -> StateMachineResult | None:
        """Handle user's yes/no response to 'Want to reorder it?' offer.

        Args:
            user_input: The user's response (e.g., "yes", "no", "sure").
            order: The current order task.

        Returns:
            StateMachineResult with appropriate action.
        """
        from .response_utils import is_affirmative, is_negative

        pending_items = order.pending_reorder_offer_items
        if not pending_items:
            order.clear_pending()
            return None

        text_lower = user_input.strip().lower()

        # Check for affirmative response
        if is_affirmative(text_lower):
            order.clear_pending()

            # Add all items from pending offer
            items_added = []
            for item_data in pending_items:
                self._add_item_from_history(item_data, order, silent=True)
                qty = item_data.get("quantity", 1)
                name = item_data.get("menu_item_name", "item")
                if qty > 1:
                    items_added.append(f"{qty} {name}s")
                else:
                    items_added.append(name)

            items_str = ", ".join(items_added)
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message=RESPONSES["reorder_success"].format(summary=items_str),
                order=order,
            )

        # Check for negative response
        if is_negative(text_lower):
            order.clear_pending()
            order.set_phase(OrderPhase.TAKING_ITEMS)

            return StateMachineResult(
                message="No problem! What can I get for you today?",
                order=order,
            )

        # Didn't understand - clear pending state and fall through to normal processing
        order.clear_pending()
        return None

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_customer_phone(self, order: OrderTask) -> str | None:
        """Get customer phone from returning_customer or order."""
        if self._returning_customer:
            return self._returning_customer.get("phone")
        if order.customer_info and order.customer_info.phone:
            return order.customer_info.phone
        return None

    def _get_order_history(
        self,
        phone: str,
        days: int = 90,
        limit: int = 10,
    ) -> dict | None:
        """Get order history from database.

        Falls back to returning_customer data if no DB session.
        """
        if self._db_session:
            from ..services.customer_service import lookup_customer_order_history
            return lookup_customer_order_history(
                self._db_session, phone, days=days, limit=limit
            )

        # Fallback: construct from returning_customer
        if self._returning_customer:
            items = self._returning_customer.get("last_order_items", [])
            if items:
                from ..services.helpers import build_order_items_summary
                summary = build_order_items_summary(items)

                return {
                    "customer": {
                        "name": self._returning_customer.get("name"),
                        "phone": self._returning_customer.get("phone"),
                        "email": self._returning_customer.get("email"),
                    },
                    "order_count": self._returning_customer.get("order_count", 1),
                    "orders": [{
                        "order_id": self._returning_customer.get("last_order_id"),
                        "order_date": self._returning_customer.get("last_order_date"),
                        "order_type": self._returning_customer.get("last_order_type"),
                        "items": items,
                        "total_price": sum(
                            item.get("price", 0) * item.get("quantity", 1)
                            for item in items
                        ),
                        "summary": summary,
                    }],
                }
        return None

    def _format_order_date(self, date_str: str | None) -> str:
        """Format order date for display."""
        if not date_str:
            return "unknown date"
        try:
            from datetime import datetime
            if isinstance(date_str, str):
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            else:
                dt = date_str
            return dt.strftime("%b %d")  # e.g., "Jan 15"
        except (ValueError, AttributeError):
            return "unknown date"

    def _format_items_for_display(self, items: list) -> str:
        """Format items list for display."""
        parts = []
        for item in items:
            qty = item.get("quantity", 1)
            name = item.get("menu_item_name", "item")
            if qty > 1:
                parts.append(f"{qty}x {name}")
            else:
                parts.append(name)
        return ", ".join(parts) if parts else "no items"

    def apply_modifications(
        self,
        items: list,
        modification_text: str,
    ) -> tuple[list, str]:
        """Apply modifications like 'but iced', 'without bagel' to items.

        Args:
            items: List of item dicts from order history.
            modification_text: The modification text (e.g., "iced", "without the bagel").

        Returns:
            Tuple of (modified_items, description_of_changes)
        """
        text_lower = modification_text.lower()
        modifications = []
        items_to_remove = []

        # Check for "without X" - remove item
        without_match = WITHOUT_PATTERN.search(text_lower)
        if without_match:
            item_to_remove = without_match.group(1).strip()
            items_to_remove.append(item_to_remove)

        # Check for attribute modifications (built dynamically from cache)
        for keyword, (attr, value) in get_reorder_modification_keywords().items():
            if keyword in text_lower:
                modifications.append((attr, value))

        # Apply modifications
        modified_items = []
        description_parts = []

        for item in items:
            item_name = item.get("menu_item_name", "").lower()

            # Check if item should be removed
            should_remove = any(
                remove_term in item_name
                for remove_term in items_to_remove
            )
            if should_remove:
                description_parts.append(f"without {item.get('menu_item_name', 'item')}")
                continue

            # Copy item and apply attribute modifications
            modified_item = item.copy()
            if "attribute_values" in modified_item and modified_item["attribute_values"]:
                modified_item["attribute_values"] = modified_item["attribute_values"].copy()
            else:
                modified_item["attribute_values"] = {}

            for attr, value in modifications:
                # Apply to attribute_values
                modified_item["attribute_values"][attr] = value
                # Also set at top level for legacy compatibility
                modified_item[attr] = value

            modified_items.append(modified_item)

        # Build description using generic attribute formatting
        if modifications:
            mod_descs = []
            for attr, value in modifications:
                if isinstance(value, bool):
                    # Boolean: show slug if True, "not {slug}" if False
                    mod_descs.append(attr if value else f"not {attr}")
                else:
                    # Non-boolean: show the value directly
                    mod_descs.append(str(value))
            if mod_descs:
                description_parts.append(", ".join(mod_descs))

        description = " and ".join(description_parts) if description_parts else "with modifications"

        return modified_items, description

    def _add_item_from_history(
        self,
        item_data: dict,
        order: OrderTask,
        silent: bool = False,
    ) -> StateMachineResult | None:
        """Add an item from order history to the current order.

        Args:
            item_data: Item dict from order history.
            order: Current order task.
            silent: If True, don't return a result (for batch adds).

        Returns:
            StateMachineResult with confirmation, or None if silent.
        """
        # Check item availability (optional)
        item_name = item_data.get("menu_item_name", "Item")
        menu_item_type = item_data.get("menu_item_type") or item_data.get("item_type")
        price = item_data.get("price", 0)
        quantity = item_data.get("quantity", 1)

        # Create MenuItemTask
        item = MenuItemTask(
            menu_item_name=item_name,
            menu_item_type=menu_item_type,
            unit_price=price,
        )

        # Copy attribute_values if present
        if "attribute_values" in item_data and item_data["attribute_values"]:
            item.attribute_values = item_data["attribute_values"].copy()
        else:
            # Copy individual attributes (legacy support)
            metadata_keys = {
                "item_type", "menu_item_type", "menu_item_name", "menu_item_id",
                "quantity", "price", "modifiers", "attribute_values", "base_price",
                "display_name", "free_details", "customization_offered",
            }
            for key, value in item_data.items():
                if key not in metadata_keys and value is not None:
                    item[key] = value

        # Mark complete and add to order
        item.mark_complete()
        for _ in range(quantity):
            order.items.add_item(item.duplicate())

        order.set_phase(OrderPhase.TAKING_ITEMS)

        if silent:
            return None

        logger.info(
            "Added item '%s' from order history (qty=%d)",
            item_name, quantity
        )

        qty_word = f"{quantity} " if quantity > 1 else ""
        return StateMachineResult(
            message=RESPONSES["reorder_success"].format(
                summary=f"{qty_word}{item_name}"
            ),
            order=order,
        )

    def _validate_items(self, items: list) -> tuple[list, list]:
        """Check which items from history are still available.

        Returns:
            Tuple of (available_items, unavailable_items)
        """
        available = []
        unavailable = []

        for item in items:
            # For now, assume all items are available
            # In production, would check menu_cache.is_item_available()
            available.append(item)

        return available, unavailable
