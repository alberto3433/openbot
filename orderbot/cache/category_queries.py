"""
Category query mixin for MenuDataCache.

Contains methods for querying categories and category keywords.
"""

import re
import logging

from .base import ensure_cache_loaded, normalize_text, singularize, pluralize

logger = logging.getLogger(__name__)


class CategoryQueryMixin:
    """Mixin containing category query methods."""

    @ensure_cache_loaded
    def get_available_menu_categories(self) -> dict[str, str]:
        """Get all available high-level menu categories.

        Returns:
            Dict mapping category slug to display name.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        return self._available_categories.copy()

    @ensure_cache_loaded
    def get_modifier_categories_for_inquiry(self) -> dict[str, dict]:
        """Get modifier categories for menu inquiries.

        Returns:
            Dict mapping slug -> {display_name, loads_from_ingredients, ...}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._modifier_categories.copy()

    @ensure_cache_loaded
    def get_modifier_category_items(self, slug: str) -> set[str]:
        """Get items for a modifier category.

        Args:
            slug: The modifier category slug

        Returns:
            Set of item names/slugs in that category.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        cat_info = self._modifier_categories.get(slug, {})

        if cat_info.get("loads_from_ingredients"):
            ing_cat = cat_info.get("ingredient_category")
            if ing_cat:
                return self.get_ingredients(ing_cat)

        return set()

    @ensure_cache_loaded
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
        return self._modifier_category_alias_to_slug.get(normalize_text(alias))

    @ensure_cache_loaded
    def get_category_keyword_mapping(self, keyword: str) -> dict | None:
        """Look up category info for a user keyword.

        Args:
            keyword: User input like "bagels", "desserts", "coffees", "teas"

        Returns:
            Dict with category info if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        keyword_lower = normalize_text(keyword)
        return self._category_keywords.get(keyword_lower)

    @ensure_cache_loaded
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
        term_lower = normalize_text(term)

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

    @ensure_cache_loaded
    def get_category_needing_clarification(self, text: str) -> str | None:
        """Check if text contains a generic category term that needs clarification.

        Args:
            text: User input text to search (should be lowercase)

        Returns:
            Category slug if a generic category term is found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        text_lower = normalize_text(text)

        for keyword, mapping in self._category_keywords.items():
            pattern = rf'\b{re.escape(keyword)}\b'
            if re.search(pattern, text_lower):
                return mapping["slug"]

        return None

    @ensure_cache_loaded
    def get_menu_display_groups(self) -> list[dict]:
        """Get top-level menu display groups for "what's on the menu?" responses.

        Returns high-level user-facing categories like "breads", "sandwiches",
        "drinks", etc. Child groups (those with a parent) are excluded since
        they are discoverable via their parent group.

        Returns:
            List of dicts ordered by display_order:
            [{"slug": "breads", "display_name": "Breads", "display_order": 1}, ...]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return [g for g in self._menu_display_groups_ordered if g.get("parent_slug") is None]

    @ensure_cache_loaded
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
        query_lower = normalize_text(slug)

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

    @ensure_cache_loaded
    def get_descendant_display_group_slugs(self, display_group_slug: str) -> list[str]:
        """Get all descendant display group slugs (children, grandchildren, etc.).

        Traverses the parent-child hierarchy to collect all groups nested under
        the given group. Does not include the given group itself.

        Args:
            display_group_slug: The parent display group slug (e.g., "snacks")

        Returns:
            List of all descendant slugs (e.g., ["candy_bars", "chips"]).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        descendants: list[str] = []
        stack = list(self._display_group_children.get(display_group_slug, []))
        while stack:
            child = stack.pop()
            descendants.append(child)
            stack.extend(self._display_group_children.get(child, []))
        return descendants

    @ensure_cache_loaded
    def get_item_types_in_display_group(self, display_group_slug: str) -> list[str]:
        """Get item type slugs that belong to a display group and all its descendants.

        Traverses the parent-child hierarchy so that querying "snacks" also
        returns item types from child groups like "candy_bars" and "chips".

        Args:
            display_group_slug: The display group slug (e.g., "breads", "snacks")

        Returns:
            List of item type slugs in that group and all descendant groups.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        # Collect from the group itself
        result = list(self._item_types_by_display_group.get(display_group_slug, []))
        # Collect from all descendant groups
        for child_slug in self.get_descendant_display_group_slugs(display_group_slug):
            result.extend(self._item_types_by_display_group.get(child_slug, []))
        return result
