"""
Menu Search Query Mixin.

Contains methods for searching menu items by name, word match, term, and partial query.
"""

import re
import logging
from typing import Any

from .base import ensure_cache_loaded, normalize_for_matching, normalize_text, singularize

logger = logging.getLogger(__name__)


class MenuSearchQueryMixin:
    """Mixin for menu item search and matching methods."""

    @ensure_cache_loaded
    def search_menu_items_by_name(self, term: str) -> list[dict]:
        """Find menu items where the name contains the search term.

        Args:
            term: Search term (e.g., "muffin", "cookie", "chip")

        Returns:
            List of matching menu item dicts.
        """
        term_lower = normalize_text(term)
        term_singular = singularize(term_lower)

        matches = []

        for item_name in self._known_menu_items:
            item_lower = item_name.lower()
            if term_lower in item_lower or term_singular in item_lower:
                item_info = self._menu_index.get(item_name, {})
                matches.append({
                    "name": item_name,
                    "item_type": item_info.get("item_type", "menu_item"),
                    "base_price": item_info.get("base_price", 0.0),
                })

        return matches

    @ensure_cache_loaded
    def find_items_by_word_match(
        self,
        word: str,
        item_type_slug: str | None = None,
    ) -> list[dict]:
        """Find menu items where the word appears as a complete word in the name.

        Uses word boundary matching (not substring).
        Example: "tea" matches "Hot Tea", "Iced Tea" but NOT "Cheesesteak"

        Special character normalization is applied to both the search word and
        item names, so "dr brown" matches "Dr. Brown's".

        Args:
            word: The word to search for
            item_type_slug: Optional item type to restrict search

        Returns:
            List of matching menu item dicts with name, item_type, base_price.
        """
        word_normalized = normalize_for_matching(word)

        if not word_normalized:
            return []

        # Word boundary pattern - matches whole words only
        word_pattern = re.compile(rf'\b{re.escape(word_normalized)}\b', re.IGNORECASE)

        matches = []
        seen_names = set()

        # Iterate over _menu_items which contains item names and their item_type
        for item_name, item_info in self._menu_items.items():
            item_type = item_info.get("item_type")

            # Skip if filtering by item type and doesn't match
            if item_type_slug and item_type != item_type_slug:
                continue

            item_name_lower = item_name.lower()
            if item_name_lower in seen_names:
                continue

            # Normalize item name for matching (handles Dr. Brown's -> dr browns)
            item_normalized = normalize_for_matching(item_name)
            if word_pattern.search(item_normalized):
                seen_names.add(item_name_lower)
                matches.append({
                    "name": item_info.get("name", item_name),
                    "item_type": item_type or "menu_item",
                    "base_price": item_info.get("base_price", 0.0),
                })

        return matches

    @ensure_cache_loaded
    def find_all_items_by_word_match(self, word: str) -> list[dict]:
        """Find menu items where the word appears as a complete word in the name.

        Like find_items_by_word_match but searches ALL menu items including
        configurable items without default ingredients. Use for multi-word
        phrases that fail the primary search.

        Args:
            word: The word or phrase to search for

        Returns:
            List of matching menu item dicts with name, item_type, base_price.
        """
        word_normalized = normalize_for_matching(word)

        if not word_normalized:
            return []

        word_pattern = re.compile(rf'\b{re.escape(word_normalized)}\b', re.IGNORECASE)

        matches = []
        seen_ids: set[int] = set()

        for name_lower, item_data in self._all_menu_items_by_name.items():
            item_id = item_data.get("id")
            if item_id in seen_ids:
                continue

            item_normalized = normalize_for_matching(name_lower)
            if word_pattern.search(item_normalized):
                seen_ids.add(item_id)
                matches.append({
                    "name": item_data.get("name", name_lower),
                    "item_type": item_data.get("item_type_slug") or "menu_item",
                    "base_price": item_data.get("base_price", 0.0),
                })

        return matches

    @ensure_cache_loaded
    def search_menu_items_by_term(self, term: str) -> list[dict]:
        """Search menu items by term in both names AND aliases using word-boundary matching.

        This is designed for menu inquiries like "what lattes do you have?" where we want
        to find ALL items containing "latte" - not just the first alias match.

        Uses word-boundary matching: "latte" matches "Hot Latte", "Iced Latte"
        but not "Latteen". Also singularizes the search term.

        Special character normalization is applied, so "dr brown" matches "Dr. Brown's".

        Args:
            term: Search term (e.g., "latte", "muffins", "tea")

        Returns:
            List of matching menu item dicts from items_by_type, deduplicated by name.
        """
        term_normalized = normalize_for_matching(term)
        term_singular = singularize(term_normalized)

        if not term_normalized:
            return []

        # Build word boundary patterns for both original and singular forms
        patterns = [re.compile(rf'\b{re.escape(term_normalized)}\b', re.IGNORECASE)]
        if term_singular != term_normalized:
            patterns.append(re.compile(rf'\b{re.escape(term_singular)}\b', re.IGNORECASE))

        matches = []
        seen_names = set()

        # Get all items from menu_data (items_by_type)
        items_by_type = self._menu_index.get("items_by_type", {}) if self._menu_index else {}

        for type_items in items_by_type.values():
            for item in type_items:
                item_name = item.get("name", "")
                item_name_lower = item_name.lower()

                # Skip if already seen (handles items in multiple categories like signature_items)
                if item_name_lower in seen_names:
                    continue

                # Normalize item name for matching (handles Dr. Brown's -> dr browns)
                item_normalized = normalize_for_matching(item_name)

                # Check if term matches item name
                name_matches = any(p.search(item_normalized) for p in patterns)

                # Check if term matches any alias for this item
                alias_matches = False
                if not name_matches:
                    # Look up aliases for this item
                    for type_aliases in self._item_alias_to_canonical_by_type.values():
                        for alias, canonical in type_aliases.items():
                            if canonical.lower() == item_name_lower:
                                # This alias points to our item - check if term matches the alias
                                alias_normalized = normalize_for_matching(alias)
                                if any(p.search(alias_normalized) for p in patterns):
                                    alias_matches = True
                                    break
                        if alias_matches:
                            break

                if name_matches or alias_matches:
                    seen_names.add(item_name_lower)
                    matches.append(item)

        return matches

    def find_menu_item_matches(self, query: str) -> list[str]:
        """Find menu items that match a partial query.

        Handles plural forms by also trying the singularized version of words.

        Args:
            query: User input like "classic", "blt", or "cookies"

        Returns:
            List of matching menu item names.
        """
        query_lower = normalize_text(query)

        if not query_lower:
            return []

        # Try exact match first
        if query_lower in self._known_menu_items:
            return [query_lower]

        # Also try singularized form for exact match
        query_singular = singularize(query_lower)
        if query_singular != query_lower and query_singular in self._known_menu_items:
            return [query_singular]

        matches = set()
        for word in query_lower.split():
            # Try original word
            if word in self._menu_item_keyword_index:
                matches.update(self._menu_item_keyword_index[word])
            # Also try singularized form (e.g., "cookies" -> "cookie")
            word_singular = singularize(word)
            if word_singular != word and word_singular in self._menu_item_keyword_index:
                matches.update(self._menu_item_keyword_index[word_singular])

        if not matches and len(query_lower) >= 3:
            for item in self._known_menu_items:
                if query_lower in item:
                    matches.add(item)
            # Also try singularized form for substring matching
            if not matches and query_singular != query_lower:
                for item in self._known_menu_items:
                    if query_singular in item:
                        matches.add(item)

        return sorted(matches)

    @ensure_cache_loaded
    def get_menu_index(self, store_id: str | None = None) -> dict[str, Any]:
        """Get the cached menu index.

        Args:
            store_id: Optional store ID (currently not used)

        Returns:
            The cached menu index dict.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._menu_index
