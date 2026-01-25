"""
Unified option matching with multi-phase algorithm.

Consolidates duplicated option matching logic from:
- menu_item_config_handler._match_option_from_input()
- menu_item_config_handler._match_multiple_options_from_input()
- menu_item_config_handler._is_whole_word_match()
- menu_item_config_handler._passes_must_match()
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .input_normalizer import InputNormalizer

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class OptionMatcher:
    """
    Unified option matching with multi-phase algorithm.

    Matches user input to options using a prioritized multi-phase approach:
    1. Phase 0: Raw exact match (before normalization)
    2. Phase 1: Normalized exact match
    3. Phase 2: Partial match - user input in option name
    4. Phase 3: Partial match - option name in user input

    Supports:
    - Single-select matching (returns first match)
    - Multi-select matching (returns all matches)
    - Alias resolution (pipe-separated or comma-separated)
    - must_match filtering
    """

    def __init__(self, normalizer: InputNormalizer | None = None):
        """
        Initialize the option matcher.

        Args:
            normalizer: InputNormalizer instance. Uses default if not provided.
        """
        self.normalizer = normalizer or InputNormalizer()

    def match_single(
        self, user_input: str, options: list[dict]
    ) -> tuple[dict | None, list[dict]]:
        """
        Find first matching option with smart partial matching.

        Returns:
            (matched_option, partial_matches) tuple:
            - (option, []) = exact or unique partial match found
            - (None, [opt1, opt2, ...]) = multiple partial matches, need disambiguation
            - (None, []) = no matches at all

        Matching priority:
        1. Exact match on display_name, slug, or alias
        2. Partial match: user input is contained in option name
        3. Partial match: option name is contained in user input
        """
        user_lower = self.normalizer.normalize_for_matching(user_input)
        user_raw_lower = user_input.lower().strip()

        # Phase 0: Raw exact match (before normalization)
        match = self._phase_raw_exact_match(user_raw_lower, options, user_input)
        if match:
            return (match, [])

        # Phase 1: Normalized exact match
        match = self._phase_normalized_exact_match(user_lower, options, user_input)
        if match:
            return (match, [])

        # Phase 2: Partial match - user input in option name
        partial_matches = self._phase_partial_input_in_option(
            user_lower, options, user_input
        )
        if len(partial_matches) == 1:
            return (partial_matches[0], [])
        elif len(partial_matches) > 1:
            return (None, partial_matches)

        # Phase 3: Partial match - option name in user input
        match = self._phase_partial_option_in_input(user_lower, options, user_input)
        if match:
            return (match, [])

        return (None, [])

    def match_multiple(self, user_input: str, options: list[dict]) -> list[dict]:
        """
        Match ALL options mentioned in user input (for multi_select attributes).

        Returns list of matched options (may be empty if none found).
        Unlike match_single, this finds ALL matches, not just one.

        E.g., "milk and sugar" -> [whole_milk_option, sugar_option]
              "mayo mustard" -> [mayo_option, mustard_option]

        Supports tokenized input: splits on "and", ",", "&", etc.
        """
        user_lower = self.normalizer.normalize_for_matching(user_input)
        user_raw_lower = user_input.lower().strip()
        matched: list[dict] = []
        matched_slugs: set[str] = set()

        def add_match(opt: dict) -> bool:
            """Add option to matches if not already present."""
            if opt["slug"] not in matched_slugs:
                matched_slugs.add(opt["slug"])
                matched.append(opt)
                return True
            return False

        # Get all input variants (raw, normalized, tokenized)
        all_inputs = self.normalizer.get_all_input_variants(user_input)
        raw_tokens = [t.lower().strip() for t in self.normalizer.tokenize_multi_input(user_input)]
        normalized_tokens = [self.normalizer.normalize_for_matching(t) for t in raw_tokens]

        for opt in options:
            if not self._passes_must_match(user_input, opt):
                logger.debug(
                    "MULTI_SELECT SKIP: '%s' filtered by must_match=%s for option '%s'",
                    user_input, opt.get("must_match"), opt.get("display_name")
                )
                continue

            display_lower = opt["display_name"].lower()
            slug_readable = opt["slug"].replace("_", " ")
            display_normalized = self.normalizer.normalize_for_matching(display_lower)
            slug_normalized = self.normalizer.normalize_for_matching(slug_readable)

            # === Phase 0: Exact match with raw input ===
            if display_lower == user_raw_lower or slug_readable == user_raw_lower:
                add_match(opt)
                continue
            if display_lower in raw_tokens or slug_readable in raw_tokens:
                add_match(opt)
                continue

            # === Phase 1: Exact match with normalized input ===
            if display_normalized == user_lower or slug_normalized == user_lower:
                add_match(opt)
                continue
            if display_normalized in normalized_tokens or slug_normalized in normalized_tokens:
                add_match(opt)
                continue

            # === Direction 1: Option name/alias appears in user input ===
            if self._is_whole_word_match(display_lower, user_raw_lower):
                add_match(opt)
                continue
            if self._is_whole_word_match(slug_readable, user_raw_lower):
                add_match(opt)
                continue

            # Check aliases in user input
            alias_matched = False
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 2 and self._is_whole_word_match(alias_lower, user_raw_lower):
                    add_match(opt)
                    alias_matched = True
                    break
            if alias_matched:
                continue

            # === Direction 2: User token appears in option name ===
            for token in all_inputs:
                if not token or len(token) < 2:
                    continue
                if self._is_whole_word_match(token, display_lower):
                    add_match(opt)
                    break
                if self._is_whole_word_match(token, slug_readable):
                    add_match(opt)
                    break
                for alias in self._get_aliases(opt):
                    alias_lower = alias.lower()
                    if len(alias_lower) >= 2 and self._is_whole_word_match(token, alias_lower):
                        add_match(opt)
                        break

        return matched

    # =========================================================================
    # Matching Phases
    # =========================================================================

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
        """Phase 3: Option name is contained in user input."""
        for opt in options:
            if not self._passes_must_match(original_input, opt):
                continue
            display_lower = opt["display_name"].lower()
            if display_lower in user_lower and self._is_whole_word_match(display_lower, user_lower):
                return opt
            slug_readable = opt["slug"].replace("_", " ")
            if slug_readable in user_lower and self._is_whole_word_match(slug_readable, user_lower):
                return opt
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 3 and alias_lower in user_lower:
                    if self._is_whole_word_match(alias_lower, user_lower):
                        return opt
        return None

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_aliases(self, opt: dict) -> list[str]:
        """Get aliases from option, handling both pipe and comma separated formats."""
        aliases_raw = opt.get("aliases", [])
        if isinstance(aliases_raw, str):
            if "|" in aliases_raw:
                return [a.strip() for a in aliases_raw.split("|") if a.strip()]
            return [a.strip() for a in aliases_raw.split(",") if a.strip()]
        return aliases_raw or []

    def _is_whole_word_match(self, needle: str, haystack: str) -> bool:
        """Check if needle appears as a whole word/phrase in haystack."""
        pattern = r'\b' + re.escape(needle) + r'\b'
        return bool(re.search(pattern, haystack))

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
            must_match_list = [m.strip().lower() for m in must_match_raw.split(",") if m.strip()]
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


# Module-level singleton for convenience
_matcher = OptionMatcher()


def match_option(user_input: str, options: list[dict]) -> tuple[dict | None, list[dict]]:
    """Module-level wrapper for single option matching."""
    return _matcher.match_single(user_input, options)


def match_multiple_options(user_input: str, options: list[dict]) -> list[dict]:
    """Module-level wrapper for multiple option matching."""
    return _matcher.match_multiple(user_input, options)
