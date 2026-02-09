"""
Attribute Repository.

Provides global attribute and option lookup operations.
"""

from .base import BaseRepository


class AttributeRepository(BaseRepository):
    """Repository for attribute and option operations.

    Wraps cache methods related to global attributes, item type attributes,
    and attribute options.
    """

    # =========================================================================
    # Item Type Attributes
    # =========================================================================

    def get_for_item_type(self, item_type_slug: str) -> dict:
        """Get all attributes for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict of attribute configurations
        """
        return self._cache.get_item_type_attributes(item_type_slug)

    def get_field_config(
        self,
        item_type_slug: str,
        field_slug: str
    ) -> dict | None:
        """Get configuration for a specific field.

        Args:
            item_type_slug: The item type slug
            field_slug: The field/attribute slug

        Returns:
            Field configuration dict or None
        """
        return self._cache.get_field_config(item_type_slug, field_slug)

    def get_all_field_configs(self, item_type_slug: str) -> dict:
        """Get all field configurations for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict mapping field slug to config
        """
        return self._cache.get_all_field_configs(item_type_slug)

    def has_conversation_attributes(self, item_type_slug: str) -> bool:
        """Check if an item type has attributes that should be asked in conversation.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if has askable attributes, False otherwise
        """
        return self._cache.has_conversation_attributes(item_type_slug)

    # =========================================================================
    # Attribute Metadata
    # =========================================================================

    def get_input_type(
        self,
        item_type_slug: str,
        attribute_slug: str
    ) -> str | None:
        """Get the input type for an attribute.

        Args:
            item_type_slug: The item type slug
            attribute_slug: The attribute slug

        Returns:
            Input type string (e.g., "single_select", "multi_select") or None
        """
        return self._cache.get_attribute_input_type(item_type_slug, attribute_slug)

    def get_display_name(self, attr_slug: str) -> str:
        """Get the display name for an attribute.

        Args:
            attr_slug: The attribute slug

        Returns:
            Display name
        """
        return self._cache.get_attribute_display_name(attr_slug)

    def is_multi_select(self, attr_slug: str) -> bool:
        """Check if an attribute is multi-select.

        Args:
            attr_slug: The attribute slug

        Returns:
            True if multi-select, False otherwise
        """
        return self._cache.is_multi_select_attribute(attr_slug)

    def get_for_category(
        self,
        item_type_slug: str,
        category_slug: str
    ) -> str | None:
        """Get the attribute slug for a category.

        Args:
            item_type_slug: The item type slug
            category_slug: The category slug

        Returns:
            Attribute slug or None
        """
        return self._cache.get_attribute_for_category(item_type_slug, category_slug)

    def get_for_ingredient_category(
        self,
        item_type_slug: str,
        ingredient_category: str
    ) -> str | None:
        """Get the attribute slug for an ingredient category.

        Args:
            item_type_slug: The item type slug
            ingredient_category: The ingredient category

        Returns:
            Attribute slug or None
        """
        return self._cache.get_attribute_for_ingredient_category(
            item_type_slug, ingredient_category
        )

    def get_modifier_fields(self, item_type_slug: str) -> list[dict]:
        """Get modifier fields for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            List of modifier field configs
        """
        return self._cache.get_modifier_fields_for_item_type(item_type_slug)

    # =========================================================================
    # Option Resolution
    # =========================================================================

    def get_options(self, attr_slug: str) -> list[dict]:
        """Get all options for a global attribute.

        Args:
            attr_slug: The attribute slug

        Returns:
            List of option dicts
        """
        return self._cache.get_global_attribute_options(attr_slug)

    def resolve_option(
        self,
        attr_slug: str,
        input_value: str
    ) -> dict | None:
        """Resolve an option by alias or value.

        Args:
            attr_slug: The attribute slug
            input_value: User input to resolve

        Returns:
            Option dict if found, None otherwise
        """
        return self._cache.resolve_option_by_alias(attr_slug, input_value)

    def get_option_display_name(
        self,
        attr_slug: str,
        option_slug: str
    ) -> str | None:
        """Get the display name for an option.

        Args:
            attr_slug: The attribute slug
            option_slug: The option slug

        Returns:
            Display name or None
        """
        return self._cache.get_global_option_display_name(attr_slug, option_slug)

    def is_known_option(self, word: str) -> tuple[bool, str | None]:
        """Check if a word is a known attribute option.

        Args:
            word: The word to check

        Returns:
            Tuple of (is_known, attribute_slug if known)
        """
        return self._cache.is_known_attribute_option(word)

    # =========================================================================
    # Skip Rules & Forwarding
    # =========================================================================

    def get_skipped_for_option(self, option_slug: str) -> set[str]:
        """Get attributes that should be skipped when an option is selected.

        Args:
            option_slug: The option slug

        Returns:
            Set of attribute slugs to skip
        """
        return self._cache.get_skipped_attributes_for_option(option_slug)

    def get_skipped_for_selections(self, selections: list[dict]) -> set[str]:
        """Get attributes that should be skipped for a set of selections.

        Args:
            selections: List of selection dicts

        Returns:
            Set of attribute slugs to skip
        """
        return self._cache.get_skipped_attributes_for_selections(selections)

    def check_skip_conflict(
        self,
        option_slug: str,
        modifier_category: str
    ) -> bool:
        """Check if an option has a skip conflict with a modifier category.

        Args:
            option_slug: The option slug
            modifier_category: The modifier category

        Returns:
            True if conflict exists, False otherwise
        """
        return self._cache.check_skip_conflict(option_slug, modifier_category)

    def get_forward_to(
        self,
        attr_slug: str,
        option_slug: str
    ) -> str | None:
        """Get the attribute to forward to for an option.

        Args:
            attr_slug: The attribute slug
            option_slug: The option slug

        Returns:
            Forward-to attribute slug or None
        """
        return self._cache.get_forward_to_attribute(attr_slug, option_slug)

    def get_options_with_forward(self, attr_slug: str) -> list[dict]:
        """Get options that have forward delegation.

        Args:
            attr_slug: The attribute slug

        Returns:
            List of option dicts with forward delegation
        """
        return self._cache.get_options_with_forward_delegation(attr_slug)

    # =========================================================================
    # Global Aliases
    # =========================================================================

    def get_all_option_aliases(self) -> set[str]:
        """Get all option aliases across all attributes.

        Returns:
            Set of all option aliases
        """
        return self._cache.get_all_option_aliases()

    def get_all_attribute_aliases(self) -> dict[str, str]:
        """Get mapping of all global attribute aliases.

        Returns:
            Dict mapping alias to attribute slug
        """
        return self._cache.get_all_global_attribute_aliases()

    def get_item_type_from_option_alias(
        self,
        alias: str
    ) -> tuple[str, str, str] | None:
        """Get item type info from an option alias.

        Args:
            alias: The option alias

        Returns:
            Tuple of (item_type_slug, attr_slug, option_slug) or None
        """
        return self._cache.get_item_type_from_option_alias(alias)

    def contains_modifier_category(
        self,
        attr_slug: str,
        modifier_category: str
    ) -> bool:
        """Check if an attribute contains options from a modifier category.

        Args:
            attr_slug: The attribute slug
            modifier_category: The modifier category

        Returns:
            True if attribute contains category, False otherwise
        """
        return self._cache.attribute_contains_modifier_category(
            attr_slug, modifier_category
        )
