"""
Menu Core Query Mixin.

Contains fundamental menu item lookup, alias resolution, and iteration methods.
"""

import logging

from .base import ensure_cache_loaded, normalize_text, singularize

logger = logging.getLogger(__name__)


class MenuCoreQueryMixin:
    """Mixin for core menu item queries and alias resolution."""

    @property
    def is_loaded(self) -> bool:
        """Check if cache has been loaded from database."""
        return self._is_loaded

    @ensure_cache_loaded
    def get_known_menu_items(self) -> set[str]:
        """Get the set of all known menu item names and aliases (lowercase).

        Returns:
            Set of menu item names and aliases for pattern matching.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._known_menu_items.copy()

    @ensure_cache_loaded
    def get_item_names(self, item_type_slug: str) -> set[str]:
        """Get all MenuItem names and aliases for a given ItemType.

        Args:
            item_type_slug: The ItemType slug (e.g., "sized_beverage", "bagel", "beverage")

        Returns:
            Set of lowercase item names and aliases for matching user input.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        if item_type_slug not in self._item_names_by_type:
            return set()
        return self._item_names_by_type[item_type_slug].copy()

    @ensure_cache_loaded
    def get_item_alias_to_canonical_by_type(self, item_type_slug: str) -> dict[str, str]:
        """Get alias-to-canonical name mapping for a given item type.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")

        Returns:
            Dict mapping aliases (lowercase) to canonical names.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        if item_type_slug not in self._item_alias_to_canonical_by_type:
            return {}
        return self._item_alias_to_canonical_by_type[item_type_slug].copy()

    @ensure_cache_loaded
    def get_items_by_category(self, category_slug: str) -> list[dict]:
        """Get all menu items in a given high-level category (drink, food, etc.).

        Args:
            category_slug: The category slug (e.g., "drink", "food")

        Returns:
            List of dicts with menu item info: [{"id": int, "name": str, "item_type_slug": str}]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        return self._menu_items_by_category_slug.get(category_slug, []).copy()

    @ensure_cache_loaded
    def get_items_by_item_type(self, item_type_slug: str) -> list[dict]:
        """Get all menu items of a given item type.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")

        Returns:
            List of dicts with menu item info.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        result = []
        for item_name, item_data in self._menu_items.items():
            if item_data.get("item_type") == item_type_slug:
                result.append({
                    "id": item_data.get("id"),
                    "name": item_data.get("name", item_name),
                    "item_type": item_type_slug,
                    "base_price": item_data.get("base_price", 0.0),
                })
        return result

    @ensure_cache_loaded
    def iter_all_menu_items(self) -> dict[str, dict]:
        """Return the full menu items dict keyed by canonical name.

        Each value is a dict with at least: id, name, item_type, base_price,
        aliases, and required_match_phrases.

        Returns:
            Shallow copy of the internal menu items dict.
        """
        return dict(self._menu_items)

    @ensure_cache_loaded
    def get_item_names_by_ids(self, item_ids: set[int]) -> dict[int, str]:
        """Map a set of menu item IDs to their display names.

        Args:
            item_ids: Set of menu item IDs to look up.

        Returns:
            Dict mapping id -> display name for all found items.
        """
        result: dict[int, str] = {}
        for item_data in self._all_menu_items_by_name.values():
            item_id = item_data.get("id")
            if item_id in item_ids:
                result[item_id] = item_data.get("name", f"Item {item_id}")
        return result

    @ensure_cache_loaded
    def resolve_item_alias(
        self, alias: str, item_type_slug: str | None = None
    ) -> str | None:
        """Resolve an item alias to its canonical MenuItem name.

        Args:
            alias: The alias to resolve (e.g., "coke", "matcha", "drip")
            item_type_slug: Optional ItemType slug to restrict search.

        Returns:
            Canonical MenuItem name (with original casing), or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        alias_lower = normalize_text(alias)

        if item_type_slug:
            type_aliases = self._item_alias_to_canonical_by_type.get(item_type_slug, {})
            return type_aliases.get(alias_lower)
        else:
            for type_aliases in self._item_alias_to_canonical_by_type.values():
                if alias_lower in type_aliases:
                    return type_aliases[alias_lower]
            return None

    @ensure_cache_loaded
    def get_items_with_defaults_aliases(self) -> dict[str, str]:
        """Get alias mapping for items that have default ingredients.

        Items with default ingredients need special recognition in parsing to prevent
        trigger-based detection from overriding them.

        Returns:
            Dict mapping lowercase alias -> menu item name (with original casing).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._items_with_defaults_aliases.copy()

    @ensure_cache_loaded
    def item_has_default_ingredients(self, menu_item_name: str) -> bool:
        """Check if a menu item has default ingredients defined.

        Args:
            menu_item_name: The menu item name to check (case-insensitive)

        Returns:
            True if the item has default ingredients, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return (
            menu_item_name in self._items_with_defaults_types
            or menu_item_name in self._items_with_defaults_aliases.values()
        )

    @ensure_cache_loaded
    def get_item_type_for_menu_item(self, menu_item_name: str) -> str | None:
        """Get the item type slug for a menu item.

        Args:
            menu_item_name: The canonical menu item name (e.g., "The Classic BEC")

        Returns:
            The item type slug (e.g., "egg_sandwich") or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        result = self._items_with_defaults_types.get(menu_item_name)
        if result:
            return result

        item_info = self._menu_index.get(menu_item_name, {})
        return item_info.get("item_type")

    @ensure_cache_loaded
    def resolve_menu_item_alias(self, name: str) -> str | None:
        """Resolve a menu item name or alias to its canonical menu item name.

        Args:
            name: User input like "tuna salad", "blt", "cheese omelette"

        Returns:
            Canonical MenuItem.name or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        name_lower = normalize_text(name)
        return self._menu_item_alias_to_canonical.get(name_lower)

    @ensure_cache_loaded
    def resolve_alias(self, term: str) -> tuple[str | None, str | None]:
        """Unified alias resolution across all sources (data-driven).

        Args:
            term: User input like "coke", "bec", "lox", "chips"

        Returns:
            Tuple of (canonical_name, source_type) where:
            - canonical_name: The resolved name, or None if not found
            - source_type: One of "menu_item", "side", "item", "modifier", or None

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        term_lower = normalize_text(term)

        # 1. Try menu item aliases first
        result = self._menu_item_alias_to_canonical.get(term_lower)
        if result:
            return (result, "menu_item")

        # 2. Try side item aliases
        result = self._side_alias_to_canonical.get(term_lower)
        if result:
            return (result, "side")

        # 3. Try item aliases across all item types
        for item_type_slug, type_aliases in self._item_alias_to_canonical_by_type.items():
            if term_lower in type_aliases:
                return (type_aliases[term_lower], "item")

        # 4. Try ingredient/modifier aliases
        result = self._modifier_aliases.get(term_lower)
        if result:
            return (result, "modifier")

        return (None, None)

    @ensure_cache_loaded
    def resolve_side_alias(self, name: str) -> str | None:
        """Resolve a side item name or alias to its canonical menu item name.

        Args:
            name: User input like "sausage", "latke", "bacon"

        Returns:
            Canonical MenuItem.name or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        name_lower = normalize_text(name)
        return self._side_alias_to_canonical.get(name_lower)
