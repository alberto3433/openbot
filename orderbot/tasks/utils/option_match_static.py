"""
Static utility methods extracted from OptionMatcher.

Provides OptionMatchStaticMixin with static methods for simple value matching,
price extraction, option filtering, and numeric option matching.
"""

from __future__ import annotations

from ..normalization import normalize_to_slug
from .text import normalize_text


class OptionMatchStaticMixin:
    """Mixin providing static utility methods for OptionMatcher."""

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
            >>> OptionMatchStaticMixin.normalize_option({"slug": "oat-milk", "display_name": "Oat Milk"})
            ("oat_milk", "oat_milk")
        """
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
        opt_slug, opt_name = OptionMatchStaticMixin.normalize_option(option)
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

    @staticmethod
    def get_option_price(option: dict) -> float:
        """Extract price from option dict.

        Consolidates the repeated pattern of checking both 'price' and 'price_modifier' keys.

        Args:
            option: Option dict with optional 'price' or 'price_modifier' keys

        Returns:
            Price as float, or 0.0 if not found
        """
        return option.get("price") or option.get("price_modifier") or 0.0

    @staticmethod
    def filter_available_options(options: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split options into available and unavailable.

        Args:
            options: List of option dicts with optional 'is_available' key

        Returns:
            Tuple of (available_options, unavailable_options)
        """
        available = [opt for opt in options if opt.get("is_available", True)]
        unavailable = [opt for opt in options if not opt.get("is_available", True)]
        return available, unavailable

    def match_numeric_option(
        self,
        user_input: str,
        options: list[dict],
    ) -> dict | None:
        """Match numeric input to options with numeric slugs.

        Handles options like shots: "1", "2", "3" or eggs: "2_eggs", "3_eggs".
        Supports numeric words ("double", "triple") via parse_numeric_input.

        Args:
            user_input: User's input text
            options: List of option dicts to match against

        Returns:
            Matched option dict if found, None otherwise
        """
        from ..parsers.quantity_utils import parse_numeric_input
        from ..response_utils import is_affirmative

        user_lower = normalize_text(user_input)

        # Check if any options have numeric slugs
        numeric_slugs = {opt["slug"] for opt in options if opt["slug"].isdigit()}
        if not numeric_slugs:
            return None

        # Parse the user input as a number
        parsed_num = parse_numeric_input(user_lower)

        # Default to 1 for affirmative responses when options are numeric
        if parsed_num is None and is_affirmative(user_input):
            parsed_num = 1

        if parsed_num is None:
            return None

        # Find matching option
        target_slug = str(parsed_num)
        for opt in options:
            if opt["slug"] == target_slug:
                return opt

        return None
