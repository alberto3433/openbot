"""
Item Creation Builder.

This module handles INITIAL ITEM CREATION - converting parsed user input
into the initial item dict that will become a MenuItemTask.

Architecture Layer: ITEM CREATION (during order flow)
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Deterministic Parser Output                              │
│              (item_type="bagel", item_name="Plain Bagel", ...)             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ build_menu_item_dict()
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 THIS MODULE (order_item_builder.py)                         │
│                        Item creation builder                                │
│                                                                             │
│   OrderItemBuilder: Creates initial item dict from parser output            │
│   • Looks up menu item by name (gets DB id, etc.)                          │
│   • Resolves base price from PricingEngine                                 │
│   • Detects if item type is configurable (needs questions)                 │
│                                                                             │
│   Output: Dict with name, item_type, base_price, id, skip_config           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ (dict becomes MenuItemTask.from_dict)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        item_adder_handler.py                                │
│              Creates MenuItemTask and adds to order.items                   │
└─────────────────────────────────────────────────────────────────────────────┘

Key Distinction from item_converters.py:
    - order_item_builder.py: Creates NEW items from parser output (forward flow)
    - item_converters.py: Serializes/deserializes EXISTING items (persistence)

    This module answers: "User said 'plain bagel' - what item dict should I create?"
    item_converters answers: "Here's a persisted dict - restore the MenuItemTask"

Public API:
    OrderItemBuilder(menu_lookup_func, pricing)
        .build_menu_item_dict(item_type, item_name, kwargs) -> dict

Related Modules:
    - item_adder_handler.py: Uses this to create items during order flow
    - pricing.py: Provides PricingEngine for base price lookups
    - item_converters.py: Different concern - persistence/serialization
"""

import logging
from typing import TYPE_CHECKING, Callable

from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class OrderItemBuilder:
    """Builds menu item dictionaries for order item creation.

    Handles menu lookup, price resolution, and configurable item detection.
    """

    def __init__(
        self,
        menu_lookup_func: Callable[[str], dict | None] | None = None,
        pricing: "PricingEngine | None" = None,
    ):
        """Initialize the order item builder.

        Args:
            menu_lookup_func: Function to look up menu items by name
            pricing: PricingEngine for price lookups
        """
        self._menu_lookup = menu_lookup_func
        self._pricing = pricing

    def build_menu_item_dict(
        self,
        item_type: str,
        item_name: str,
        kwargs: dict,
    ) -> dict:
        """Build menu_item dict for item creation.

        Uses unified price lookup for all item types - no category-specific branching.

        Args:
            item_type: The item type slug
            item_name: The item name (e.g., "Bagel", "Latte", "Turkey Club")
            kwargs: Original kwargs with item details

        Returns:
            Dict with name, item_type, base_price, id, skip_config
        """
        # Use item_name from kwargs if provided (may have been canonicalized)
        lookup_name = kwargs.get("item_name") or item_name

        # Step 1: Try menu lookup (works for all menu-backed items)
        menu_data = self._menu_lookup(lookup_name) if self._menu_lookup else None
        if menu_data:
            result = {
                "name": menu_data.get("name", lookup_name),
                "item_type": menu_data.get("item_type") or item_type,
                "base_price": menu_data.get("base_price", 0),
                "id": menu_data.get("id"),
                "skip_config": menu_data.get("skip_config", False),
            }
            # Include size_category_slug for items with variant pricing
            # This allows cart to display which variant the price is for (e.g., "1/4 lb")
            if menu_data.get("size_category_slug"):
                result["size_category_slug"] = menu_data["size_category_slug"]
            return result

        # Step 2: Check if this is a configurable item type (has conversation attributes)
        # For configurable types where menu lookup failed, keep the user's item name
        # (e.g., "latte") and try to price it. Don't substitute the item type display name
        # (e.g., "Sized Beverage") since that's not a valid menu item for pricing.
        is_configurable_type = item_type and menu_cache.has_conversation_attributes(item_type)
        if is_configurable_type:
            # Keep lookup_name (user's input like "latte"), not item type display name
            canonical_name = lookup_name
            # Try to look up price for the user's item name; default to 0.0 if not found
            base_price = 0.0
            if self._pricing:
                try:
                    base_price = self._pricing.lookup_base_price(canonical_name)
                except ValueError:
                    # Price lookup failed - item will be priced during configuration
                    logger.debug(
                        "No base price found for '%s' (item_type=%s), will price during config",
                        canonical_name, item_type
                    )
            return {
                "name": canonical_name,
                "item_type": item_type,
                "base_price": base_price,
                "id": None,
                "skip_config": False,
            }

        # Step 3: Try pricing engine as fallback
        if self._pricing:
            try:
                base_price = self._pricing.lookup_base_price(lookup_name)
                return {
                    "name": lookup_name,
                    "item_type": item_type,
                    "base_price": base_price,
                    "id": None,
                    "skip_config": False,
                }
            except ValueError:
                # Price lookup failed - fall through to return zero-price item
                pass

        # Step 4: Return with zero price (item will need configuration or is unknown)
        return {
            "name": lookup_name,
            "item_type": item_type,
            "base_price": 0,
            "id": None,
            "skip_config": False,
        }
