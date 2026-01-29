"""
Item type query mixin for MenuDataCache.

Contains methods for querying item types, attributes, and configuration.
"""

import logging
from typing import Any

from .base import singularize

logger = logging.getLogger(__name__)


class ItemTypeQueryMixin:
    """Mixin containing item type and attribute query methods."""

    def get_all_item_type_slugs(self) -> set[str]:
        """Get all available item type slugs.

        Returns:
            Set of item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return set(self._item_names_by_type.keys())

    def get_item_type_names_for_regex(self) -> list[str]:
        """Get item type names/aliases for use in regex patterns.

        Returns names and aliases sorted by length (longest first) for
        proper regex matching.

        Returns:
            List of item type names/aliases for regex patterns.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        names = []
        for keyword, info in self._category_keywords.items():
            if info.get("lookup_type") == "item_type":
                names.append(keyword)
        return sorted(names, key=len, reverse=True)

    def get_modifier_category(self, item_type_slug: str) -> str | None:
        """Get the modifier category for an item type.

        Args:
            item_type_slug: The item type slug (e.g., "bagel", "sized_beverage")

        Returns:
            Modifier category ("food", "beverage", or None).

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_type_modifier_categories.get(item_type_slug)

    def get_item_keywords(self) -> set[str]:
        """Get all item keywords for disambiguation.

        Returns:
            Set of keywords including menu item names and item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._item_keywords.copy()

    def get_configurable_item_types(self) -> set[str]:
        """Get item types that have attributes defined.

        Returns:
            Set of item type slugs that are configurable.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._configurable_item_types.copy()

    def item_type_has_side_choice(self, item_type_slug: str) -> bool:
        """Check if an item type has a side choice attribute.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has side choice.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("has_side_choice", False)

    def get_side_choice_attribute(self, item_type_slug: str) -> dict | None:
        """Get side choice attribute details for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            Dict with slug, question_text, display_name, or None.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        config = self._item_type_side_choice.get(item_type_slug, {})
        return config.get("side_choice_attribute")

    def get_global_attribute_options(self, attr_slug: str) -> list[dict]:
        """Get options for a global attribute.

        Args:
            attr_slug: The global attribute slug (e.g., "size", "temperature")

        Returns:
            List of option dicts with slug, display_name, price_modifier, etc.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._global_attribute_options.get(attr_slug, []).copy()

    def get_all_global_attribute_aliases(self) -> dict[str, str]:
        """Get all global attribute aliases.

        Returns:
            Dict mapping alias -> attribute slug.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self._global_attribute_aliases.copy()

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

    def get_global_option_display_name(self, attr_slug: str, option_slug: str) -> str | None:
        """Get the display name for a specific option within a global attribute.

        Args:
            attr_slug: The attribute slug (e.g., "bread", "size")
            option_slug: The option slug (e.g., "garlic", "large")

        Returns:
            The option's display name if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        options = self._global_attribute_options.get(attr_slug, [])
        option_slug_lower = option_slug.lower()
        for opt in options:
            if opt.get("slug", "").lower() == option_slug_lower:
                return opt.get("display_name")
        return None

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

    def get_multi_select_attribute_slugs(self, item_type_slug: str) -> set[str]:
        """Get all multi-select attribute slugs for an item type.

        This is used to determine which attributes support adding multiple
        selections (e.g., syrups, sweeteners, extras).

        Args:
            item_type_slug: The item type slug

        Returns:
            Set of attribute slugs that are multi-select type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        result: set[str] = set()
        attrs = self.get_item_type_attributes(item_type_slug)
        for attr_slug, attr_config in attrs.items():
            if attr_config.get("input_type") == "multi_select":
                result.add(attr_slug)
        return result

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

    def get_scannable_modifier_categories(self, item_type_slug: str) -> list[str]:
        """Get modifier categories that can be scanned for an item type.

        Args:
            item_type_slug: The item type slug

        Returns:
            List of scannable modifier category slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        modifier_type = self.get_modifier_category(item_type_slug)
        if not modifier_type:
            return []
        return self.get_ordered_ingredient_categories(modifier_type)

    def item_accepts_input_modifiers(self, item_type_slug: str) -> bool:
        """Check if an item type accepts input modifiers.

        Args:
            item_type_slug: The item type slug

        Returns:
            True if the item type has a modifier category defined.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        return self.get_modifier_category(item_type_slug) is not None

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

    def resolve_option_by_alias(self, attr_slug: str, input_value: str) -> dict | None:
        """Resolve an option by value or alias within a global attribute.

        Args:
            attr_slug: The attribute slug
            input_value: The value or alias to look up

        Returns:
            The option dict if found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        options = self._global_attribute_options.get(attr_slug, [])
        input_lower = input_value.lower().strip()

        for opt in options:
            if opt.get("slug", "").lower() == input_lower:
                return opt
            if opt.get("display_name", "").lower() == input_lower:
                return opt
            aliases = opt.get("aliases")
            if aliases:
                alias_list = [a.strip().lower() for a in aliases]
                if input_lower in alias_list:
                    return opt

        return None

    def resolve_item_type_slug(self, name_or_alias: str) -> str:
        """Resolve an item type name or alias to its canonical database slug.

        Args:
            name_or_alias: Item type name or alias. Case-insensitive.

        Returns:
            The canonical item type slug from the database.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        name_lower = name_or_alias.lower().strip()
        category_info = self._category_keywords.get(name_lower)

        if category_info and "slug" in category_info:
            return category_info["slug"]

        return name_or_alias

    def infer_item_type_from_text(self, text: str) -> dict | None:
        """Infer item type by checking if any category keyword appears in the text.

        Args:
            text: User input text like "orange juice" or "blueberry muffin"

        Returns:
            Dict with item type info if a keyword is found, None otherwise.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        text_lower = text.lower()
        words = text_lower.split()

        for word in words:
            if word in self._category_keywords:
                return self._category_keywords[word]

        for keyword, info in self._category_keywords.items():
            if " " in keyword and keyword in text_lower:
                return info

        return None

    def get_item_type_display_name(self, item_type_slug: str, plural: bool = False) -> str:
        """Get the display name for an item type slug.

        Args:
            item_type_slug: The item type slug (e.g., "sized_beverage", "bagel")
            plural: If True, return plural form for suggestions

        Returns:
            Display name string. Returns slug if not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()

        info = self._category_keywords.get(item_type_slug)
        if info:
            if plural:
                return info.get("display_name_plural", info.get("display_name", item_type_slug) + "s")
            return info.get("display_name", item_type_slug)

        return item_type_slug

    def is_known_attribute_option(self, word: str) -> tuple[bool, str | None]:
        """Check if a word is a known attribute option value.

        Args:
            word: Word to check (e.g., "large", "iced", "hot")

        Returns:
            Tuple of (is_known, attribute_slug)

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        word_lower = word.lower().strip()

        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                if opt.get("slug", "").lower() == word_lower:
                    return True, attr_slug
                if opt.get("display_name", "").lower() == word_lower:
                    return True, attr_slug
        return False, None

    def get_all_attribute_option_words(self) -> dict[str, str]:
        """Get all known attribute option words mapped to their attribute slug.

        Returns:
            Dict mapping option word -> attribute slug

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        result: dict[str, str] = {}

        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                slug = opt.get("slug", "").lower()
                display = opt.get("display_name", "").lower()
                if slug:
                    result[slug] = attr_slug
                if display and display != slug:
                    result[display] = attr_slug
        return result

    def get_all_config_answer_words(self) -> set[str]:
        """Get all valid configuration answer words from the database.

        Returns:
            Set of lowercase answer words

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        answers: set[str] = set()

        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                slug = opt.get("slug", "").lower()
                display = opt.get("display_name", "").lower()
                if slug:
                    answers.add(slug)
                if display:
                    answers.add(display)
                aliases = opt.get("aliases")
                if aliases:
                    for alias in aliases:
                        answers.add(alias.lower())

        if self._side_items:
            answers.update(self._side_items)

        for item_type_slug, fields in self._item_type_fields.items():
            for field in fields:
                input_type = field.get("input_type", "")
                if input_type == "boolean":
                    field_name = field.get("field_name", "").lower()
                    display_name = field.get("display_name", "").lower()
                    if field_name:
                        answers.add(field_name)
                        answers.add(f"not {field_name}")
                        answers.add(f"un{field_name}")
                    if display_name and display_name != field_name:
                        answers.add(display_name)
                        answers.add(f"not {display_name}")
                        answers.add(f"un{display_name}")

        return answers

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
