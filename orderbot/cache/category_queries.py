"""
Category query mixin for MenuDataCache.

Contains methods for querying categories and category keywords.
"""

import re
import logging

from .base import singularize, pluralize

logger = logging.getLogger(__name__)


class CategoryQueryMixin:
    """Mixin containing category query methods."""

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

    def get_modifier_category_by_alias(self, alias: str) -> str | None:
        """Look up modifier category slug by alias.

        Uses the modifier_category_aliases table to map user terms like
        "cream cheese" to category slugs like "spreads".

        Args:
            alias: User input to look up (e.g., "cream cheese", "spread")

        Returns:
            Category slug if found (e.g., "spreads"), None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_category_alias_to_slug.get(alias.lower().strip())

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

    def is_category_reference(self, term: str) -> str | None:
        """Check if a term matches a category name/slug (case-insensitive).

        Checks in order:
        1. Category keywords (item type slugs, Category names)
        2. Display group aliases (e.g., "desserts" -> "desserts_pastries")

        Args:
            term: User input like "drinks", "beverage", "cookies", "muffin"

        Returns:
            Category slug if match found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()

        # Check category keywords first
        mapping = self._category_keywords.get(term_lower)
        if mapping:
            return mapping["slug"]

        term_singular = singularize(term_lower)
        if term_singular != term_lower:
            mapping = self._category_keywords.get(term_singular)
            if mapping:
                return mapping["slug"]

        # Check display group aliases (e.g., "desserts" -> "desserts_pastries")
        # Return the alias itself - handle_category_clarification will resolve it
        display_group_slug = self._display_group_alias_to_slug.get(term_lower)
        if display_group_slug:
            return term_lower

        # Try singularized form for display group aliases
        if term_singular != term_lower:
            display_group_slug = self._display_group_alias_to_slug.get(term_singular)
            if display_group_slug:
                return term_singular

        # Try pluralized form for display group aliases
        term_plural = pluralize(term_lower)
        if term_plural != term_lower:
            display_group_slug = self._display_group_alias_to_slug.get(term_plural)
            if display_group_slug:
                return term_plural

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

    def get_menu_display_groups(self) -> list[dict]:
        """Get menu display groups for "what's on the menu?" responses.

        Returns high-level user-facing categories like "breads", "sandwiches",
        "drinks", etc. - consolidated from the more granular item types.

        Returns:
            List of dicts ordered by display_order:
            [{"slug": "breads", "display_name": "Breads", "display_order": 1}, ...]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return list(self._menu_display_groups_ordered)

    def get_display_group_by_slug(self, slug: str) -> dict | None:
        """Get display group info by slug, alias, or display name match.

        Matches against (in order):
        1. Exact slug match (e.g., "breads" matches slug "breads")
        2. Alias match (e.g., "pastries" matches "desserts_pastries" via alias)
        3. Words in display_name (e.g., "desserts" matches "Desserts and Pastries")

        Args:
            slug: The display group slug, alias, or partial name (e.g., "breads", "pastries")

        Returns:
            Dict with display group info if found, None otherwise.
            {"slug": "breads", "display_name": "Breads", "display_order": 1}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        query_lower = slug.lower().strip()

        # Try exact slug match first
        for group in self._menu_display_groups_ordered:
            if group["slug"] == query_lower:
                return group

        # Try alias match (e.g., "pastries" -> "desserts_pastries")
        alias_group_slug = self._display_group_alias_to_slug.get(query_lower)
        if alias_group_slug:
            for group in self._menu_display_groups_ordered:
                if group["slug"] == alias_group_slug:
                    return group

        # Try singularized alias (e.g., "pastry" -> "pastries" -> "desserts_pastries")
        query_singular = singularize(query_lower)
        if query_singular != query_lower:
            alias_group_slug = self._display_group_alias_to_slug.get(query_singular)
            if alias_group_slug:
                for group in self._menu_display_groups_ordered:
                    if group["slug"] == alias_group_slug:
                        return group

        # Try pluralized alias (e.g., "pastry" -> "pastries" -> lookup)
        query_plural = pluralize(query_lower)
        if query_plural != query_lower:
            alias_group_slug = self._display_group_alias_to_slug.get(query_plural)
            if alias_group_slug:
                for group in self._menu_display_groups_ordered:
                    if group["slug"] == alias_group_slug:
                        return group

        # Try matching against display_name words (e.g., "desserts" in "Desserts and Pastries")
        # Use word boundary to avoid partial matches
        query_pattern = re.compile(rf'\b{re.escape(query_lower)}\b', re.IGNORECASE)
        for group in self._menu_display_groups_ordered:
            if query_pattern.search(group["display_name"]):
                return group

        # Try singularized form against display_name
        if query_singular != query_lower:
            singular_pattern = re.compile(rf'\b{re.escape(query_singular)}\b', re.IGNORECASE)
            for group in self._menu_display_groups_ordered:
                if singular_pattern.search(group["display_name"]):
                    return group

        # Try pluralized form against display_name
        if query_plural != query_lower:
            plural_pattern = re.compile(rf'\b{re.escape(query_plural)}\b', re.IGNORECASE)
            for group in self._menu_display_groups_ordered:
                if plural_pattern.search(group["display_name"]):
                    return group

        return None

    def get_item_types_in_display_group(self, display_group_slug: str) -> list[str]:
        """Get item type slugs that belong to a display group.

        Used when user asks "what breads do you have?" - returns the item types
        (e.g., "bagel") that are in the "breads" display group.

        Args:
            display_group_slug: The display group slug (e.g., "breads")

        Returns:
            List of item type slugs in that display group, empty list if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_types_by_display_group.get(display_group_slug, [])
