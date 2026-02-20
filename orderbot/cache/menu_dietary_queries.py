"""
Menu Dietary Query Mixin.

Contains methods for querying dietary properties, allergens,
prefix-based lookups, and unit display formatting.
"""

import logging

from .base import ensure_cache_loaded, normalize_text

logger = logging.getLogger(__name__)


class MenuDietaryQueryMixin:
    """Mixin for dietary, allergen, prefix, and unit info queries."""

    @ensure_cache_loaded
    def get_items_by_dietary_property(self, property_name: str) -> list[dict]:
        """Get all menu items that have a specific dietary property.

        Args:
            property_name: The dietary property to filter by, e.g.:
                - "is_vegan", "is_vegetarian", "is_gluten_free", "is_dairy_free", "is_kosher"
                - "eggs_free", "fish_free", "sesame_free", "nuts_free" (for allergen-free)

        Returns:
            List of menu item dicts: [{id, name, item_type_slug, base_price}, ...]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._items_by_dietary_property.get(property_name, []).copy()

    @ensure_cache_loaded
    def get_items_by_dietary_property_filtered(
        self,
        property_name: str,
        item_type_slugs: list[str] | None = None
    ) -> list[dict]:
        """Get dietary items, optionally filtered by item types.

        Used for combined dietary + category queries like "what vegan drinks do you have?"
        where we want to filter by both dietary property AND item type.

        Args:
            property_name: The dietary property to filter by (e.g., "is_vegan")
            item_type_slugs: Optional list of item type slugs to filter by.
                If None, returns all items matching the dietary property.

        Returns:
            List of menu item dicts: [{id, name, item_type_slug, base_price}, ...]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        all_items = self._items_by_dietary_property.get(property_name, [])

        if not item_type_slugs:
            return all_items.copy()

        item_type_set = set(item_type_slugs)
        return [item for item in all_items if item.get("item_type_slug") in item_type_set]

    @ensure_cache_loaded
    def get_item_dietary_info(self, item_name: str) -> dict | None:
        """Get dietary and allergen information for a specific menu item.

        Args:
            item_name: The menu item name or alias (case-insensitive)

        Returns:
            Dict with dietary info: {
                "id": int,
                "name": str,
                "item_type_slug": str | None,
                "base_price": float,
                "is_vegan": bool | None,
                "is_vegetarian": bool | None,
                "is_gluten_free": bool | None,
                "is_dairy_free": bool | None,
                "is_kosher": bool | None,
                "contains_eggs": bool | None,
                "contains_fish": bool | None,
                "contains_sesame": bool | None,
                "contains_nuts": bool | None,
            }
            or None if item not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        name_lower = normalize_text(item_name)
        return self._item_dietary_info.get(name_lower)

    @ensure_cache_loaded
    def get_item_allergens(self, item_name: str) -> list[str]:
        """Get list of allergens contained in a menu item.

        Args:
            item_name: The menu item name or alias (case-insensitive)

        Returns:
            List of allergen names that the item contains (e.g., ["eggs", "fish"])
            Returns empty list if item not found or has no allergen data.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        info = self.get_item_dietary_info(item_name)
        if not info:
            return []

        # Build allergen list dynamically from properties with "contains_" prefix
        allergens = []
        for prop, value in info.items():
            if prop.startswith("contains_") and value is True:
                allergens.append(prop.replace("contains_", ""))

        return allergens

    @ensure_cache_loaded
    def has_dietary_data(self) -> bool:
        """Check if any dietary data is available in the cache.

        Returns:
            True if at least one item has dietary data configured.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        # Check if any dietary property has items
        return any(
            items for items in self._items_by_dietary_property.values()
        )

    @ensure_cache_loaded
    def get_allergen_column_names(self) -> list[str]:
        """Get list of allergen column names from cached dietary data.

        Returns column names in the "contains_X" format, derived from the
        _item_dietary_info cache which stores all dietary/allergen properties.

        Returns:
            List of allergen column names (e.g., ["contains_eggs", "contains_fish", ...]).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        # Get columns from the first item's dietary info that has allergen data
        # This is schema knowledge (column names), not domain data
        allergen_columns = []
        for info in self._item_dietary_info.values():
            for key in info.keys():
                if key.startswith("contains_") and key not in allergen_columns:
                    allergen_columns.append(key)
            # Once we've found an item with dietary info, we have the schema
            if allergen_columns:
                break

        return sorted(allergen_columns)

    # =========================================================================
    # Prefix-Based Query Methods (for "what iced drinks?" type queries)
    # =========================================================================

    @ensure_cache_loaded
    def get_menu_items_by_name_prefix(self, prefix: str) -> list[dict]:
        """Get all menu items whose name starts with a given word.

        Used for queries like "what iced drinks do you have?" where "iced"
        is the prefix and items like "Iced Coffee", "Iced Tea" are returned.

        Args:
            prefix: The prefix word to search for (e.g., "iced", "hot")

        Returns:
            List of menu item dicts matching the prefix.
            Each dict has: name, item_type, base_price, etc.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._menu_items_by_prefix.get(normalize_text(prefix), []).copy()

    @ensure_cache_loaded
    def get_known_name_prefixes(self) -> set[str]:
        """Get all known menu item name prefixes.

        Returns the set of first words from multi-word menu item names.
        Useful for checking if a word like "iced" is a known prefix.

        Returns:
            Set of lowercase prefix strings.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return set(self._menu_items_by_prefix.keys())

    @ensure_cache_loaded
    def get_menu_item_unit_info(self, item_name: str) -> tuple[str, int | None]:
        """Get unit type and quantity per unit for a menu item.

        Args:
            item_name: The menu item name (case-insensitive)

        Returns:
            Tuple of (unit_type, quantity_per_unit).
            Defaults to ("each", None) if item not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        item_data = self._menu_items.get(item_name.lower())
        if item_data:
            return (
                item_data.get("unit_type", "each"),
                item_data.get("quantity_per_unit"),
            )
        return ("each", None)

    @staticmethod
    def format_unit_display(unit_type: str, quantity_per_unit: int | None) -> str:
        """Format unit info for display to users.

        Args:
            unit_type: The unit type (each, pack, dozen, by_weight)
            quantity_per_unit: Number of items per unit (for packs)

        Returns:
            Display string like "(3 pack)" or "" for single items.
        """
        if unit_type == "pack" and quantity_per_unit and quantity_per_unit > 1:
            return f"({quantity_per_unit} pack)"
        if unit_type == "dozen":
            return "(dozen)"
        return ""
