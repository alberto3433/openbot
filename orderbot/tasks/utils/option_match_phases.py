"""
Match phase methods extracted from OptionMatcher.

Provides MatchPhasesMixin with the multi-phase matching algorithm:
- Phase 0: Raw exact match (before normalization)
- Phase 1: Normalized exact match
- Phase 2: Partial match - user input in option name
- Phase 3: Partial match - option name in user input
- Helper methods: _passes_must_match, _get_aliases, _is_whole_word_match
"""

from __future__ import annotations

import logging

from .text import normalize_text, word_boundary_match

logger = logging.getLogger(__name__)


class MatchPhasesMixin:
    """Mixin providing multi-phase matching methods for OptionMatcher."""

    def _phase_raw_exact_match(
        self, user_raw_lower: str, options: list[dict], original_input: str
    ) -> dict | None:
        """Phase 0: Try exact match with raw (un-normalized) input."""
        for opt in options:
            if not self._passes_must_match(original_input, opt):
                continue
            display_lower = opt["display_name"].lower()
            if display_lower == user_raw_lower:
                return opt
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable == user_raw_lower:
                return opt
            for alias in self._get_aliases(opt):
                if alias.lower() == user_raw_lower:
                    return opt
        return None

    def _phase_normalized_exact_match(
        self, user_lower: str, options: list[dict], original_input: str
    ) -> dict | None:
        """Phase 1: Exact matches with normalized input."""
        for opt in options:
            if not self._passes_must_match(original_input, opt):
                continue
            display_lower = opt["display_name"].lower()
            display_normalized = self.normalizer.normalize_for_matching(display_lower)
            if display_normalized == user_lower:
                return opt
            slug_readable = opt["slug"].replace("_", " ")
            slug_normalized = self.normalizer.normalize_for_matching(slug_readable)
            if slug_normalized == user_lower:
                return opt
            for alias in self._get_aliases(opt):
                alias_normalized = self.normalizer.normalize_for_matching(alias)
                if alias_normalized == user_lower:
                    return opt
        return None

    def _phase_partial_input_in_option(
        self, user_lower: str, options: list[dict], original_input: str
    ) -> list[dict]:
        """Phase 2: User input is contained in option name (partial match)."""
        partial_matches = []
        for opt in options:
            if not self._passes_must_match(original_input, opt):
                continue
            display_lower = opt["display_name"].lower()
            if self._is_whole_word_match(user_lower, display_lower):
                partial_matches.append(opt)
                continue
            slug_readable = opt["slug"].replace("_", " ")
            if self._is_whole_word_match(user_lower, slug_readable):
                if opt not in partial_matches:
                    partial_matches.append(opt)
                continue
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and self._is_whole_word_match(user_lower, alias_lower):
                    if opt not in partial_matches:
                        partial_matches.append(opt)
                    break
        return partial_matches

    def _phase_partial_option_in_input(
        self, user_lower: str, options: list[dict], original_input: str
    ) -> dict | None:
        """Phase 3: Option name is contained in user input.

        Collects all matches and returns the one with the longest matching
        text, so that "Gluten Free Cinnamon Raisin Bagel" beats
        "Cinnamon Raisin Bagel" when both appear in the input.
        """
        best_match: dict | None = None
        best_length = 0

        for opt in options:
            if not self._passes_must_match(original_input, opt):
                continue
            display_lower = opt["display_name"].lower()
            if display_lower in user_lower and self._is_whole_word_match(display_lower, user_lower):
                if len(display_lower) > best_length:
                    best_match = opt
                    best_length = len(display_lower)
                continue
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable in user_lower and self._is_whole_word_match(slug_readable, user_lower):
                if len(slug_readable) > best_length:
                    best_match = opt
                    best_length = len(slug_readable)
                continue
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and alias_lower in user_lower:
                    if self._is_whole_word_match(alias_lower, user_lower):
                        if len(alias_lower) > best_length:
                            best_match = opt
                            best_length = len(alias_lower)
                        break
        return best_match

    def _passes_must_match(self, user_input: str, opt: dict) -> bool:
        """
        Check if option passes must_match requirement.

        If opt has must_match strings, at least one must be present in user_input.
        If no must_match is set, returns True (no restriction).
        """
        must_match_raw = opt.get("must_match")
        if not must_match_raw:
            return True

        user_lower = user_input.lower()
        if isinstance(must_match_raw, str):
            must_match_list = [normalize_text(m) for m in must_match_raw.split(",") if m.strip()]
        else:
            must_match_list = [str(m).lower() for m in must_match_raw]

        for must_str in must_match_list:
            if self._is_whole_word_match(must_str, user_lower):
                logger.debug(
                    "MUST_MATCH PASSED: '%s' contains '%s' for option '%s'",
                    user_input, must_str, opt.get("display_name")
                )
                return True

        logger.debug(
            "MUST_MATCH FAILED: '%s' does not contain any of %s for option '%s'",
            user_input, must_match_list, opt.get("display_name")
        )
        return False

    def _get_aliases(self, opt: dict) -> list[str]:
        """Get aliases from option, handling both pipe and comma separated formats."""
        from .disambiguation_utils import get_aliases
        return get_aliases(opt)

    def _is_whole_word_match(self, needle: str, haystack: str) -> bool:
        """Check if needle appears as a whole word/phrase in haystack."""
        return word_boundary_match(needle, haystack)
