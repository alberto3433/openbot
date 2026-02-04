"""
Attribute query mixin for MenuDataCache.

Contains methods for querying item type attributes and their configurations.
"""

import logging

logger = logging.getLogger(__name__)


class AttributeQueryMixin:
    """Mixin containing attribute-related query methods."""

    def get_item_type_attributes(self, item_type_slug: str) -> dict:
        """Get all attribute configurations for an item type.

        All attributes are pre-loaded at startup via _preload_all_item_type_attributes().
        No lazy loading or runtime database queries are needed.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict mapping attr_slug -> attr_config dict.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_type_attributes.get(item_type_slug, {})

    def has_conversation_attributes(self, item_type_slug: str) -> bool:
        """Check if an item type has any ask_in_conversation attributes.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has conversational attributes.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)
        for attr_config in attrs.values():
            if attr_config.get("ask_in_conversation", False):
                return True
        return False

    def get_attribute_input_type(self, item_type_slug: str, attribute_slug: str) -> str | None:
        """Get the input type for a specific attribute.

        Args:
            item_type_slug: The item type slug
            attribute_slug: The attribute slug

        Returns:
            The input type (e.g., "single_select", "multi_select", "boolean") or None.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)
        attr = attrs.get(attribute_slug, {})
        return attr.get("input_type")

    def get_attribute_for_category(self, item_type_slug: str, category_slug: str) -> str | None:
        """Get the attribute slug that handles a given ingredient category.

        Args:
            item_type_slug: The item type slug
            category_slug: The ingredient category slug

        Returns:
            The attribute slug, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("ingredient_group") == category_slug:
                return attr_slug
        return None

    def get_field_to_slug_map(self, item_type_slug: str) -> dict[str, str]:
        """Get the field name to attribute slug mapping for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict mapping field names to attribute slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        # Ensure attributes are loaded first
        self.get_item_type_attributes(item_type_slug)
        return self._field_to_slug_map.get(item_type_slug, {}).copy()

    def resolve_field_to_slug(self, item_type_slug: str, field_name: str) -> str:
        """Resolve a field name to its canonical attribute slug.

        Args:
            item_type_slug: The item type slug
            field_name: The field name (may be category or attribute slug)

        Returns:
            The canonical attribute slug.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        field_map = self.get_field_to_slug_map(item_type_slug)
        return field_map.get(field_name, field_name)

    def get_field_config(self, item_type_slug: str, field_slug: str) -> dict | None:
        """Get configuration for a specific attribute field.

        Args:
            item_type_slug: The item type slug
            field_slug: The field/attribute slug

        Returns:
            The field config dict or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)
        return attrs.get(field_slug)

    def get_all_field_configs(self, item_type_slug: str) -> dict:
        """Get all field configurations for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict mapping field slug to config dict.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self.get_item_type_attributes(item_type_slug)

    def get_modifier_fields_for_item_type(self, item_type_slug: str) -> list[dict]:
        """Get modifier field definitions for an item type.

        Returns fields that load from ingredients, ordered by display_order.

        Args:
            item_type_slug: The item type slug

        Returns:
            List of modifier field config dicts.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)
        result = []
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("loads_from_ingredients"):
                result.append(attr_config)
        return sorted(result, key=lambda x: x.get("display_order", 999))

    def is_multi_select_attribute(self, attr_slug: str) -> bool:
        """Check if an attribute is a multi-select type.

        Args:
            attr_slug: The attribute slug

        Returns:
            True if the attribute is multi-select type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        metadata = self._global_attribute_metadata.get(attr_slug, {})
        return metadata.get("input_type") == "multi_select"

    def attribute_contains_modifier_category(self, attr_slug: str, modifier_category: str) -> bool:
        """Check if an attribute contains options with a given modifier category.

        Args:
            attr_slug: The attribute slug
            modifier_category: The modifier category slug

        Returns:
            True if the attribute has options with that modifier category.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attr_set = self._modifier_category_to_attrs.get(modifier_category, set())
        return attr_slug in attr_set

    def get_attribute_display_name(self, attr_slug: str) -> str:
        """Get the display name for a global attribute.

        Args:
            attr_slug: The attribute slug

        Returns:
            The display name, or the slug if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        metadata = self._global_attribute_metadata.get(attr_slug, {})
        return metadata.get("display_name", attr_slug)

    def get_property_name_for_attribute(self, attr_slug: str) -> str:
        """Get the Python property name for an attribute slug.

        Args:
            attr_slug: The attribute slug

        Returns:
            The property name, or the slug itself if no mapping.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._global_attribute_property_names.get(attr_slug, attr_slug)

    def get_all_global_attribute_aliases(self) -> dict[str, str]:
        """Get all global attribute aliases.

        Returns:
            Dict mapping alias -> attribute slug.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._global_attribute_aliases.copy()

    def get_attribute_for_ingredient_category(
        self, item_type_slug: str, ingredient_category: str
    ) -> str | None:
        """Map an ingredient category to the attribute slug for an item type.

        Used when populating signature item defaults: ingredient.category (e.g., "cheese")
        needs to map to the attribute that handles that category (e.g., "cheese" attribute).

        This method tries (data-driven, no hardcoded mappings):
        1. Attributes with ingredient_group matching the category
        2. Direct attribute slug match (if attribute slug == ingredient category)
        3. code_field_name from ingredient_categories table (e.g., protein -> extra_protein)

        Args:
            item_type_slug: The item type slug (e.g., "egg_sandwich")
            ingredient_category: The ingredient's category (e.g., "cheese", "protein", "bread")

        Returns:
            The attribute slug that handles this ingredient category, or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        attrs = self.get_item_type_attributes(item_type_slug)

        # First try: match ingredient_group
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("ingredient_group") == ingredient_category:
                return attr_slug

        # Second try: direct slug match (some categories like "cheese" match the attribute slug)
        if ingredient_category in attrs:
            return ingredient_category

        # Third try: use code_field_name from ingredient_categories table
        # This is the data-driven mapping (e.g., protein -> extra_protein)
        category_config = self._ingredient_category_field_config.get(ingredient_category, {})
        code_field = category_config.get("code_field_name")
        if code_field and code_field in attrs:
            return code_field

        # Fourth try: known category-to-attribute mappings for mismatches
        # This handles cases where ingredient.category doesn't match the attribute slug
        # e.g., egg_sandwich uses "meat" attribute but ingredient category is "protein"
        # TODO: Remove once DB has proper ingredient_group -> attribute mapping
        fallback_mappings = {
            "protein": ["meat", "extra_protein", "protein"],
            "condiment": ["spread", "toppings", "condiments"],
        }
        if ingredient_category in fallback_mappings:
            for candidate in fallback_mappings[ingredient_category]:
                if candidate in attrs:
                    return candidate

        return None

    def get_item_type_from_option_alias(self, alias: str) -> tuple[str, str, str] | None:
        """Look up item type from an attribute option alias.

        This enables inferring item type when a user orders by option name alone,
        e.g., "earl grey" -> infer item_type="tea" with tea_flavor=earl_gray.

        Args:
            alias: Option name or alias (e.g., "earl grey", "oat milk")

        Returns:
            Tuple of (item_type_slug, attribute_slug, option_slug) or None if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._option_alias_to_item_type.get(alias.lower().strip())

    def get_all_option_aliases(self) -> set[str]:
        """Get all attribute option aliases.

        Returns set of all aliases (lowercase), including multi-word aliases
        like "earl grey", "oat milk", etc.

        Returns:
            Set of lowercase alias strings

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return set(self._option_alias_to_item_type.keys())

    def get_skipped_attributes_for_option(self, option_slug: str) -> set[str]:
        """Get attributes that should be skipped when an option is selected.

        Used for data-driven question skipping. For example, selecting "black"
        for coffee means we should skip asking about milk/sweetener/syrup.

        Args:
            option_slug: The selected option's slug (e.g., "black")

        Returns:
            Set of attribute slugs to skip (e.g., {"milk_sweetener_syrup"})

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._option_skip_rules.get(option_slug, set()).copy()

    def check_skip_conflict(self, option_slug: str, modifier_category: str) -> bool:
        """Check if selecting an option conflicts with a modifier category.

        Used to detect conflicts like "black coffee with cream" - black skips
        milk-related modifiers but user also requested cream.

        Args:
            option_slug: The triggering option slug (e.g., "black")
            modifier_category: The modifier category slug (e.g., "milk")

        Returns:
            True if there's a conflict (option skips the modifier's attribute)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        skipped_attrs = self._option_skip_rules.get(option_slug, set())

        # Check if any skipped attribute contains options with this modifier category
        for attr_slug in skipped_attrs:
            if self.attribute_contains_modifier_category(attr_slug, modifier_category):
                return True
        return False

    def get_skipped_attributes_for_selections(self, selections: list[dict]) -> set[str]:
        """Get all attributes to skip based on current selections.

        Aggregates skip rules from all selected options.

        Args:
            selections: List of selection dicts with "slug" keys

        Returns:
            Set of all attribute slugs to skip

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        skipped: set[str] = set()
        for sel in selections:
            slug = sel.get("slug") if isinstance(sel, dict) else getattr(sel, "slug", None)
            if slug:
                skipped.update(self._option_skip_rules.get(slug, set()))
        return skipped
