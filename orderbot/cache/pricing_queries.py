"""
Pricing query mixin for MenuDataCache.

Contains methods for price lookups and price inquiry resolution.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PricingQueryMixin:
    """Mixin containing pricing-related query methods."""

    def item_type_has_priced_attributes(self, item_type_slug: str) -> bool:
        """Check if an item type has priced attribute options.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has attributes with price_modifier values.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_type_priced_attribute.get(item_type_slug) is not None

    def get_first_priced_attribute(self, item_type_slug: str) -> str | None:
        """Get the first priced attribute for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            The attribute slug if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_type_priced_attribute.get(item_type_slug)

    def get_resolved_item_price(self, item_name: str) -> float | None:
        """Get the resolved price for a menu item.

        Args:
            item_name: The menu item name

        Returns:
            The resolved price, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._resolved_item_prices.get(item_name.lower())

    def get_ingredient_price_contexts(self, ingredient_name: str) -> list[dict]:
        """Get price contexts for an ingredient.

        Args:
            ingredient_name: The ingredient name or alias

        Returns:
            List of context dicts with context_type, item_type_slug, label, price.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._ingredient_price_contexts.get(ingredient_name.lower(), []).copy()

    def resolve_price_inquiry(
        self, query: str, context: dict | None = None
    ) -> dict[str, Any]:
        """Resolve a price inquiry to item/ingredient details.

        This is the main entry point for data-driven price lookups.

        Args:
            query: The price query (e.g., "lox", "bagel", "large coffee")
            context: Optional context for resolution (not currently used)

        Returns:
            Dict with pricing info. Type field indicates result:
            - "item": {"type": "item", "name": str, "price": float}
            - "ingredient": {"type": "ingredient", "name": str, "contexts": [...]}
            - "attribute_options": {"type": "attribute_options", "item_type": str, "attribute": str, "options": [...]}
            - "not_found": {"type": "not_found", "query": str}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        query_lower = query.lower().strip()

        # 1. Check for exact menu item match
        if query_lower in self._resolved_item_prices:
            price = self._resolved_item_prices[query_lower]
            if price and price > 0:
                # Get display name from menu index
                name = query
                item_info = self._menu_index.get(query_lower, {})
                if item_info:
                    name = item_info.get("name", query)
                return {
                    "type": "item",
                    "name": name,
                    "price": price,
                }

        # 2. Check if it's an alias that resolves to a menu item
        resolved = self._menu_item_alias_to_canonical.get(query_lower)
        if resolved:
            resolved_lower = resolved.lower()
            if resolved_lower in self._resolved_item_prices:
                price = self._resolved_item_prices[resolved_lower]
                if price and price > 0:
                    return {
                        "type": "item",
                        "name": resolved,
                        "price": price,
                    }

        # 3. Check for ingredient with price contexts
        if query_lower in self._ingredient_price_contexts:
            contexts = self._ingredient_price_contexts[query_lower]
            # Get display name
            name = self.normalize_modifier(query)
            return {
                "type": "ingredient",
                "name": name,
                "contexts": contexts,
            }

        # 4. Check if it's an item type with priced attributes (e.g., "bagel")
        category_info = self._category_keywords.get(query_lower)
        if category_info and category_info.get("lookup_type") == "item_type":
            item_type_slug = category_info.get("slug")
            if item_type_slug and self.item_type_has_priced_attributes(item_type_slug):
                priced_attr = self.get_first_priced_attribute(item_type_slug)
                if priced_attr:
                    options = self.get_global_attribute_options(priced_attr)
                    if options:
                        return {
                            "type": "attribute_options",
                            "item_type": item_type_slug,
                            "item_type_display": category_info.get("display_name", item_type_slug),
                            "attribute": priced_attr,
                            "attribute_display": self.get_attribute_display_name(priced_attr),
                            "options": [
                                {
                                    "slug": opt.get("slug"),
                                    "display_name": opt.get("display_name"),
                                    "price": opt.get("price_modifier", 0),
                                }
                                for opt in options
                                if opt.get("price_modifier")
                            ],
                        }

        # 5. Check menu index for sized/priced items
        item_info = self._menu_index.get(query_lower)
        if not item_info:
            # Try to find in all menu items
            for name_lower, info in self._all_menu_items_by_name.items():
                if query_lower in name_lower:
                    item_info = self._menu_index.get(info.get("name", "").lower(), {})
                    if item_info:
                        break

        if item_info:
            name = item_info.get("name", query)
            price = item_info.get("base_price")

            # Check for size prices
            if "size_prices" in item_info:
                return {
                    "type": "sized_item",
                    "name": name,
                    "sizes": item_info["size_prices"],
                }

            if price and price > 0:
                return {
                    "type": "item",
                    "name": name,
                    "price": price,
                }

        # 5. Not found
        return {
            "type": "not_found",
            "query": query,
        }
