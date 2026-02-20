"""
Menu Metadata Query Mixin.

Contains methods for querying menu item metadata: fields, recommendations,
unit types, compound phrases, categories, and default ingredients.
"""

import logging
from typing import Any

from .base import ensure_cache_loaded, normalize_text

logger = logging.getLogger(__name__)


class MenuMetadataQueryMixin:
    """Mixin for menu metadata, recommendation, and unit type queries."""

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

    @ensure_cache_loaded
    def get_compound_phrases(self) -> set[str]:
        """Get all known compound phrases that shouldn't be split on 'and'.

        Returns a set of phrases (lowercase) that contain "and" but should be
        treated as single items (e.g., "bacon egg and cheese", "ham and swiss").

        Returns:
            Set of compound phrase strings.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._compound_phrases.copy()

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
