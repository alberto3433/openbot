"""
Pricing Repository.

Provides price lookup operations.
"""

from .base import BaseRepository


class PricingRepository(BaseRepository):
    """Repository for pricing operations.

    Wraps cache methods related to price lookups for menu items,
    ingredients, and variants.
    """

    # =========================================================================
    # Price Lookups
    # =========================================================================

    def get_item_price(self, item_name: str) -> float | None:
        """Get the resolved price for a menu item.

        Args:
            item_name: The menu item name

        Returns:
            Price as float or None if not found
        """
        return self._cache.get_resolved_item_price(item_name)

    def get_ingredient_price(
        self,
        ingredient_name: str,
        item_type: str
    ) -> float | None:
        """Get the price for an ingredient in the context of an item type.

        Args:
            ingredient_name: The ingredient name
            item_type: The item type slug

        Returns:
            Price as float or None if not found
        """
        return self._cache.get_ingredient_price_for_item_type(
            ingredient_name, item_type
        )

    # =========================================================================
    # Pricing Attributes
    # =========================================================================

    def has_priced_attributes(self, item_type_slug: str) -> bool:
        """Check if an item type has attributes that affect pricing.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if has priced attributes, False otherwise
        """
        return self._cache.item_type_has_priced_attributes(item_type_slug)

    def get_first_priced_attribute(self, item_type_slug: str) -> str | None:
        """Get the first attribute that affects pricing.

        Args:
            item_type_slug: The item type slug

        Returns:
            Attribute slug or None
        """
        return self._cache.get_first_priced_attribute(item_type_slug)
