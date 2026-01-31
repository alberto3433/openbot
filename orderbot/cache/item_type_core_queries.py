"""
Core item type query mixin for MenuDataCache.

Contains methods for querying item types, configurable types, and type metadata.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ItemTypeCoreQueryMixin:
    """Mixin containing core item type query methods."""

    def get_all_item_type_slugs(self) -> set[str]:
        """Get all available item type slugs.

        Returns:
            Set of item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return set(self._item_names_by_type.keys())

    def get_item_type_names_for_regex(self) -> list[str]:
        """Get item type names/aliases for use in regex patterns.

        Returns names and aliases sorted by length (longest first) for
        proper regex matching.

        Returns:
            List of item type names/aliases for regex patterns.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        names = []
        for keyword, info in self._category_keywords.items():
            if info.get("lookup_type") == "item_type":
                names.append(keyword)
        return sorted(names, key=len, reverse=True)

    def get_modifier_category(self, item_type_slug: str) -> str | None:
        """Get the modifier category for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")

        Returns:
            Modifier category ("food", "beverage", or None).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_type_modifier_categories.get(item_type_slug)

    def get_item_keywords(self) -> set[str]:
        """Get all item keywords for disambiguation.

        Returns:
            Set of keywords including menu item names and item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_keywords.copy()

    def get_configurable_item_types(self) -> set[str]:
        """Get item types that have attributes defined.

        Returns:
            Set of item type slugs that are configurable.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._configurable_item_types.copy()

    def get_simple_item_types(self) -> set[str]:
        """Get item types that have no attributes to ask about.

        These are "simple" items like beverages, pastries, sides that
        can be added to an order without configuration questions.

        Returns:
            Set of item type slugs that are NOT configurable.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        all_types = self.get_all_item_type_slugs()
        configurable = self._configurable_item_types
        return all_types - configurable

    def item_type_has_side_choice(self, item_type_slug: str) -> bool:
        """Check if an item type has a side choice attribute.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has side choice.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("has_side_choice", False)

    def get_side_choice_attribute(self, item_type_slug: str) -> dict | None:
        """Get side choice attribute details for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict with slug, question_text, display_name, or None.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("side_choice_attribute")

    def resolve_item_type_slug(self, name_or_alias: str) -> str:
        """Resolve an item type name or alias to its canonical database slug.

        Args:
            name_or_alias: Item type name or alias. Case-insensitive.

        Returns:
            The canonical item type slug from the database.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        name_lower = name_or_alias.lower().strip()
        category_info = self._category_keywords.get(name_lower)

        if category_info and "slug" in category_info:
            return category_info["slug"]

        return name_or_alias

    def infer_item_type_from_text(self, text: str) -> dict | None:
        """Infer item type by checking if any category keyword appears in the text.

        Args:
            text: User input text like "orange juice" or "blueberry muffin"

        Returns:
            Dict with item type info if a keyword is found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        text_lower = text.lower()
        words = text_lower.split()

        for word in words:
            if word in self._category_keywords:
                return self._category_keywords[word]

        for keyword, info in self._category_keywords.items():
            if " " in keyword and keyword in text_lower:
                return info

        return None

    def get_item_type_display_name(self, item_type_slug: str, plural: bool = False) -> str:
        """Get the display name for an item type slug.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")
            plural: If True, return plural form for suggestions

        Returns:
            Display name string. Returns slug if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        info = self._category_keywords.get(item_type_slug)
        if info:
            if plural:
                return info.get("display_name_plural", info.get("display_name", item_type_slug) + "s")
            return info.get("display_name", item_type_slug)

        return item_type_slug

    def item_accepts_input_modifiers(self, item_type_slug: str) -> bool:
        """Check if an item type accepts input modifiers.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has a modifier category defined.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self.get_modifier_category(item_type_slug) is not None

    def get_scannable_modifier_categories(self, item_type_slug: str) -> list[str]:
        """Get modifier categories that can be scanned for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            List of scannable modifier category slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        modifier_type = self.get_modifier_category(item_type_slug)
        if not modifier_type:
            return []
        return self.get_ordered_ingredient_categories(modifier_type)
