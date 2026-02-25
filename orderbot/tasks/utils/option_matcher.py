"""
Unified option matching with multi-phase algorithm.

Provides multi-phase matching for single-select and multi-select attributes.
Also supports ordinal matching for numbered list disambiguation.

Composed from mixins:
- MatchPhasesMixin: Multi-phase matching (raw exact, normalized exact, partial)
- NumberedListMatchMixin: Numbered list and ordinal matching
- OptionMatchStaticMixin: Static utility methods (normalize, price, filter)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from orderbot.cache import menu_cache
from .input_normalizer import InputNormalizer
from .option_match_phases import MatchPhasesMixin
from .option_match_numbered import NumberedListMatchMixin
from .option_match_static import OptionMatchStaticMixin
from .text import normalize_text

logger = logging.getLogger(__name__)


@dataclass
class MultiMatchResult:
    """Result of matching multiple options with unmatched token tracking."""

    matched: list[dict] = field(default_factory=list)
    """Options that matched."""

    unmatched: list[str] = field(default_factory=list)
    """Tokens that didn't match anything (excluding stopwords)."""


class OptionMatcher(MatchPhasesMixin, NumberedListMatchMixin, OptionMatchStaticMixin):
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
        user_raw_lower = normalize_text(user_input)

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
        user_raw_lower = normalize_text(user_input)
        matched: list[dict] = []
        matched_slugs: set[str] = set()

        # Get all input variants (raw, normalized, tokenized)
        all_inputs = self.normalizer.get_all_input_variants(user_input)
        raw_tokens = [normalize_text(t) for t in self.normalizer.tokenize_multi_input(user_input)]
        normalized_tokens = [self.normalizer.normalize_for_matching(t) for t in raw_tokens]

        # Strip leading qualifier patterns from tokens for matching
        # e.g., "lot of milk" → also try "milk", "extra mayo" → also try "mayo"
        try:
            qualifier_patterns = menu_cache.get_qualifier_patterns()
        except (KeyError, ValueError, TypeError, AttributeError):
            qualifier_patterns = []

        qualifier_stripped: list[str] = []
        for token in raw_tokens:
            for pattern in qualifier_patterns:
                prefix = pattern + " "
                if token.startswith(prefix) and len(token) > len(prefix):
                    qualifier_stripped.append(token[len(prefix):])
                    break  # Only strip one (longest-first already)

        if qualifier_stripped:
            raw_tokens = raw_tokens + qualifier_stripped
            normalized_tokens = normalized_tokens + [
                self.normalizer.normalize_for_matching(t) for t in qualifier_stripped
            ]
            all_inputs = all_inputs + qualifier_stripped + [
                self.normalizer.normalize_for_matching(t) for t in qualifier_stripped
            ]

        for opt in options:
            if not self._passes_must_match(user_input, opt):
                logger.debug(
                    "MULTI_SELECT SKIP: '%s' filtered by must_match=%s for option '%s'",
                    user_input, opt.get("must_match"), opt.get("display_name")
                )
                continue

            # Use the extracted helper method for matching logic
            if self._option_matches_input(
                opt, user_raw_lower, user_lower, raw_tokens, normalized_tokens, all_inputs
            ):
                # Add if not already present
                if opt["slug"] not in matched_slugs:
                    matched_slugs.add(opt["slug"])
                    matched.append(opt)

        # Exact-match priority: if one option exactly matches the full input, prefer it
        # over options that only matched via partial word overlap.
        # e.g., "strawberry cream cheese" exactly matches "Strawberry Cream Cheese"
        # but only word-matches "Plain Cream Cheese" via "cream"/"cheese".
        # Also try with leading article stripped (e.g., "the strawberry cream cheese").
        if len(matched) > 1:
            _article_re = re.compile(r'^(?:the|a|an)\s+', re.IGNORECASE)
            raw_no_article = _article_re.sub('', user_raw_lower)
            norm_no_article = _article_re.sub('', user_lower)
            exact = [
                opt for opt in matched
                if opt.get("display_name", "").lower() in (user_raw_lower, raw_no_article)
                or opt["slug"].replace("_", " ") in (user_raw_lower, raw_no_article)
                or self.normalizer.normalize_for_matching(
                    opt.get("display_name", "")
                ) in (user_lower, norm_no_article)
            ]
            if len(exact) == 1:
                matched = exact

        # Direction 1 priority: when there's a single compound token (no explicit
        # separators like "and"/","), individual words are extracted for matching.
        # If some options matched because their display name appears as a phrase
        # in the input ("blueberry cream cheese" found in "blueberry cream cheese
        # on the side") and others matched only via individual word tokens ("cream"
        # found in "plain cream cheese"), prefer the phrase-level matches.
        # Only apply when there's a single token — with explicit separators,
        # all tokens are intentional (e.g., "oat milk and 2 syrups").
        if len(matched) > 1 and len(raw_tokens) == 1:
            strong = [
                opt for opt in matched
                if self._is_whole_word_match(
                    opt["display_name"].lower(), user_raw_lower
                )
                or self._is_whole_word_match(
                    opt["slug"].replace("_", " "), user_raw_lower
                )
            ]
            if strong and len(strong) < len(matched):
                matched = strong

        # Deduplicate within same category: if specific must_match options matched
        # alongside generic (no must_match) options, prefer the specific ones.
        # e.g., "oat milk" matches oat_milk (must_match=["oat milk"]) AND whole_milk
        # (no must_match). Since oat_milk has a specific must_match for this input,
        # whole_milk should be dropped.
        if len(matched) > 1:
            matched = self._prefer_specific_must_match(user_input, matched)

        return matched

    def _prefer_specific_must_match(
        self, user_input: str, matched: list[dict]
    ) -> list[dict]:
        """Remove generic matches when a specific must_match winner exists in the same category.

        Groups matched options by ingredient_category. Within each group, if some options
        have a must_match that passes for the input and others have no must_match (generic),
        keep only the specific must_match winners.

        Options without a category or in categories with no must_match competition
        are always kept.
        """
        from collections import defaultdict
        by_category: dict[str | None, list[dict]] = defaultdict(list)
        for opt in matched:
            cat = opt.get("ingredient_category") or opt.get("category")
            by_category[cat].append(opt)

        result = []
        for cat, opts in by_category.items():
            if cat is None or len(opts) <= 1:
                result.extend(opts)
                continue

            # Split into specific (has must_match that passes) and generic (no must_match)
            specific = []
            generic = []
            for opt in opts:
                mm = opt.get("must_match")
                if mm and self._passes_must_match(user_input, opt):
                    specific.append(opt)
                elif not mm:
                    generic.append(opt)
                else:
                    # Has must_match but didn't pass - shouldn't be here, keep it
                    result.append(opt)

            if specific and generic:
                # Specific winners found - drop generic matches in this category
                logger.debug(
                    "MUST_MATCH DEDUP: keeping specific %s, dropping generic %s for input '%s'",
                    [o["slug"] for o in specific], [o["slug"] for o in generic], user_input
                )
                result.extend(specific)
            else:
                # No competition - keep all
                result.extend(specific)
                result.extend(generic)

        return result

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
        # Includes action verbs (add, put) users say when specifying modifiers
        stopwords = {"and", "with", "some", "a", "the", "please", "also", "too", "extra", "add", "put"}

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
            token_lower = normalize_text(token)

            # Skip stopwords
            if token_lower in stopwords:
                continue

            # Skip if empty or too short
            if len(token_lower) < 2:
                continue

            # Strip leading quantity from token for matching (e.g., "2 milks" -> "milks")
            _, token_without_qty = self.normalizer.extract_leading_quantity(token)
            token_without_qty_lower = normalize_text(token_without_qty) if token_without_qty else token_lower

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
                    if token_consumed:
                        break

            if not token_consumed:
                # Token wasn't directly consumed - check if it has multiple words
                # where some matched but others didn't (e.g., "milk sugar" where
                # "sugar" matched "Domino Sugar" but "milk" didn't match anything)
                words = token_without_qty_lower.split()
                if len(words) > 1:
                    # Check each word individually
                    for word in words:
                        if len(word) < 2 or word in stopwords:
                            continue
                        word_singular = self.normalizer.singularize(word)
                        word_consumed = (
                            word in matched_identifiers or
                            word_singular in matched_identifiers
                        )
                        if not word_consumed:
                            for identifier in matched_identifiers:
                                if (self._is_whole_word_match(word, identifier) or
                                        self._is_whole_word_match(identifier, word)):
                                    word_consumed = True
                                    break
                                if word_singular and (
                                        self._is_whole_word_match(word_singular, identifier) or
                                        self._is_whole_word_match(identifier, word_singular)):
                                    word_consumed = True
                                    break
                        if not word_consumed:
                            unmatched.append(word)
                    token_consumed = True  # Processed at word level
                else:
                    # Single word token - report as unmatched
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
        user_raw_lower = normalize_text(user_input)

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
            # No "input in option" matches found - try match_multiple() which also
            # checks if option names appear IN user input (handles "salt pepper" → ["salt", "pepper"])
            matched = self.match_multiple(user_input, options)
            if matched and len(matched) > 1:
                # Verify at least one match is "strong" — the option's display name
                # or slug appears as a phrase in the user input (Direction 1).
                # If ALL matches are "weak" (only matched because a user sub-word
                # appears in the option name via Direction 2), the sub-word is too
                # generic. E.g., "cheese" extracted from "melted cheese" matching
                # all cream cheese options. Return empty to let other attributes or
                # attribute-name matching handle the input.
                has_strong = any(
                    self._is_whole_word_match(
                        opt["display_name"].lower(), user_raw_lower
                    )
                    or self._is_whole_word_match(
                        opt["slug"].replace("_", " "), user_raw_lower
                    )
                    for opt in matched
                )
                if not has_strong:
                    return ([], [])
                return (matched, [])
            if matched:
                return (matched, [])
            return ([], [])
        elif len(partial_matches) == 1:
            # Single partial match - use it
            return (partial_matches, [])
        else:
            # Multiple partial matches from single term - need disambiguation
            return ([], partial_matches)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _option_matches_input(
        self,
        opt: dict,
        user_raw_lower: str,
        user_lower: str,
        raw_tokens: list[str],
        normalized_tokens: list[str],
        all_inputs: list[str],
    ) -> bool:
        """Check if a single option matches any variant of the user input.

        This is the core matching logic used by match_multiple(). It checks
        multiple matching strategies in order of specificity:

        1. Exact raw match (display_name or slug matches raw input)
        2. Exact normalized match
        3. Option name/alias appears as whole word in input
        4. User token appears as whole word in option name/alias

        Args:
            opt: Option dict with display_name, slug, and optional aliases
            user_raw_lower: Raw user input, lowercased
            user_lower: Normalized user input (plurals removed, etc.)
            raw_tokens: List of raw tokens from input (split on "and", ",", etc.)
            normalized_tokens: Normalized version of raw_tokens
            all_inputs: All input variants (raw, normalized, tokenized)

        Returns:
            True if the option matches by any strategy, False otherwise
        """
        display_lower = opt["display_name"].lower()
        slug_readable = opt["slug"].replace("_", " ")
        display_normalized = self.normalizer.normalize_for_matching(display_lower)
        slug_normalized = self.normalizer.normalize_for_matching(slug_readable)

        # === Phase 0: Exact match with raw input ===
        if display_lower == user_raw_lower or slug_readable == user_raw_lower:
            return True
        if display_lower in raw_tokens or slug_readable in raw_tokens:
            return True

        # === Phase 1: Exact match with normalized input ===
        if display_normalized == user_lower or slug_normalized == user_lower:
            return True
        if display_normalized in normalized_tokens or slug_normalized in normalized_tokens:
            return True

        # === Direction 1: Option name/alias appears in user input ===
        if self._is_whole_word_match(display_lower, user_raw_lower):
            return True
        if self._is_whole_word_match(slug_readable, user_raw_lower):
            return True

        # Check aliases in user input
        for alias in self._get_aliases(opt):
            alias_lower = alias.lower()
            if len(alias_lower) >= 2 and self._is_whole_word_match(alias_lower, user_raw_lower):
                return True

        # === Direction 2: User token appears in option name ===
        for token in all_inputs:
            if not token or len(token) < 2:
                continue
            if self._is_whole_word_match(token, display_lower):
                return True
            if self._is_whole_word_match(token, slug_readable):
                return True
            for alias in self._get_aliases(opt):
                alias_lower = alias.lower()
                if len(alias_lower) >= 2 and self._is_whole_word_match(token, alias_lower):
                    return True

        return False
