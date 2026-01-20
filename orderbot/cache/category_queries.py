"""
Category query mixin for MenuDataCache.

Contains methods for querying categories and category keywords.
"""

import re
import logging

from .base import singularize

logger = logging.getLogger(__name__)


class CategoryQueryMixin:
    """Mixin containing category query methods."""

    def is_category_slug(self, keyword: str) -> bool:
        """Check if a keyword is a valid high-level category slug.

        Args:
            keyword: The keyword to check (e.g., "drink", "food")

        Returns:
            True if keyword is a valid category slug.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        return keyword.lower() in self._available_categories

    def get_available_menu_categories(self) -> dict[str, str]:
        """Get all available high-level menu categories.

        Returns:
            Dict mapping category slug to display name.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        return self._available_categories.copy()

    def get_modifier_categories_for_inquiry(self) -> dict[str, dict]:
        """Get modifier categories for menu inquiries.

        Returns:
            Dict mapping slug -> {display_name, loads_from_ingredients, ...}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_categories.copy()

    def get_modifier_category_items(self, slug: str) -> set[str]:
        """Get items for a modifier category.

        Args:
            slug: The modifier category slug

        Returns:
            Set of item names/slugs in that category.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        cat_info = self._modifier_categories.get(slug, {})

        if cat_info.get("loads_from_ingredients"):
            ing_cat = cat_info.get("ingredient_category")
            if ing_cat:
                return self.get_ingredients(ing_cat)

        return set()

    def get_category_keyword_mapping(self, keyword: str) -> dict | None:
        """Look up category info for a user keyword.

        Args:
            keyword: User input like "bagels", "desserts", "coffees", "teas"

        Returns:
            Dict with category info if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        keyword_lower = keyword.lower().strip()
        return self._category_keywords.get(keyword_lower)

    def get_available_category_keywords(self) -> list[str]:
        """Get list of all available category keywords for error messages.

        Returns:
            Sorted list of all valid category keywords.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return sorted(self._category_keywords.keys())

    def is_category_reference(self, term: str) -> str | None:
        """Check if a term matches a category name/slug (case-insensitive).

        Args:
            term: User input like "drinks", "beverage", "cookies", "muffin"

        Returns:
            Category slug if match found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()

        mapping = self._category_keywords.get(term_lower)
        if mapping:
            return mapping["slug"]

        term_singular = singularize(term_lower)
        if term_singular != term_lower:
            mapping = self._category_keywords.get(term_singular)
            if mapping:
                return mapping["slug"]

        return None

    def get_category_needing_clarification(self, text: str) -> str | None:
        """Check if text contains a generic category term that needs clarification.

        Args:
            text: User input text to search (should be lowercase)

        Returns:
            Category slug if a generic category term is found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        text_lower = text.lower().strip()

        for keyword, mapping in self._category_keywords.items():
            pattern = rf'\b{re.escape(keyword)}\b'
            if re.search(pattern, text_lower):
                return mapping["slug"]

        return None
