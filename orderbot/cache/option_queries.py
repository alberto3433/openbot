"""
Option query mixin for MenuDataCache.

Contains methods for querying and resolving attribute options.
"""

import logging
from typing import Any

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
