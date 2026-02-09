"""
Ingredient Repository.

Provides ingredient and modifier lookup operations.
"""

from .base import BaseRepository


class IngredientRepository(BaseRepository):
    """Repository for ingredient and modifier operations.

    Wraps cache methods related to ingredients, modifiers, and their categories.
    """

    # =========================================================================
    # Core Lookups
    # =========================================================================

    def normalize(self, modifier: str) -> str:
        """Normalize a modifier name to its canonical form.

        Args:
            modifier: The modifier name or alias

        Returns:
            Canonical modifier name (or original if no alias found)
        """
        return self._cache.normalize_modifier(modifier)

    def is_known(self, word: str) -> bool:
        """Check if a word is a known modifier.

        Args:
            word: The word to check

        Returns:
            True if known modifier, False otherwise
        """
        return self._cache.is_known_modifier(word)

    def get_display_name(self, slug: str) -> str | None:
        """Get the display name for an ingredient slug.

        Args:
            slug: The ingredient slug

        Returns:
            Display name or None
        """
        return self._cache.get_ingredient_display_name(slug)

    def get_category(self, ingredient_name: str) -> str | None:
        """Get the category for an ingredient.

        Args:
            ingredient_name: The ingredient name

        Returns:
            Category slug or None
        """
        return self._cache.get_ingredient_category(ingredient_name)

    # =========================================================================
    # Category Queries
    # =========================================================================

    def get_all_categories(self) -> set[str]:
        """Get all ingredient category slugs.

        Returns:
            Set of category slugs
        """
        return self._cache.get_all_ingredient_categories()

    def get_by_category(self, category: str) -> set[str]:
        """Get all ingredients in a category.

        Args:
            category: Category slug

        Returns:
            Set of ingredient names
        """
        return self._cache.get_ingredients(category)

    def get_category_details(self, category: str) -> list[dict]:
        """Get detailed ingredient info for a category.

        Args:
            category: Category slug

        Returns:
            List of ingredient dicts with full details
        """
        return self._cache.get_ingredient_details(category)

    def get_categories_for_item_type(
        self,
        item_type_slug: str
    ) -> dict[str, set[str]]:
        """Get ingredients grouped by category for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict mapping category to set of ingredient names
        """
        return self._cache.get_ingredients_by_category_for_item_type(item_type_slug)

    def get_category_display_name(self, category_slug: str) -> str:
        """Get the display name for an ingredient category.

        Args:
            category_slug: The category slug

        Returns:
            Display name
        """
        return self._cache.get_ingredient_category_display_name(category_slug)

    def get_category_field_config(self, category_slug: str) -> dict | None:
        """Get field configuration for an ingredient category.

        Args:
            category_slug: The category slug

        Returns:
            Field config dict or None
        """
        return self._cache.get_ingredient_category_field_config(category_slug)

    # =========================================================================
    # Search Methods
    # =========================================================================

    def find_matching(self, term: str) -> list[dict]:
        """Find ingredients matching a search term.

        Args:
            term: Search term

        Returns:
            List of matching ingredient dicts
        """
        return self._cache.find_matching_ingredients(term)

    def find_all_categories_for(self, ingredient_name: str) -> list[str]:
        """Find all categories an ingredient belongs to.

        Args:
            ingredient_name: The ingredient name

        Returns:
            List of category slugs
        """
        return self._cache.find_all_categories_for_ingredient(ingredient_name)

    def get_item_types_for(self, ingredient_name: str) -> list[dict]:
        """Get item types that use a specific ingredient.

        Args:
            ingredient_name: The ingredient name

        Returns:
            List of item type dicts
        """
        return self._cache.get_item_types_for_ingredient(ingredient_name)

    # =========================================================================
    # Validation
    # =========================================================================

    def is_valid_for_item_type(
        self,
        modifier_slug: str,
        item_type_slug: str
    ) -> bool:
        """Check if a modifier is valid for an item type.

        Args:
            modifier_slug: The modifier slug
            item_type_slug: The item type slug

        Returns:
            True if valid, False otherwise
        """
        return self._cache.is_valid_modifier_for_item_type(modifier_slug, item_type_slug)

    def get_modifier_to_category_map(self) -> dict[str, str]:
        """Get mapping from modifier slugs to their categories.

        Returns:
            Dict mapping modifier slug to category slug
        """
        return self._cache.get_modifier_to_category_map()

    # =========================================================================
    # Qualifiers & Abbreviations
    # =========================================================================

    def get_qualifier_patterns(self) -> list[str]:
        """Get all qualifier patterns sorted by length.

        Returns:
            List of qualifier patterns
        """
        return self._cache.get_qualifier_patterns()

    def get_qualifier_info(self, pattern: str) -> dict | None:
        """Get information for a qualifier pattern.

        Args:
            pattern: The qualifier pattern

        Returns:
            Dict with qualifier info or None
        """
        return self._cache.get_qualifier_info(pattern)

    def expand_abbreviations(self, text: str) -> str:
        """Expand abbreviations in text.

        Args:
            text: Text with potential abbreviations

        Returns:
            Text with abbreviations expanded
        """
        return self._cache.expand_abbreviations(text)
