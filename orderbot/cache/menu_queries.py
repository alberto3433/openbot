"""
Menu query mixin for MenuDataCache.

Contains methods for querying menu items, signatures, and aliases.
"""

import re
import logging
from typing import Any

from .base import ensure_cache_loaded, normalize_text, singularize

logger = logging.getLogger(__name__)


class MenuQueryMixin:
    """Mixin containing menu item query methods."""

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

    def get_item_names_by_type(self, item_type_slug: str) -> set[str]:
        """Alias for get_item_names() - get all item names for a given item type."""
        return self.get_item_names(item_type_slug)

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

        Args:
            word: The word to search for
            item_type_slug: Optional item type to restrict search

        Returns:
            List of matching menu item dicts with name, item_type, base_price.
        """
        word_lower = normalize_text(word)

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

    @ensure_cache_loaded
    def search_menu_items_by_term(self, term: str) -> list[dict]:
        """Search menu items by term in both names AND aliases using word-boundary matching.

        This is designed for menu inquiries like "what lattes do you have?" where we want
        to find ALL items containing "latte" - not just the first alias match.

        Uses word-boundary matching: "latte" matches "Hot Latte", "Iced Latte"
        but not "Latteen". Also singularizes the search term.

        Args:
            term: Search term (e.g., "latte", "muffins", "tea")

        Returns:
            List of matching menu item dicts from items_by_type, deduplicated by name.
        """
        term_lower = normalize_text(term)
        term_singular = singularize(term_lower)

        if not term_lower:
            return []

        # Build word boundary patterns for both original and singular forms
        patterns = [re.compile(rf'\b{re.escape(term_lower)}\b', re.IGNORECASE)]
        if term_singular != term_lower:
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

                # Check if term matches item name
                name_matches = any(p.search(item_name) for p in patterns)

                # Check if term matches any alias for this item
                alias_matches = False
                if not name_matches:
                    # Look up aliases for this item
                    for type_aliases in self._item_alias_to_canonical_by_type.values():
                        for alias, canonical in type_aliases.items():
                            if canonical.lower() == item_name_lower:
                                # This alias points to our item - check if term matches the alias
                                if any(p.search(alias) for p in patterns):
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

    @ensure_cache_loaded
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
        fields = self._item_type_fields.get(item_type_slug, [])
        for field in fields:
            if field["field_name"] == field_name:
                return field.get("question_text")
        return None

    @ensure_cache_loaded
    def search_menu_items_for_recommendation(self, term: str) -> list[dict]:
        """Search menu items by partial name/alias match for recommendations.

        Args:
            term: Search term (already singularized), e.g., "tea", "bagel", "snack"

        Returns:
            List of matching items.
        """
        term_lower = normalize_text(term)

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

    @ensure_cache_loaded
    def search_item_type_for_recommendation(self, term: str) -> str | None:
        """Search for an item type that matches the term for recommendations.

        Args:
            term: Search term (e.g., "tea", "bagel")

        Returns:
            Item type slug if match found, None otherwise.
        """
        term_lower = normalize_text(term)

        if term_lower in self._category_keywords:
            return self._category_keywords[term_lower].get("slug")

        for keyword, info in self._category_keywords.items():
            if term_lower in keyword:
                return info.get("slug")

        return None

    @ensure_cache_loaded
    def get_menu_items_by_unit_type(self, unit_type: str) -> set[str]:
        """Get menu item names by unit type.

        Args:
            unit_type: The unit type (e.g., "each", "by_weight", "dozen")

        Returns:
            Set of item names (lowercase) in that unit type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._by_unit_type_items.get(unit_type, set()).copy()

    @ensure_cache_loaded
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
        name_lower = normalize_text(item_name)
        unit_aliases = self._unit_type_aliases.get(unit_type, {})
        return unit_aliases.get(name_lower)

    @ensure_cache_loaded
    def find_items_by_unit_type_partial(
        self, search_term: str, unit_type: str
    ) -> list[tuple[str, str]]:
        """Find all items matching a search term within a specific unit type.

        Used for disambiguation when user says something like "salmon" and there
        are multiple salmon items (Nova Scotia Salmon, Scottish Salmon, etc.).

        Args:
            search_term: The term to search for (e.g., "salmon")
            unit_type: The unit type to search in (e.g., "by_weight")

        Returns:
            List of (canonical_name, item_type_slug) tuples for matching items.
            Returns empty list if no matches.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        term_lower = normalize_text(search_term)
        unit_aliases = self._unit_type_aliases.get(unit_type, {})

        # Find all items where the canonical name contains the search term
        # Use a set to dedupe by canonical name (multiple aliases may point to same item)
        seen = set()
        matches = []

        for alias, (canonical_name, item_type_slug) in unit_aliases.items():
            canonical_lower = canonical_name.lower()
            # Match if search term is in canonical name (word boundary preferred)
            if term_lower in canonical_lower and canonical_name not in seen:
                seen.add(canonical_name)
                matches.append((canonical_name, item_type_slug))

        return matches

    @ensure_cache_loaded
    def is_compound_phrase(self, text: str) -> bool:
        """Check if text is a known compound phrase that shouldn't be split on 'and'.

        Compound phrases like "bacon egg and cheese" are stored as menu item aliases
        and should be treated as single items rather than split into parts.

        Args:
            text: Text to check (case-insensitive)

        Returns:
            True if the text is a known compound phrase, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return normalize_text(text) in self._compound_phrases

    @ensure_cache_loaded
    def find_compound_phrase_in(self, text: str) -> str | None:
        """Find a compound phrase that appears at the start of text.

        Checks if any known compound phrase (menu item names/aliases with "and")
        matches the beginning of the input text.

        Args:
            text: Text to search in (case-insensitive)

        Returns:
            The matching compound phrase if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        text_lower = normalize_text(text)

        # Sort by length (longest first) to match most specific phrase
        for phrase in sorted(self._compound_phrases, key=len, reverse=True):
            if text_lower.startswith(phrase):
                # Ensure word boundary (end of string or non-alphanumeric)
                if len(text_lower) == len(phrase) or not text_lower[len(phrase)].isalnum():
                    return phrase
        return None

    def get_status(self) -> dict[str, Any]:
        """Get cache status information."""
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

    @ensure_cache_loaded
    def get_all_menu_item_names(self) -> list[str]:
        """Get all menu item display names for fuzzy matching.

        Returns:
            List of all menu item names (original casing preserved).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        # Extract unique display names from _menu_items
        names = set()
        for item_data in self._menu_items.values():
            name = item_data.get("name")
            if name:
                names.add(name)
        return sorted(names)

    @ensure_cache_loaded
    def get_categories_for_inference(self) -> list[dict]:
        """Get menu categories in a format suitable for LLM inference.

        Returns:
            List of dicts with 'slug' and 'display_name' for each category.
            Suitable for passing to llm_category_inference.infer_item_category().

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        categories = []

        # Add high-level menu categories (Category table)
        for slug, display_name in self._available_categories.items():
            categories.append({
                "slug": slug,
                "display_name": display_name,
            })

        # Add item types as categories (ItemType table)
        for item_type_slug, item_type_info in self._item_type_displays.items():
            display_name = item_type_info.get("display_name") or item_type_slug.replace("_", " ").title()
            # Avoid duplicates
            if not any(c["slug"] == item_type_slug for c in categories):
                categories.append({
                    "slug": item_type_slug,
                    "display_name": display_name,
                })

        return categories

    @ensure_cache_loaded
    def get_menu_item_default_ingredients(self, menu_item_id: int) -> list[dict]:
        """Get default ingredients for a signature menu item.

        Loads from menu_item_ingredients junction table, which stores the
        default configuration for signature items like "The Classic BEC".

        Args:
            menu_item_id: The database ID of the menu item

        Returns:
            List of dicts with ingredient information:
            [{
                "ingredient_id": int,
                "ingredient_slug": str,
                "ingredient_name": str,
                "ingredient_category": str,  # e.g., "bread", "protein", "cheese"
                "quantity": int,
            }]

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._menu_item_default_ingredients.get(menu_item_id, [])

    @ensure_cache_loaded
    def get_menu_item_by_id(self, menu_item_id: int) -> dict | None:
        """Get menu item information by database ID.

        Args:
            menu_item_id: The database ID of the menu item

        Returns:
            Dict with menu item info: {
                "id": int,
                "name": str,
                "item_type_slug": str | None,
                "base_price": float
            }
            or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        # Search through _menu_items (keyed by name) to find by ID
        for item_data in self._menu_items.values():
            if item_data.get("id") == menu_item_id:
                return {
                    "id": item_data["id"],
                    "name": item_data.get("name", ""),
                    "item_type_slug": item_data.get("item_type"),
                    "base_price": item_data.get("base_price", 0.0),
                }
        return None

    # =========================================================================
    # Dietary and Allergen Query Methods
    # =========================================================================

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
