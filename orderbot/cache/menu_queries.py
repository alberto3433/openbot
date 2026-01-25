"""
Menu query mixin for MenuDataCache.

Contains methods for querying menu items, signatures, and aliases.
"""

import re
import logging
from typing import Any

from .base import singularize

logger = logging.getLogger(__name__)


class MenuQueryMixin:
    """Mixin containing menu item query methods."""

    @property
    def is_loaded(self) -> bool:
        """Check if cache has been loaded from database."""
        return self._is_loaded

    @property
    def last_refresh(self):
        """Get timestamp of last cache refresh."""
        return self._last_refresh

    def get_known_menu_items(self) -> set[str]:
        """Get the set of all known menu item names and aliases (lowercase).

        Returns:
            Set of menu item names and aliases for pattern matching.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._known_menu_items.copy()

    def get_item_names(self, item_type_slug: str) -> set[str]:
        """Get all MenuItem names and aliases for a given ItemType.

        Args:
            item_type_slug: The ItemType slug (e.g., "sized_beverage", "bagel", "beverage")

        Returns:
            Set of lowercase item names and aliases for matching user input.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        if item_type_slug not in self._item_names_by_type:
            return set()
        return self._item_names_by_type[item_type_slug].copy()

    def get_item_names_by_type(self, item_type_slug: str) -> set[str]:
        """Alias for get_item_names() - get all item names for a given item type."""
        return self.get_item_names(item_type_slug)

    def get_item_alias_to_canonical_by_type(self, item_type_slug: str) -> dict[str, str]:
        """Get alias-to-canonical name mapping for a given item type.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")

        Returns:
            Dict mapping aliases (lowercase) to canonical names.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        if item_type_slug not in self._item_alias_to_canonical_by_type:
            return {}
        return self._item_alias_to_canonical_by_type[item_type_slug].copy()

    def get_items_by_category(self, category_slug: str) -> list[dict]:
        """Get all menu items in a given high-level category (drink, food, etc.).

        Args:
            category_slug: The category slug (e.g., "drink", "food")

        Returns:
            List of dicts with menu item info: [{"id": int, "name": str, "item_type_slug": str}]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        return self._menu_items_by_category_slug.get(category_slug, []).copy()

    def get_items_by_item_type(self, item_type_slug: str) -> list[dict]:
        """Get all menu items of a given item type.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")

        Returns:
            List of dicts with menu item info.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()

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
        self._ensure_loaded()
        alias_lower = alias.lower().strip()

        if item_type_slug:
            type_aliases = self._item_alias_to_canonical_by_type.get(item_type_slug, {})
            return type_aliases.get(alias_lower)
        else:
            for type_aliases in self._item_alias_to_canonical_by_type.values():
                if alias_lower in type_aliases:
                    return type_aliases[alias_lower]
            return None

    def get_signature_item_aliases(self) -> dict[str, str]:
        """Get signature item alias mapping.

        Returns:
            Dict mapping lowercase alias -> menu item name (with original casing).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._signature_item_aliases.copy()

    def is_signature_item(self, menu_item_name: str) -> bool:
        """Check if a menu item is a signature item.

        Args:
            menu_item_name: The menu item name to check (case-insensitive)

        Returns:
            True if the item is a signature item, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return (
            menu_item_name in self._signature_item_types
            or menu_item_name in self._signature_item_aliases.values()
        )

    def get_item_type_for_menu_item(self, menu_item_name: str) -> str | None:
        """Get the item type slug for a menu item.

        Args:
            menu_item_name: The canonical menu item name (e.g., "The Classic BEC")

        Returns:
            The item type slug (e.g., "egg_sandwich") or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        result = self._signature_item_types.get(menu_item_name)
        if result:
            return result

        item_info = self._menu_index.get(menu_item_name, {})
        return item_info.get("item_type")

    def resolve_menu_item_alias(self, name: str) -> str | None:
        """Resolve a menu item name or alias to its canonical menu item name.

        Args:
            name: User input like "tuna salad", "blt", "cheese omelette"

        Returns:
            Canonical MenuItem.name or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        name_lower = name.lower().strip()
        return self._menu_item_alias_to_canonical.get(name_lower)

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
        self._ensure_loaded()
        term_lower = term.lower().strip()

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

    def get_side_items(self) -> set[str]:
        """Get all known side item names and aliases (lowercase).

        Returns:
            Set of side item names and their aliases, all lowercase.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no side items found
        """
        from ..exceptions import MenuDataNotLoadedError
        self._ensure_loaded()
        if not self._side_items:
            raise MenuDataNotLoadedError(
                "No side items found in database. "
                "Check that menu_items table has items in 'side' category."
            )
        return self._side_items.copy()

    def resolve_side_alias(self, name: str) -> str | None:
        """Resolve a side item name or alias to its canonical menu item name.

        Args:
            name: User input like "sausage", "latke", "bacon"

        Returns:
            Canonical MenuItem.name or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        name_lower = name.lower().strip()
        return self._side_alias_to_canonical.get(name_lower)

    def search_menu_items_by_name(self, term: str) -> list[dict]:
        """Find menu items where the name contains the search term.

        Args:
            term: Search term (e.g., "muffin", "cookie", "chip")

        Returns:
            List of matching menu item dicts.
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()
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

    def find_items_by_word_match(
        self,
        word: str,
        item_type_slug: str | None = None,
    ) -> list[dict]:
        """Find menu items where the word appears as a complete word in the name.

        Uses word boundary matching (not substring).
        Example: "tea" matches "Hot Tea", "Iced Tea" but NOT "Cheesesteak"

        Args:
            word: The word to search for
            item_type_slug: Optional item type to restrict search

        Returns:
            List of matching menu item dicts with name, item_type, base_price.
        """
        self._ensure_loaded()
        word_lower = word.lower().strip()

        if not word_lower:
            return []

        # Word boundary pattern - matches whole words only
        word_pattern = re.compile(rf'\b{re.escape(word_lower)}\b', re.IGNORECASE)

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

            if word_pattern.search(item_name):
                seen_names.add(item_name_lower)
                matches.append({
                    "name": item_info.get("name", item_name),
                    "item_type": item_type or "menu_item",
                    "base_price": item_info.get("base_price", 0.0),
                })

        return matches

    def get_menu_item_names_by_category(self, category_slug: str) -> set[str]:
        """Get all menu item names that belong to a category.

        Args:
            category_slug: Category slug (e.g., "beverage", "bagel", "sandwich")

        Returns:
            Set of menu item names and aliases in that category
        """
        self._ensure_loaded()
        names = set()

        for item_name, item_info in self._menu_index.items():
            item_category = item_info.get("category", "")
            if item_category == category_slug or category_slug in item_category.lower():
                names.add(item_name)
                aliases = item_info.get("aliases", [])
                if aliases:
                    names.update(aliases)

        for item_name, item_info in self._menu_index.items():
            item_type = item_info.get("item_type", "")
            if item_type:
                modifier_cat = self.get_modifier_category(item_type)
                if modifier_cat == category_slug:
                    names.add(item_name)
                    aliases = item_info.get("aliases", [])
                    if aliases:
                        names.update(aliases)

        return names

    def find_menu_item_matches(self, query: str) -> list[str]:
        """Find menu items that match a partial query.

        Args:
            query: User input like "classic" or "blt"

        Returns:
            List of matching menu item names.
        """
        query_lower = query.lower().strip()

        if not query_lower:
            return []

        if query_lower in self._known_menu_items:
            return [query_lower]

        matches = set()
        for word in query_lower.split():
            if word in self._menu_item_keyword_index:
                matches.update(self._menu_item_keyword_index[word])

        if not matches and len(query_lower) >= 3:
            for item in self._known_menu_items:
                if query_lower in item:
                    matches.add(item)

        return sorted(matches)

    def get_menu_index(self, store_id: str | None = None) -> dict[str, Any]:
        """Get the cached menu index.

        Args:
            store_id: Optional store ID (currently not used)

        Returns:
            The cached menu index dict.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._menu_index

    def get_question_for_field(self, item_type_slug: str, field_name: str) -> str | None:
        """Get the question text for a specific field of an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")
            field_name: The field name (e.g., "toasted", "size")

        Returns:
            The question_text for the field, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        fields = self._item_type_fields.get(item_type_slug, [])
        for field in fields:
            if field["field_name"] == field_name:
                return field.get("question_text")
        return None

    def search_menu_items_for_recommendation(self, term: str) -> list[dict]:
        """Search menu items by partial name/alias match for recommendations.

        Args:
            term: Search term (already singularized), e.g., "tea", "bagel", "snack"

        Returns:
            List of matching items.
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()

        if not term_lower:
            return []

        matches: dict[int, dict] = {}

        if term_lower in self._recommendation_keyword_index:
            for name_lower in self._recommendation_keyword_index[term_lower]:
                item_data = self._all_menu_items_by_name.get(name_lower)
                if item_data and item_data["id"] not in matches:
                    matches[item_data["id"]] = item_data

        for name_lower, item_data in self._all_menu_items_by_name.items():
            if term_lower in name_lower and item_data["id"] not in matches:
                matches[item_data["id"]] = item_data

        return list(matches.values())

    def search_item_type_for_recommendation(self, term: str) -> str | None:
        """Search for an item type that matches the term for recommendations.

        Args:
            term: Search term (e.g., "tea", "bagel")

        Returns:
            Item type slug if match found, None otherwise.
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()

        if term_lower in self._category_keywords:
            return self._category_keywords[term_lower].get("slug")

        for keyword, info in self._category_keywords.items():
            if term_lower in keyword:
                return info.get("slug")

        return None

    def get_menu_items_by_unit_type(self, unit_type: str) -> set[str]:
        """Get menu item names by unit type.

        Args:
            unit_type: The unit type (e.g., "each", "by_weight", "dozen")

        Returns:
            Set of item names (lowercase) in that unit type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._by_unit_type_items.get(unit_type, set()).copy()

    def find_item_by_unit_type(self, item_name: str, unit_type: str) -> tuple[str, str] | None:
        """Find an item by name/alias within a specific unit type.

        Args:
            item_name: The item name or alias to look up
            unit_type: The unit type to search in

        Returns:
            Tuple of (canonical_name, item_type_slug) or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        name_lower = item_name.lower().strip()
        unit_aliases = self._unit_type_aliases.get(unit_type, {})
        return unit_aliases.get(name_lower)

    def get_status(self) -> dict[str, Any]:
        """Get cache status information."""
        from datetime import datetime
        return {
            "is_loaded": self._is_loaded,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "counts": {
                "known_menu_items": len(self._known_menu_items),
                "item_type_fields": sum(len(fields) for fields in self._item_type_fields.values()),
                "response_patterns": sum(len(p) for p in self._response_patterns.values()),
                "modifier_qualifiers": len(self._modifier_qualifiers),
                "compound_phrases": len(self._compound_phrases),
                "item_type_triggers": sum(len(t) for t in self._item_type_triggers.values()),
                "by_unit_type_items": {k: len(v) for k, v in self._by_unit_type_items.items()},
                "unit_type_aliases": {k: len(v) for k, v in self._unit_type_aliases.items()},
                "item_names_by_type": {k: len(v) for k, v in self._item_names_by_type.items()},
                "ingredients_by_category": {k: len(v) for k, v in self._ingredients_by_category.items()},
            },
            "keyword_indices": {
                "menu_item_keywords": len(self._menu_item_keyword_index),
            },
        }
