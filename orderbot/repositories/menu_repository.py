"""
Menu Repository.

Provides menu item lookup and search operations.
"""

from typing import Any

from .base import BaseRepository


class MenuRepository(BaseRepository):
    """Repository for menu item operations.

    Wraps cache methods related to menu items, providing a cleaner API
    for menu item lookups, searches, and dietary queries.
    """

    # =========================================================================
    # Core Lookups
    # =========================================================================

    def find_by_name(self, name: str) -> dict | None:
        """Find a menu item by its name.

        Args:
            name: The menu item name (case-insensitive)

        Returns:
            Menu item dict if found, None otherwise
        """
        return self._cache.get_menu_item(name)

    def find_by_id(self, menu_item_id: int) -> dict | None:
        """Find a menu item by its database ID.

        Args:
            menu_item_id: The menu item's database ID

        Returns:
            Menu item dict if found, None otherwise
        """
        return self._cache.get_menu_item_by_id(menu_item_id)

    def get_all_names(self) -> list[str]:
        """Get all menu item names.

        Returns:
            List of all menu item names
        """
        return self._cache.get_all_menu_item_names()

    def get_known_items(self) -> set[str]:
        """Get set of all known menu item names.

        Returns:
            Set of menu item names (lowercase)
        """
        return self._cache.get_known_menu_items()

    # =========================================================================
    # Alias Resolution
    # =========================================================================

    def resolve_alias(self, alias: str) -> str | None:
        """Resolve a menu item alias to its canonical name.

        Args:
            alias: The alias to resolve

        Returns:
            Canonical menu item name if found, None otherwise
        """
        return self._cache.resolve_menu_item_alias(alias)

    def get_item_type(self, menu_item_name: str) -> str | None:
        """Get the item type slug for a menu item.

        Args:
            menu_item_name: The menu item name

        Returns:
            Item type slug (e.g., "bagel", "sized_beverage") or None
        """
        return self._cache.get_item_type_for_menu_item(menu_item_name)

    # =========================================================================
    # Search Methods
    # =========================================================================

    def find_by_word_match(
        self,
        word: str,
        item_type_slug: str | None = None
    ) -> list[dict]:
        """Find menu items matching a word.

        Args:
            word: The word to search for
            item_type_slug: Optional filter by item type

        Returns:
            List of matching menu item dicts
        """
        return self._cache.find_items_by_word_match(word, item_type_slug)

    def search_by_name(self, term: str) -> list[dict]:
        """Search menu items by name.

        Args:
            term: Search term

        Returns:
            List of matching menu item dicts
        """
        return self._cache.search_menu_items_by_name(term)

    def search_by_term(self, term: str) -> list[dict]:
        """Search menu items by term (includes aliases).

        Args:
            term: Search term

        Returns:
            List of matching menu item dicts
        """
        return self._cache.search_menu_items_by_term(term)

    def search_for_recommendation(self, term: str) -> list[dict]:
        """Search menu items for recommendation.

        Args:
            term: Search term

        Returns:
            List of matching menu item dicts suitable for recommendations
        """
        return self._cache.search_menu_items_for_recommendation(term)

    # =========================================================================
    # Category & Type Queries
    # =========================================================================

    def get_by_category(self, category_slug: str) -> list[dict]:
        """Get all menu items in a category.

        Args:
            category_slug: The category slug

        Returns:
            List of menu item dicts in the category
        """
        return self._cache.get_items_by_category(category_slug)

    def get_by_item_type(self, item_type_slug: str) -> list[dict]:
        """Get all menu items of a specific type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel")

        Returns:
            List of menu item dicts of that type
        """
        return self._cache.get_items_by_item_type(item_type_slug)

    def get_all_item_type_slugs(self) -> set[str]:
        """Get all known item type slugs.

        Returns:
            Set of item type slugs
        """
        return self._cache.get_all_item_type_slugs()

    # =========================================================================
    # Dietary & Allergen Queries
    # =========================================================================

    def get_by_dietary_property(
        self,
        property_name: str,
        item_type_slugs: list[str] | None = None
    ) -> list[dict]:
        """Get menu items with a specific dietary property.

        Args:
            property_name: Dietary property (e.g., "is_vegan", "is_gluten_free")
            item_type_slugs: Optional filter by item types

        Returns:
            List of matching menu item dicts
        """
        if item_type_slugs:
            return self._cache.get_items_by_dietary_property_filtered(
                property_name, item_type_slugs
            )
        return self._cache.get_items_by_dietary_property(property_name)

    def get_dietary_info(self, item_name: str) -> dict | None:
        """Get dietary information for a menu item.

        Args:
            item_name: The menu item name

        Returns:
            Dict with dietary properties or None
        """
        return self._cache.get_item_dietary_info(item_name)

    def get_allergens(self, item_name: str) -> list[str]:
        """Get allergens for a menu item.

        Args:
            item_name: The menu item name

        Returns:
            List of allergen names
        """
        return self._cache.get_item_allergens(item_name)

    # =========================================================================
    # Default Ingredients
    # =========================================================================

    def get_default_ingredients(self, menu_item_id: int) -> list[dict]:
        """Get default ingredients for a menu item.

        Args:
            menu_item_id: The menu item's database ID

        Returns:
            List of ingredient dicts
        """
        return self._cache.get_menu_item_default_ingredients(menu_item_id)

    # =========================================================================
    # Unit Type Queries
    # =========================================================================

    def get_by_unit_type(self, unit_type: str) -> set[str]:
        """Get menu items with a specific unit type.

        Args:
            unit_type: The unit type (e.g., "weight", "quantity")

        Returns:
            Set of menu item names
        """
        return self._cache.get_menu_items_by_unit_type(unit_type)

    def get_unit_info(self, item_name: str) -> tuple[str, int | None]:
        """Get unit information for a menu item.

        Args:
            item_name: The menu item name

        Returns:
            Tuple of (unit_type, quantity_per_unit)
        """
        return self._cache.get_menu_item_unit_info(item_name)
