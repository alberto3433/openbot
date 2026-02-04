"""
Keyword extraction mixin for MenuDataCache.

Contains methods for extracting relevant keywords from attributes for matching.
"""

import logging

logger = logging.getLogger(__name__)


class KeywordQueryMixin:
    """Mixin containing keyword extraction query methods."""

    def get_relevant_keywords_for_attribute(
        self, item_type_slug: str | None, attr_slug: str
    ) -> set[str]:
        """Get keywords relevant to a specific attribute for off-topic detection.

        Args:
            item_type_slug: The item type slug (can be None for global attributes)
            attr_slug: The attribute slug

        Returns:
            Set of lowercase keywords relevant to this attribute.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        keywords: set[str] = set()

        if item_type_slug:
            attrs = self.get_item_type_attributes(item_type_slug)
            if attr_slug in attrs:
                attr = attrs[attr_slug]
                self._extract_keywords_from_attribute(attr, keywords)
                return keywords

        if attr_slug in self._global_attribute_options:
            options = self._global_attribute_options[attr_slug]
            keywords.add(attr_slug.lower().replace("_", " "))
            keywords.add(attr_slug.lower())
            for opt in options:
                self._extract_keywords_from_option(opt, keywords)
            return keywords

        keywords.add(attr_slug.lower().replace("_", " "))
        keywords.add(attr_slug.lower())
        return keywords

    def _extract_keywords_from_attribute(self, attr: dict, keywords: set[str]) -> None:
        """Extract keywords from an attribute config dict."""
        display_name = attr.get("display_name", "")
        if display_name:
            keywords.add(display_name.lower())
            for word in display_name.lower().split():
                if len(word) > 2:
                    keywords.add(word)

        slug = attr.get("slug", "")
        if slug:
            keywords.add(slug.lower())
            keywords.add(slug.lower().replace("_", " "))

        for opt in attr.get("options", []):
            self._extract_keywords_from_option(opt, keywords)

    def _extract_keywords_from_option(self, opt: dict, keywords: set[str]) -> None:
        """Extract keywords from an option dict."""
        slug = opt.get("slug", "")
        if slug:
            keywords.add(slug.lower())
            keywords.add(slug.lower().replace("_", " "))

        display_name = opt.get("display_name", "")
        if display_name:
            keywords.add(display_name.lower())
            for word in display_name.lower().split():
                if len(word) > 2:
                    keywords.add(word)

        aliases = opt.get("aliases")
        if aliases:
            for alias in aliases:
                keywords.add(alias.lower())

        category = opt.get("category", "")
        if category:
            keywords.add(category.lower())

    def get_attribute_for_inquiry_keyword(
        self, keyword: str, item_type_slug: str | None = None
    ) -> str | None:
        """Look up an attribute slug for an inquiry keyword.

        This is a data-driven replacement for the hardcoded common_mappings.
        Handles queries like "what types of X do you have?" by mapping
        the keyword (e.g., "types") and optional item type (e.g., "bagel")
        to an attribute slug (e.g., "bread").

        Lookup order:
        1. Exact match: (keyword, item_type_slug)
        2. Wildcard match: (keyword, None)

        Args:
            keyword: The signal word from user input (e.g., "types", "sizes")
            item_type_slug: Optional item type for context (e.g., "bagel")

        Returns:
            Attribute slug (e.g., "bread") or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        keyword_lower = keyword.lower()

        # 1. Try exact match with item type
        if item_type_slug:
            result = self._attribute_inquiry_keywords.get((keyword_lower, item_type_slug))
            if result:
                return result

        # 2. Try wildcard match (keyword, None)
        return self._attribute_inquiry_keywords.get((keyword_lower, None))
