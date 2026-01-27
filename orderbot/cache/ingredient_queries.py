"""
Ingredient query mixin for MenuDataCache.

Contains methods for querying ingredients, modifiers, and aliases.
"""

import re
import logging

logger = logging.getLogger(__name__)


class IngredientQueryMixin:
    """Mixin containing ingredient and modifier query methods."""

    def get_ingredients(self, category: str) -> set[str]:
        """Get all ingredient names and aliases for a given category.

        Args:
            category: The ingredient category (e.g., "protein", "cheese", "topping", "spread")

        Returns:
            Set of lowercase ingredient names and aliases for matching user input.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        if category not in self._ingredients_by_category:
            return set()
        return self._ingredients_by_category[category].copy()

    def get_ingredient_details(self, category: str) -> list[dict]:
        """Get full ingredient details for a category (slug, name, patterns).

        Args:
            category: The ingredient category

        Returns:
            List of ingredient detail dicts.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        if category not in self._ingredient_details_by_category:
            return []
        return [detail.copy() for detail in self._ingredient_details_by_category[category]]

    def get_all_ingredients(self) -> dict[str, dict]:
        """Get all ingredients across all categories.

        Returns:
            Dict mapping ingredient name (lowercase) -> {"name": str, "category": str, "slug": str}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        result: dict[str, dict] = {}
        for category, details in self._ingredient_details_by_category.items():
            for detail in details:
                name_lower = detail.get("name", "").lower()
                if name_lower:
                    result[name_lower] = {
                        "name": detail.get("name", ""),
                        "category": category,
                        "slug": detail.get("slug", ""),
                    }
        return result

    def get_ingredient_display_name(self, slug: str) -> str | None:
        """Get the display name for an ingredient by its slug.

        Args:
            slug: The ingredient slug to look up

        Returns:
            The display name from the database, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        slug_lower = slug.lower()
        for details_list in self._ingredient_details_by_category.values():
            for detail in details_list:
                if detail.get("slug", "").lower() == slug_lower:
                    return detail.get("name")
        return None

    def get_ingredients_for_item_type(
        self, item_type_slug: str, category: str | None = None
    ) -> set[str]:
        """Get ingredients valid for a specific ItemType, optionally filtered by category.

        Args:
            item_type_slug: The ItemType slug (e.g., "bagel", "sandwich")
            category: Optional ingredient category to filter by

        Returns:
            Set of lowercase ingredient names and aliases valid for the item type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()

        type_ingredients = self._ingredients_for_item_type.get(item_type_slug, {})
        if not type_ingredients:
            return set()

        if category:
            return type_ingredients.get(category, set()).copy()
        else:
            all_ingredients: set[str] = set()
            for cat_ingredients in type_ingredients.values():
                all_ingredients.update(cat_ingredients)
            return all_ingredients

    def get_ingredients_by_category_for_item_type(
        self, item_type_slug: str
    ) -> dict[str, set[str]]:
        """Get ingredients for an item type, grouped by category.

        Args:
            item_type_slug: The ItemType slug (e.g., "bagel", "sandwich")

        Returns:
            Dict mapping category slug to set of ingredient names.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded.
        """
        self._ensure_loaded()
        type_ingredients = self._ingredients_for_item_type.get(item_type_slug, {})
        return {cat: names.copy() for cat, names in type_ingredients.items()}

    def get_all_ingredient_categories(self) -> set[str]:
        """Get all available ingredient categories.

        Returns:
            Set of category slugs (e.g., {"protein", "cheese", "topping"})

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return set(self._ingredients_by_category.keys())

    def get_ingredient_category(self, ingredient_name: str) -> str | None:
        """Get the category of an ingredient by name.

        Args:
            ingredient_name: The ingredient name or alias to look up

        Returns:
            Category slug (e.g., "protein", "cheese") or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        name_lower = ingredient_name.lower().strip()

        for category, names in self._ingredients_by_category.items():
            if name_lower in names:
                return category

        return None

    def find_all_categories_for_ingredient(self, ingredient_name: str) -> list[str]:
        """Find all categories that contain an ingredient by name.

        Some ingredients may belong to multiple categories.

        Args:
            ingredient_name: The ingredient name or alias to look up

        Returns:
            List of category slugs that contain this ingredient.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        name_lower = ingredient_name.lower().strip()

        categories = []
        for category, names in self._ingredients_by_category.items():
            if name_lower in names:
                categories.append(category)

        return categories

    def get_category_attribute_slug(self, category_slug: str) -> str:
        """Get the attribute slug for an ingredient category.

        This maps ingredient categories to their corresponding attribute slugs
        for storage in the task model.

        Args:
            category_slug: The ingredient category slug (e.g., "topping", "spread")

        Returns:
            The attribute slug (often pluralized), or the category_slug if no mapping.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._ingredient_category_field_config.get(category_slug, {})
        return config.get("code_field_name", category_slug)

    def get_ingredient_categories_by_modifier_type(self, modifier_type: str) -> set[str]:
        """Get ingredient categories that belong to a modifier type.

        Args:
            modifier_type: "food" or "beverage"

        Returns:
            Set of category slugs that belong to that modifier type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._ingredient_categories_by_modifier_type.get(modifier_type, set()).copy()

    def get_ordered_ingredient_categories(self, modifier_type: str) -> list[str]:
        """Get ingredient categories for a modifier type, ordered by display_order.

        Args:
            modifier_type: "food" or "beverage"

        Returns:
            List of category slugs in display order.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        categories = self._ingredient_categories_by_modifier_type.get(modifier_type, set())

        return sorted(
            categories,
            key=lambda c: self._ingredient_category_order.get(c, 999)
        )

    def get_name_forming_categories(self) -> set[str]:
        """Get ingredient categories that form the item name.

        Name-forming categories have their ingredient display name replace
        the base menu item name. For example, a "Bagel" with bread="garlic_bagel"
        displays as "Garlic Bagel" instead of "Bagel, Garlic Bagel".

        Returns:
            Set of category slugs that are name-forming.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._name_forming_categories.copy()

    def is_name_forming_category(self, category_slug: str) -> bool:
        """Check if a category is name-forming.

        Args:
            category_slug: The ingredient category slug

        Returns:
            True if the category is name-forming, False otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return category_slug in self._name_forming_categories

    def get_ingredient_category_field_config(self, category_slug: str) -> dict | None:
        """Get field configuration for an ingredient category.

        Args:
            category_slug: The ingredient category slug

        Returns:
            Dict with code_field_name, is_multi_select, display_name or None.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._ingredient_category_field_config.get(category_slug)

    def get_ingredient_category_display_name(self, category_slug: str) -> str:
        """Get the display name for an ingredient category.

        Args:
            category_slug: The category slug (e.g., "spread", "topping")

        Returns:
            Display name or the slug itself if no display name is set.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._ingredient_category_field_config.get(category_slug, {})
        return config.get("display_name", category_slug)

    def get_ingredient_category_quantity_unit(self, category_slug: str) -> str | None:
        """Get the quantity unit for an ingredient category.

        Args:
            category_slug: The category slug (e.g., "syrup", "sweetener")

        Returns:
            Quantity unit (e.g., "pump", "packet", "piece") or None if category
            uses qualifiers (extra/light) instead of numeric quantities.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._ingredient_category_field_config.get(category_slug, {})
        return config.get("quantity_unit")

    def normalize_modifier(self, modifier: str) -> str:
        """Normalize a modifier name or alias to its canonical Ingredient name.

        Args:
            modifier: User input like "lox", "veggie", "scallion", "eggs"

        Returns:
            Canonical Ingredient.name or the original modifier if no mapping found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        modifier_lower = modifier.lower().strip()
        return self._modifier_aliases.get(modifier_lower, modifier)

    def is_known_modifier(self, word: str) -> bool:
        """Check if a word is a known modifier (ingredient or alias).

        Args:
            word: Word to check (e.g., "cheese", "bacon", "lox")

        Returns:
            True if the word is a known modifier/ingredient

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return word.lower().strip() in self._modifier_aliases

    def get_ingredient_aliases(self) -> dict[str, str]:
        """Get the mapping of ingredient aliases to canonical names.

        Returns:
            Dict mapping alias (lowercase) -> canonical ingredient name

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_aliases.copy()

    def get_all_modifier_words(self) -> set[str]:
        """Get all known modifier words (ingredients and their aliases).

        Returns:
            Set of all modifier words (lowercase)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return set(self._modifier_aliases.keys())

    def get_modifier_qualifiers(self) -> dict[str, dict]:
        """Get modifier qualifier patterns.

        Returns:
            Dict mapping pattern -> {normalized_form, category}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_qualifiers.copy()

    def get_qualifier_patterns(self) -> list[str]:
        """Get all qualifier patterns sorted by length (longest first).

        Returns:
            List of qualifier patterns.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return sorted(self._modifier_qualifiers.keys(), key=len, reverse=True)

    def get_qualifier_patterns_by_category(self, category: str) -> set[str]:
        """Get qualifier patterns for a specific category.

        Args:
            category: The qualifier category (e.g., "amount", "position")

        Returns:
            Set of patterns in that category.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._qualifier_patterns_by_category.get(category, set()).copy()

    def get_qualifier_info(self, pattern: str) -> dict | None:
        """Get info for a qualifier pattern.

        Args:
            pattern: The qualifier pattern

        Returns:
            Dict with normalized_form and category, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._modifier_qualifiers.get(pattern.lower())

    def normalize_qualifier(self, pattern: str) -> str | None:
        """Normalize a qualifier pattern to its canonical form.

        Args:
            pattern: The qualifier pattern (e.g., "lots of", "extra")

        Returns:
            The normalized form, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        info = self._modifier_qualifiers.get(pattern.lower())
        if info:
            return info.get("normalized_form")
        return None

    def get_qualifier_category(self, pattern: str) -> str | None:
        """Get the category of a qualifier pattern.

        Args:
            pattern: The qualifier pattern

        Returns:
            The category (e.g., "amount", "position"), or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        info = self._modifier_qualifiers.get(pattern.lower())
        if info:
            return info.get("category")
        return None

    def get_abbreviations(self) -> dict[str, str]:
        """Get the abbreviation-to-canonical mapping.

        Returns:
            Dict mapping abbreviation (lowercase) to canonical name (lowercase).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded or no abbreviations found
        """
        from ..exceptions import MenuDataNotLoadedError
        self._ensure_loaded()
        if not self._abbreviations:
            raise MenuDataNotLoadedError(
                "No abbreviations found in database. "
                "Check that ingredients or menu_items tables have abbreviation values."
            )
        return self._abbreviations.copy()

    def expand_abbreviations(self, text: str) -> str:
        """Expand abbreviations in the input text.

        Args:
            text: Raw user input text

        Returns:
            Text with abbreviations expanded to canonical forms.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        if not self._abbreviations:
            return text

        result = text
        for abbrev, canonical in sorted(
            self._abbreviations.items(), key=lambda x: len(x[0]), reverse=True
        ):
            pattern = rf'\b{re.escape(abbrev)}\b'
            result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

        return result

    def find_matching_ingredients(self, term: str) -> list[dict]:
        """Find all ingredients whose name or aliases contain the search term.

        This enables disambiguation when a generic term like "cream cheese"
        matches multiple specific ingredients.

        Args:
            term: Search term (e.g., "cream cheese", "syrup")

        Returns:
            List of matching ingredient dicts with name, slug, category, base_price.
            Empty list if no matches. Format matches what start_disambiguation() expects.
            If there's an exact match, returns only that one (no disambiguation needed).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        term_lower = term.lower().strip()
        exact_matches = []
        partial_matches = []
        seen_slugs = set()

        for category, details_list in self._ingredient_details_by_category.items():
            for detail in details_list:
                slug = detail.get("slug", "")
                if slug in seen_slugs:
                    continue

                name = detail.get("name", "").lower()
                aliases = [a.lower() for a in detail.get("aliases", [])]
                all_terms = [name] + aliases

                match_entry = {
                    "slug": slug,
                    "name": detail.get("name"),  # Key expected by start_disambiguation()
                    "category": category,
                    "base_price": detail.get("price_modifier", 0.0),
                }

                # Check for exact match first (term equals name or alias)
                if term_lower in all_terms:
                    seen_slugs.add(slug)
                    exact_matches.append(match_entry)
                # Check for partial/substring match
                elif any(term_lower in t or t in term_lower for t in all_terms):
                    seen_slugs.add(slug)
                    partial_matches.append(match_entry)

        # Prefer exact matches - if we have any, return only those
        if exact_matches:
            return exact_matches

        return partial_matches
