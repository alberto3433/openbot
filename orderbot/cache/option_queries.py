"""
Option query mixin for MenuDataCache.

Contains methods for querying and resolving attribute options.
"""

import logging

logger = logging.getLogger(__name__)


class OptionQueryMixin:
    """Mixin containing option resolution query methods."""

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

        Includes both global attribute options and item-type-specific attribute
        options (including boolean attribute display names like "iced", "toasted").

        Returns:
            Dict mapping option word -> attribute slug

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        result: dict[str, str] = {}

        # Global attribute options
        for attr_slug, options in self._global_attribute_options.items():
            for opt in options:
                slug = opt.get("slug", "").lower()
                display = opt.get("display_name", "").lower()
                if slug:
                    result[slug] = attr_slug
                if display and display != slug:
                    result[display] = attr_slug

        # Item-type-specific attribute options (e.g., "iced", "decaf", "toasted")
        for item_type_slug, attrs in self._item_type_attributes.items():
            for attr_slug, attr_config in attrs.items():
                input_type = attr_config.get("input_type")

                # Boolean attributes: add display_name as keyword (e.g., "iced", "toasted")
                if input_type == "boolean":
                    display_name = attr_config.get("display_name", attr_slug).lower()
                    if display_name and display_name not in result:
                        result[display_name] = attr_slug

                # Single/multi select: add option slugs and display names
                for opt in attr_config.get("options", []):
                    slug = opt.get("slug", "").lower()
                    display = opt.get("display_name", "").lower()
                    if slug and slug not in result:
                        result[slug] = attr_slug
                    if display and display != slug and display not in result:
                        result[display] = attr_slug

        # Menu item variant prefixes (e.g., "hot" from "Hot Coffee", "iced" from "Iced Coffee")
        # Derived from data: if multiple items share a suffix but differ in first word, those are variants
        items_by_type = self._menu_index.get("items_by_type", {})
        for item_type_slug, items in items_by_type.items():
            # Group items by their suffix (all words except the first)
            suffix_to_prefixes: dict[str, set[str]] = {}
            for item in items:
                name = item.get("name", "")
                words = name.lower().split()
                if len(words) >= 2:
                    prefix = words[0]
                    suffix = " ".join(words[1:])
                    if suffix not in suffix_to_prefixes:
                        suffix_to_prefixes[suffix] = set()
                    suffix_to_prefixes[suffix].add(prefix)

            # If a suffix has multiple prefixes, those prefixes are variants
            for suffix, prefixes in suffix_to_prefixes.items():
                if len(prefixes) > 1:
                    for prefix in prefixes:
                        if prefix not in result:
                            result[prefix] = f"_variant_{item_type_slug}"

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

    def get_unavailable_size_terms(self) -> dict[str, str]:
        """Get unavailable size terms mapped to their display names.

        Returns terms (slugs and aliases) for size options where is_available=False.
        Used to detect when users request sizes not on our menu.

        Returns:
            Dict mapping lowercase term -> display name
            e.g., {"medium": "Medium", "med": "Medium", "tall": "Tall"}

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        self._ensure_loaded()
        result: dict[str, str] = {}

        options = self._global_attribute_options.get("size", [])
        for opt in options:
            if not opt.get("is_available", True):
                slug = opt.get("slug", "")
                display_name = opt.get("display_name", slug)
                if slug:
                    result[slug.lower()] = display_name
                # Also add aliases
                aliases = opt.get("aliases")
                if aliases:
                    for alias in aliases:
                        result[alias.lower()] = display_name

        return result
