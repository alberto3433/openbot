"""
Order Context - Unified context for handler coordination.

This module provides a single OrderContext dataclass that encapsulates
all context information shared between handlers during order processing.
"""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class OrderContext:
    """
    Unified context for order processing.

    All handlers receive this context object instead of having fragmented
    set_context, set_store_info, set_repeat_order_info methods.
    """

    # Store information (hours, location, delivery zones, etc.)
    store_info: dict[str, Any] = field(default_factory=dict)

    # Returning customer data (previous orders, preferences)
    returning_customer: dict[str, Any] | None = None

    # Repeat order flags
    is_repeat_order: bool = False
    last_order_type: str | None = None

    # Menu data (for attribute lookups, etc.)
    menu_data: dict[str, Any] = field(default_factory=dict)

    # Callback to update repeat order info (used by taking_items_handler)
    set_repeat_info_callback: Callable[[bool, str | None], None] | None = None
