from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .parsers.inquiry_patterns import (
    WITHOUT_PATTERN,
    get_reorder_modification_keywords,
)

if TYPE_CHECKING:
    from .order_history_handler import OrderHistoryHandler
    from .models import OrderTask

logger = logging.getLogger(__name__)


class OrderHistoryData:

    def __init__(self, parent: OrderHistoryHandler) -> None:
        self._parent = parent

    def _get_customer_phone(self, order: OrderTask) -> str | None:
        """Get customer phone from returning_customer or order."""
        if self._parent._returning_customer:
            return self._parent._returning_customer.get("phone")
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
        if self._parent._db_session:
            from ..services.customer_service import lookup_customer_order_history
            return lookup_customer_order_history(
                self._parent._db_session, phone, days=days, limit=limit
            )

        # Fallback: construct from returning_customer
        if self._parent._returning_customer:
            items = self._parent._returning_customer.get("last_order_items", [])
            if items:
                from ..services.helpers import build_order_items_summary
                summary = build_order_items_summary(items)

                return {
                    "customer": {
                        "name": self._parent._returning_customer.get("name"),
                        "phone": self._parent._returning_customer.get("phone"),
                        "email": self._parent._returning_customer.get("email"),
                    },
                    "order_count": self._parent._returning_customer.get("order_count", 1),
                    "orders": [{
                        "order_id": self._parent._returning_customer.get("last_order_id"),
                        "order_date": self._parent._returning_customer.get("last_order_date"),
                        "order_type": self._parent._returning_customer.get("last_order_type"),
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
