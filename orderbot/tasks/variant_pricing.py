"""
Variant Pricing Calculator.

Handles size/variant-based price lookups for menu items.
Extracted from pricing.py for better separation of concerns.
"""

import logging
from typing import TYPE_CHECKING

from .normalization import normalize_to_slug
from .utils.text import normalize_text
from orderbot.cache import menu_cache

if TYPE_CHECKING:
    from .pricing import PricingEngine

logger = logging.getLogger(__name__)


class VariantPricingCalculator:
    """Calculates prices for size/variant-based menu items.

    Handles items with multiple size options (e.g., small/medium/large coffee,
    1/4 lb / 1/2 lb spreads) where price depends on the selected variant.
    """

    def __init__(self, pricing_engine: "PricingEngine") -> None:
        """Initialize with reference to pricing engine for shared lookups.

        Args:
            pricing_engine: PricingEngine instance for _resolve_menu_item() access
        """
        self._pricing = pricing_engine

    def get_size_category_slug(self, menu_item_name: str) -> str | None:
        """Return the size_category_slug for a menu item, or None."""
        menu_item = self._pricing._resolve_menu_item(menu_item_name)
        if not menu_item:
            return None
        return menu_item.get("size_category_slug")

    def lookup_size_price(
        self,
        menu_item_name: str,
        size_name: str | None = None,
    ) -> tuple[float | None, dict | None]:
        """Look up price for a menu item with size-based pricing.

        For items with variant-based pricing (e.g., coffee, deli items), this
        returns the price for a specific size. If size_name is None and the item
        has only one size, returns that price.

        Args:
            menu_item_name: Name of the menu item
            size_name: Optional size name (e.g., "small", "large", "1/4 lb")

        Returns:
            Tuple of (price, size_data) where size_data contains size info,
            or (None, None) if item doesn't have size-based pricing
        """
        menu_item = self._pricing._resolve_menu_item(menu_item_name)
        if not menu_item:
            return None, None

        size_prices = menu_item.get("size_prices")
        if not size_prices:
            return None, None

        # If only one size, return it (no disambiguation needed)
        if len(size_prices) == 1:
            sp = size_prices[0]
            return sp["price"], sp

        # If size_name provided, find matching size
        if size_name:
            size_lower = normalize_text(size_name)
            for sp in size_prices:
                if sp["size_name"] and sp["size_name"].lower() == size_lower:
                    return sp["price"], sp

            # Try translating option slug to display name
            # (e.g., "one_pound" -> "1 lb" for weight-based pricing)
            size_category_slug = menu_item.get("size_category_slug")
            if size_category_slug:
                display_name = menu_cache.get_global_option_display_name(
                    size_category_slug, size_name
                )
                if display_name:
                    display_lower = normalize_text(display_name)
                    for sp in size_prices:
                        if sp["size_name"] and sp["size_name"].lower() == display_lower:
                            return sp["price"], sp

        # No size specified and multiple sizes - return None to trigger disambiguation
        return None, None

    def get_default_variant_for_item(
        self,
        menu_item_name: str,
    ) -> dict | None:
        """Get the default variant for an item with variant-based pricing.

        For items with size/weight-based pricing (e.g., spreads, coffee), this returns
        the default variant that determines the base price. The default is the first
        variant by display_order.

        Args:
            menu_item_name: Name of the menu item

        Returns:
            Dict with variant info {"slug": str, "display_name": str} or None if:
            - Item doesn't have variant pricing
            - Item has only one variant (no need to display "each" for bagels, etc.)
        """
        menu_item = self._pricing._resolve_menu_item(menu_item_name)
        if not menu_item:
            return None

        size_prices = menu_item.get("size_prices")
        if not size_prices:
            return None

        # If only one variant, don't show it in cart (e.g., "each" for bagels is redundant)
        if len(size_prices) == 1:
            return None

        # Sort by display_order to find the default (first) variant
        sorted_sizes = sorted(size_prices, key=lambda sp: sp.get("display_order", 999))
        default_size = sorted_sizes[0]

        # Get the size name and convert to slug
        size_name = default_size.get("size_name")
        if not size_name:
            return None

        # Convert display name to slug (e.g., "1/4 lb" -> "quarter_pound")
        slug = normalize_to_slug(size_name)

        return {
            "slug": slug,
            "display_name": size_name,
        }

    def lookup_base_price(self, menu_item_name: str, size_name: str | None = None) -> float:
        """Look up base price for any menu item by name.

        This is the generic way to get base prices - works for bagels, coffee,
        sandwiches, or any other menu item type.

        For items with size-based pricing, pass the size_name to get the correct
        price. If size_name is None and the item has only one size, that price
        is returned. If multiple sizes exist and no size_name is provided, falls
        back to base_price if available.

        Args:
            menu_item_name: Name of the menu item (e.g., "Bagel", "Latte", "BLT")
            size_name: Optional size name for size-based pricing

        Returns:
            Base price for the menu item

        Raises:
            ValueError: If menu item not found in database
        """
        if not menu_item_name:
            raise ValueError("menu_item_name is required for base price lookup")

        # Try size-based pricing first
        size_price, _ = self.lookup_size_price(menu_item_name, size_name)
        if size_price is not None:
            return size_price

        # Fall back to base_price
        menu_item = self._pricing._resolve_menu_item(menu_item_name)
        if menu_item and menu_item.get("base_price"):
            return menu_item["base_price"]

        raise ValueError(
            f"No price found for menu item '{menu_item_name}'. "
            "Ensure the menu item exists in database with a base_price or size_prices."
        )
