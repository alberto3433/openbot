"""
Unified option matching with multi-phase algorithm.

Provides multi-phase matching for single-select and multi-select attributes.
Also supports ordinal matching for numbered list disambiguation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .input_normalizer import InputNormalizer
from ..normalization import strip_filler_words

logger = logging.getLogger(__name__)

# Ordinal patterns for numbered list selection
# Format: (pattern, 0-based index)
ORDINAL_PATTERNS: list[tuple[str, int]] = [
    ("first", 0), ("1", 0), ("one", 0),
    ("second", 1), ("2", 1), ("two", 1),
    ("third", 2), ("3", 2), ("three", 2),
    ("fourth", 3), ("4", 3), ("four", 3),
    ("fifth", 4), ("5", 4), ("five", 4),
    ("sixth", 5), ("6", 5), ("six", 5),
]


@dataclass
class MultiMatchResult:
    """Result of matching multiple options with unmatched token tracking."""

    matched: list[dict] = field(default_factory=list)
    """Options that matched."""

    unmatched: list[str] = field(default_factory=list)
    """Tokens that didn't match anything (excluding stopwords)."""


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
        self, user_input: str, options: list[dict], *, exact_only: bool = False
    ) -> tuple[dict | None, list[dict]]:
        """
        Find first matching option with smart partial matching.

        Args:
            user_input: The user's input text
            options: List of option dicts to match against
            exact_only: If True, skip partial matching phases (2 and 3).
                Use this when you only want exact matches, e.g., for checking
                if user asked for an unavailable option by name.

        Returns:
            (matched_option, partial_matches) tuple:
            - (option, []) = exact or unique partial match found
            - (None, [opt1, opt2, ...]) = multiple partial matches, need disambiguation
            - (None, []) = no matches at all

        Matching priority:
        1. Exact match on display_name, slug, or alias
        2. Partial match: user input is contained in option name (skipped if exact_only)
        3. Partial match: option name is contained in user input (skipped if exact_only)
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

        # Skip partial matching if exact_only is True
        if exact_only:
            return (None, [])

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
        if user_input.startswith('-') or user_input.startswith('−'):
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

    def match_multiple_with_unmatched(
        self, user_input: str, options: list[dict]
    ) -> MultiMatchResult:
        """
        Match ALL options in user input and track unmatched tokens.

        Like match_multiple(), but also returns tokens that didn't match anything.
        Useful for reporting "Sorry, we don't have X" for unrecognized modifiers.

        Args:
            user_input: User input that may contain multiple modifiers
            options: List of available options to match against

        Returns:
            MultiMatchResult with:
            - matched: List of options that matched
            - unmatched: List of tokens that didn't match (excluding stopwords)

        Examples:
            >>> result = matcher.match_multiple_with_unmatched("milk and honey", options)
            >>> result.matched  # [whole_milk_option]
            >>> result.unmatched  # ["honey"]
        """
        # Get matched options using existing method
        matched = self.match_multiple(user_input, options)

        # Tokenize input to track which tokens were consumed
        tokens = self.normalizer.tokenize_multi_input(user_input)

        # Stopwords to ignore when reporting unmatched
        stopwords = {"and", "with", "some", "a", "the", "please", "also", "too", "extra"}

        # Build set of matched identifiers for checking
        matched_identifiers: set[str] = set()
        for opt in matched:
            matched_identifiers.add(opt["display_name"].lower())
            matched_identifiers.add(opt["slug"].lower())
            matched_identifiers.add(opt["slug"].replace("_", " ").lower())
            for alias in self._get_aliases(opt):
                matched_identifiers.add(alias.lower())

        # Find unmatched tokens
        unmatched: list[str] = []
        for token in tokens:
            token_lower = token.lower().strip()

            # Skip stopwords
            if token_lower in stopwords:
                continue

            # Skip if empty or too short
            if len(token_lower) < 2:
                continue

            # Strip leading quantity from token for matching (e.g., "2 milks" -> "milks")
            _, token_without_qty = self.normalizer.extract_leading_quantity(token)
            token_without_qty_lower = token_without_qty.lower().strip() if token_without_qty else token_lower

            # Also try singularized form
            token_singular = self.normalizer.singularize(token_without_qty_lower)

            # Check if this token was consumed by any match
            token_consumed = False

            # Direct match check (try original, without quantity, and singular forms)
            check_values = {token_lower, token_without_qty_lower, token_singular}
            for check_val in check_values:
                if check_val in matched_identifiers:
                    token_consumed = True
                    break

            if not token_consumed:
                # Check if token appears in any matched identifier (partial match)
                for identifier in matched_identifiers:
                    for check_val in check_values:
                        if self._is_whole_word_match(check_val, identifier):
                            token_consumed = True
                            break
                        if self._is_whole_word_match(identifier, check_val):
                            token_consumed = True
                            break
                    if token_consumed:
                        break

            if not token_consumed:
                # Report the token without quantity
                if token_without_qty and token_without_qty_lower not in stopwords:
                    unmatched.append(token_without_qty)
                elif token_lower not in stopwords:
                    unmatched.append(token)

        return MultiMatchResult(matched=matched, unmatched=unmatched)

    def match_multiple_with_disambiguation(
        self, user_input: str, options: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """
        Match options with disambiguation detection for multi-select attributes.

        This method distinguishes between:
        1. User explicitly listing multiple items: "bacon and turkey bacon" → add both
        2. User saying one ambiguous term: "bacon" → ask disambiguation

        Returns:
            (matched_options, disambiguation_candidates) tuple:
            - ([opt1, opt2], []) = multiple distinct matches from explicit input, add all
            - ([opt1], []) = single match, add it
            - ([], [opt1, opt2, opt3]) = single ambiguous term matches multiple, need disambiguation
        """
        user_raw_lower = user_input.lower().strip()

        # Check if input has explicit separators (user listing multiple items)
        separators = [" and ", ", ", " & ", " with "]
        has_separator = any(sep in user_raw_lower for sep in separators)

        if has_separator:
            # User explicitly listed multiple items - match all without disambiguation
            matched = self.match_multiple(user_input, options)
            return (matched, [])

        # Single term - check for exact match first
        exact_match = self._phase_raw_exact_match(user_raw_lower, options, user_input)
        if exact_match:
            return ([exact_match], [])

        # Check normalized exact match
        user_normalized = self.normalizer.normalize_for_matching(user_input)
        exact_match = self._phase_normalized_exact_match(user_normalized, options, user_input)
        if exact_match:
            return ([exact_match], [])

        # No exact match - check for partial matches
        partial_matches = self._phase_partial_input_in_option(user_normalized, options, user_input)

        if len(partial_matches) == 0:
            # No matches at all
            return ([], [])
        elif len(partial_matches) == 1:
            # Single partial match - use it
            return (partial_matches, [])
        else:
            # Multiple partial matches from single term - need disambiguation
            return ([], partial_matches)

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

    # =========================================================================
    # Static Methods for Simple Value Matching
    # =========================================================================

    @staticmethod
    def normalize_option(option: dict) -> tuple[str, str]:
        """Normalize an option dict for matching against user input.

        Extracts and normalizes both slug and display_name from an option dict
        for consistent comparison during price lookups.

        Args:
            option: Option dict with optional "slug" and "display_name" keys

        Returns:
            Tuple of (normalized_slug, normalized_display_name) where both have
            dashes and spaces converted to underscores, lowercased.

        Examples:
            >>> OptionMatcher.normalize_option({"slug": "oat-milk", "display_name": "Oat Milk"})
            ("oat_milk", "oat_milk")
        """
        # Import here to avoid circular imports
        from ..normalization import normalize_to_slug
        opt_slug = normalize_to_slug(option.get("slug") or "")
        opt_name = normalize_to_slug(option.get("display_name") or "")
        return opt_slug, opt_name

    @staticmethod
    def matches_value(
        option: dict,
        normalized_value: str,
        raw_value_lower: str,
        *,
        exact_only: bool = False,
    ) -> bool:
        """Check if an option matches by slug, display_name, or raw value.

        Simple matching for price lookups - uses multiple strategies:
        - Normalized slug comparison
        - Normalized display_name comparison
        - Raw lowercase value comparison
        - Prefix matching (value is a prefix of slug, e.g., "vanilla" matches "vanilla_syrup")

        Args:
            option: Option dict with "slug" and/or "display_name" keys
            normalized_value: Value normalized via normalize_to_slug()
            raw_value_lower: Original value lowercased
            exact_only: If True, only check exact matches (skip prefix matching)

        Returns:
            True if the option matches by any strategy, False otherwise
        """
        opt_slug, opt_name = OptionMatcher.normalize_option(option)
        opt_display_lower = (option.get("display_name") or "").lower()

        # Exact matches (preferred)
        if (opt_slug == normalized_value or
                opt_name == normalized_value or
                opt_slug == raw_value_lower or
                opt_display_lower == raw_value_lower):
            return True

        # Skip prefix matching if exact_only is True
        if exact_only:
            return False

        # Prefix matching: value must be at the START of the slug
        # This allows "vanilla" to match "vanilla_syrup" but prevents
        # "plain_bagel" from matching "gf_plain_bagel"
        if opt_slug.startswith(raw_value_lower + "_") or opt_slug.startswith(normalized_value + "_"):
            return True

        return False
