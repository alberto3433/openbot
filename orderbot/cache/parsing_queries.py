"""
Parsing query mixin for MenuDataCache.

Contains methods for response patterns, parsing helpers, and text matching.
"""

import re
import logging
from typing import Pattern

from .base import ensure_cache_loaded, _SMART_QUOTE_MAP

logger = logging.getLogger(__name__)


class ParsingQueryMixin:
    """Mixin containing parsing-related query methods."""

    @ensure_cache_loaded
    def get_response_patterns(self, pattern_type: str) -> set[str]:
        """Get all patterns for a response type.

        Args:
            pattern_type: The type of response (affirmative, negative, cancel, done)

        Returns:
            Set of patterns for the type, or empty set if pattern_type not found.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._response_patterns.get(pattern_type, set()).copy()

    @ensure_cache_loaded
    def is_response_type(self, text: str, pattern_type: str) -> bool:
        """Check if text matches a response pattern type.

        Args:
            text: User input to check
            pattern_type: The type of response to check

        Returns:
            True if text matches any pattern of the given type.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        normalized = text.lower().strip()
        # Normalize smart quotes from speech-to-text input (U+2018/2019/201C/201D)
        normalized = normalized.translate(_SMART_QUOTE_MAP)

        exact_patterns = self._response_patterns.get(pattern_type, set())
        if normalized in exact_patterns:
            return True

        regex = self._response_regex_compiled.get(pattern_type)
        if regex and regex.match(normalized):
            return True

        return False

    def is_affirmative(self, text: str) -> bool:
        """Check if text is an affirmative response.

        Args:
            text: User input to check

        Returns:
            True if text is affirmative.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self.is_response_type(text, "affirmative")

    def is_negative(self, text: str) -> bool:
        """Check if text is a negative response.

        Args:
            text: User input to check

        Returns:
            True if text is negative.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self.is_response_type(text, "negative")

    def is_done(self, text: str) -> bool:
        """Check if text is a done signal.

        Args:
            text: User input to check

        Returns:
            True if text is a done signal.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self.is_response_type(text, "done")

    def is_greeting(self, text: str) -> bool:
        """Check if text is a greeting.

        Args:
            text: User input to check

        Returns:
            True if text is a greeting.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self.is_response_type(text, "greeting")

    @ensure_cache_loaded
    def get_standalone_instruction_patterns(self) -> list[Pattern]:
        """Get compiled patterns for standalone instructions.

        Returns individual patterns (without ^ and $ anchors) that can be used
        to search for instructions within a larger input text.

        Returns:
            List of compiled regex patterns for standalone instructions.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        patterns = []

        # Return individual patterns without anchors (for searching within text)
        raw_patterns = self._response_regex_raw.get("standalone_instruction", [])
        for pattern_str in raw_patterns:
            try:
                patterns.append(re.compile(pattern_str, re.IGNORECASE))
            except re.error:
                pass

        return patterns

    @ensure_cache_loaded
    def get_item_type_triggers(self, item_type_slug: str | None = None) -> dict[str, set[str]] | set[str]:
        """Get item type trigger keywords.

        Args:
            item_type_slug: Optional specific item type to get triggers for.
                           If None, returns all triggers.

        Returns:
            If item_type_slug is provided: set of trigger keywords for that type
            If None: dict mapping item_type_slug -> set of triggers

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        if item_type_slug:
            return self._item_type_triggers.get(item_type_slug, set()).copy()
        return {k: v.copy() for k, v in self._item_type_triggers.items()}

    @ensure_cache_loaded
    def get_all_triggers_flat(self) -> set[str]:
        """Get all item type triggers as a flat set of lowercase strings.

        Returns:
            Set of all trigger keywords across all item types, lowercased.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        result: set[str] = set()
        for trigger_set in self._item_type_triggers.values():
            result.update(t.lower() for t in trigger_set)
        return result

    @ensure_cache_loaded
    def get_configurable_item_type_slugs(self) -> set[str]:
        """Get slugs of item types that have askable attributes.

        Returns:
            Set of configurable item type slugs.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        return self._configurable_item_type_slugs.copy()

    @ensure_cache_loaded
    def get_configurable_item_names(self) -> set[str]:
        """Get all item names for configurable item types.

        Returns:
            Set of item names (lowercase) from configurable item types.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        if self._configurable_item_names is not None:
            return self._configurable_item_names.copy()

        result = set()
        for item_type_slug in self._configurable_item_type_slugs:
            names = self._item_names_by_type.get(item_type_slug, set())
            result.update(names)

        self._configurable_item_names = result
        return result.copy()

    @ensure_cache_loaded
    def text_matches_exclusion_phrase(self, text: str) -> bool:
        """Check if text contains an item with required match phrases.

        This is used to detect items like "coffee cake" that should NOT
        match generic patterns for "coffee".

        Args:
            text: User input text (lowercase)

        Returns:
            True if the text matches an item with required phrases.

        Raises:
            MenuDataNotLoadedError: If cache is not loaded
        """
        text_lower = text.lower()

        for item_name, phrases in self._items_with_required_phrases.items():
            if item_name in text_lower:
                # Check if required phrases are present
                for phrase in phrases.split(","):
                    phrase = phrase.strip().lower()
                    if phrase and phrase in text_lower:
                        return True

        return False
