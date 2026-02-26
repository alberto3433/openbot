"""
Boolean Input Parser.

Parses user responses to yes/no boolean questions using a chain of strategies:
1. False aliases (e.g., "not toasted") - checked first since they contain true patterns
2. Negation patterns (e.g., "not X", "don't want it X") - before true aliases
   since "I don't want it scooped" contains "scooped" which is a true alias
3. True aliases (e.g., "toasted", "toast")
4. Yes/No patterns from database
5. Attribute name implicit yes

This follows a chain-of-responsibility pattern where each strategy is tried
in order until one succeeds.
"""

import re
from dataclasses import dataclass
from typing import Any

from orderbot.cache import menu_cache
from ...utils.text import normalize_text


@dataclass
class BooleanParseResult:
    """Result of parsing a boolean input."""

    value: bool | None
    """The parsed boolean value, or None if parsing failed."""

    matched_by: str | None = None
    """Which strategy matched (for debugging)."""


class BooleanParser:
    """
    Parses user input for boolean (yes/no) attribute questions.

    Uses a chain of strategies to determine if the user responded
    affirmatively or negatively.
    """

    def parse(
        self,
        user_input: str,
        attr: dict[str, Any],
    ) -> BooleanParseResult:
        """
        Parse user input to determine boolean value.

        Args:
            user_input: The user's response text
            attr: The attribute configuration dict containing:
                - display_name: Human-readable attribute name
                - options: List of option dicts with slugs and aliases

        Returns:
            BooleanParseResult with the parsed value (or None if unparseable)
        """
        user_lower = normalize_text(user_input)

        # Build alias lists from options
        true_aliases, false_aliases = self._extract_aliases(attr)
        attr_name = attr.get("display_name", "").lower()

        # Strategy 1: Check false aliases first (since "not toasted" contains "toasted")
        result = self._check_false_aliases(user_lower, false_aliases)
        if result.value is not None:
            return result

        # Strategy 2: Check negation patterns before true aliases
        # (since "I don't want it scooped" contains "scooped" which is a true alias)
        result = self._check_negation_pattern(user_lower, attr_name)
        if result.value is not None:
            return result

        # Strategy 3: Check true aliases
        result = self._check_true_aliases(user_lower, true_aliases)
        if result.value is not None:
            return result

        # Strategy 4: Check yes/no patterns with first-occurrence priority
        result = self._check_yes_no_patterns(user_lower, attr_name)
        if result.value is not None:
            return result

        # No match found
        return BooleanParseResult(value=None)

    def _extract_aliases(self, attr: dict[str, Any]) -> tuple[list[str], list[str]]:
        """Extract true and false aliases from attribute options.

        Args:
            attr: Attribute configuration dict

        Returns:
            Tuple of (true_aliases, false_aliases) lists
        """
        true_aliases: list[str] = []
        false_aliases: list[str] = []

        options = attr.get("options", [])
        for opt in options:
            opt_aliases = opt.get("aliases") or []
            if isinstance(opt_aliases, str):
                opt_aliases = [normalize_text(a) for a in opt_aliases.split(",")]
            else:
                opt_aliases = [a.lower() for a in opt_aliases]

            opt_slug = opt.get("slug", "")
            if opt_slug == "true" or opt_slug.endswith("_option_true"):
                true_aliases = opt_aliases
            elif opt_slug == "false" or opt_slug.endswith("_option_false"):
                false_aliases = opt_aliases

        return true_aliases, false_aliases

    def _check_false_aliases(
        self,
        user_lower: str,
        false_aliases: list[str]
    ) -> BooleanParseResult:
        """Check if input matches any false aliases.

        Args:
            user_lower: Lowercase user input
            false_aliases: List of aliases that mean "false"

        Returns:
            BooleanParseResult with value=False if matched, None otherwise
        """
        for alias in false_aliases:
            if alias in user_lower:
                return BooleanParseResult(value=False, matched_by="false_alias")
        return BooleanParseResult(value=None)

    def _check_true_aliases(
        self,
        user_lower: str,
        true_aliases: list[str]
    ) -> BooleanParseResult:
        """Check if input matches any true aliases.

        Args:
            user_lower: Lowercase user input
            true_aliases: List of aliases that mean "true"

        Returns:
            BooleanParseResult with value=True if matched, None otherwise
        """
        for alias in true_aliases:
            if alias in user_lower:
                return BooleanParseResult(value=True, matched_by="true_alias")
        return BooleanParseResult(value=None)

    def _check_negation_pattern(
        self,
        user_lower: str,
        attr_name: str
    ) -> BooleanParseResult:
        """Check for negation patterns like "not X" or "unX".

        Args:
            user_lower: Lowercase user input
            attr_name: The attribute name to check for

        Returns:
            BooleanParseResult with value=False if negation found, None otherwise
        """
        if not attr_name:
            return BooleanParseResult(value=None)

        negation_pattern = (
            rf"\bnot\s+{re.escape(attr_name)}\b"
            rf"|un{re.escape(attr_name)}\b"
            rf"|don'?t\s+(?:want|need|like)\s+(?:it\s+|that\s+)?{re.escape(attr_name)}\b"
        )
        if re.search(negation_pattern, user_lower):
            return BooleanParseResult(value=False, matched_by="negation_pattern")

        return BooleanParseResult(value=None)

    def _check_yes_no_patterns(
        self,
        user_lower: str,
        attr_name: str
    ) -> BooleanParseResult:
        """Check for yes/no patterns from database using first-occurrence priority.

        Args:
            user_lower: Lowercase user input
            attr_name: The attribute name (treated as implicit "yes")

        Returns:
            BooleanParseResult based on which pattern appears first
        """
        yes_patterns = menu_cache.get_response_patterns("affirmative")
        no_patterns = menu_cache.get_response_patterns("negative")

        # Find first occurrence of each pattern type
        first_yes_pos = float('inf')
        first_no_pos = float('inf')

        for pattern in no_patterns:
            pos = user_lower.find(pattern)
            if pos != -1 and pos < first_no_pos:
                first_no_pos = pos

        for pattern in yes_patterns:
            pos = user_lower.find(pattern)
            if pos != -1 and pos < first_yes_pos:
                first_yes_pos = pos

        # Also check for attribute name as implicit yes
        if attr_name:
            attr_pos = user_lower.find(attr_name)
            if attr_pos != -1 and attr_pos < first_yes_pos:
                first_yes_pos = attr_pos

        # First occurrence wins
        if first_no_pos < first_yes_pos:
            return BooleanParseResult(value=False, matched_by="no_pattern")
        elif first_yes_pos < first_no_pos:
            return BooleanParseResult(value=True, matched_by="yes_pattern")

        return BooleanParseResult(value=None)
