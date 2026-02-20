"""
Numbered list matching methods extracted from OptionMatcher.

Provides NumberedListMatchMixin with methods for matching user input
against numbered disambiguation lists, including ordinal matching.
"""

from __future__ import annotations

import logging

from ..normalization import strip_filler_words
from .text import ORDINAL_PATTERNS

logger = logging.getLogger(__name__)


class NumberedListMatchMixin:
    """Mixin providing numbered list matching methods for OptionMatcher."""

    def match_from_numbered_list(
        self,
        user_input: str,
        options: list[dict],
        name_key: str = "name",
        slug_key: str = "slug",
    ) -> dict | None:
        """
        Match user input to an option from a numbered list (for disambiguation).

        This method is specifically designed for disambiguation scenarios where
        the user is selecting from a numbered list of options. It supports:
        - Ordinal matching: "1", "first", "2", "second", etc.
        - Exact name/slug matching
        - Alias matching
        - Partial matching (option name in user input)

        Unlike match_single(), this method:
        - Strips filler words before matching
        - Tries ordinal matching first (essential for numbered lists)
        - Does NOT try partial matching in the other direction (user input in option)
          to avoid "ham" matching "Black Forest Ham"

        Args:
            user_input: User's response to disambiguation question
            options: List of option dicts (from a numbered list)
            name_key: Key for display name in option dict (default: "name")
            slug_key: Key for slug in option dict (default: "slug")

        Returns:
            Matched option dict, or None if no match found

        Examples:
            >>> options = [{"name": "The Classic BEC"}, {"name": "The Leo"}]
            >>> matcher.match_from_numbered_list("1", options)
            {"name": "The Classic BEC"}
            >>> matcher.match_from_numbered_list("the leo", options)
            {"name": "The Leo"}
        """
        # Try raw exact match FIRST (before any normalization)
        # Handles cases like "Sugar in the Raw" where normalization would break it
        raw_lower = user_input.lower().strip()
        for opt in options:
            if opt.get(name_key, "").lower() == raw_lower:
                logger.debug("NUMBERED_LIST: Exact raw match on %s", name_key)
                return opt
            slug_readable = opt.get(slug_key, "").replace("_", " ")
            if slug_readable == raw_lower:
                logger.debug("NUMBERED_LIST: Exact raw match on %s", slug_key)
                return opt

        # Strip filler words for subsequent matching
        input_clean = strip_filler_words(user_input)

        # Try ordinal matching first ("1", "first", etc.)
        match = self._match_by_ordinal(input_clean, options, name_key)
        if match:
            logger.debug("NUMBERED_LIST: Matched by ordinal")
            return match

        # Try exact name/slug matching (with cleaned input)
        for opt in options:
            name = opt.get(name_key, "").lower()
            if name == input_clean:
                logger.debug("NUMBERED_LIST: Exact match on %s", name_key)
                return opt
            slug_readable = opt.get(slug_key, "").replace("_", " ")
            if slug_readable == input_clean:
                logger.debug("NUMBERED_LIST: Exact match on %s (slug)", slug_key)
                return opt

        # Try exact alias matching
        for opt in options:
            for alias in self._get_aliases(opt):
                if alias.lower() == input_clean:
                    logger.debug("NUMBERED_LIST: Exact alias match '%s'", alias)
                    return opt

        # Try if FULL option name is in user input
        # ("black forest ham please" -> "Black Forest Ham")
        for opt in options:
            name = opt.get(name_key, "").lower()
            if name and name in input_clean:
                logger.debug("NUMBERED_LIST: Name '%s' found in input", name)
                return opt

        # Try if FULL alias is in user input using word-boundary matching
        for opt in options:
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and self._is_whole_word_match(alias_lower, input_clean):
                    logger.debug("NUMBERED_LIST: Alias '%s' found in input", alias)
                    return opt

        # NO partial matching in the other direction!
        # We deliberately don't check if input is in option name
        # because that would make "ham" match "Black Forest Ham"

        logger.debug("NUMBERED_LIST: No match for '%s'", user_input[:50])
        return None

    def _match_by_ordinal(
        self, user_input: str, options: list[dict], name_key: str = "name"
    ) -> dict | None:
        """Match user input to an option by ordinal/number.

        Handles inputs like "first", "1", "second one", etc.

        Args:
            user_input: Cleaned user input (lowercase, filler words stripped)
            options: List of option dicts
            name_key: Key for display name

        Returns:
            Matched option dict or None
        """
        # Reject negative numbers
        if user_input.startswith('-') or user_input.startswith('\u2212'):
            return None

        for pattern, idx in ORDINAL_PATTERNS:
            if pattern in user_input or user_input == f"{pattern} one":
                if idx < len(options):
                    logger.debug(
                        "ORDINAL: Matched option %d ('%s') by pattern '%s'",
                        idx + 1, options[idx].get(name_key, ""), pattern
                    )
                    return options[idx]
                else:
                    logger.debug(
                        "ORDINAL: Pattern '%s' out of range (only %d options)",
                        pattern, len(options)
                    )
                    return None
        return None
