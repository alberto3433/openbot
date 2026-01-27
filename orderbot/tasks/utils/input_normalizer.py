"""
Unified input normalization utilities for option matching.

Consolidates duplicate implementations from:
- menu_item_config_handler._extract_quantity_from_input()
- taking_items_handler._extract_quantity_from_input()

Note: normalize_for_option_match() is imported from normalization.py
to avoid duplication.
"""

from __future__ import annotations

import re

from orderbot.menu_data_cache import singularize
from orderbot.tasks.normalization import normalize_for_option_match as _normalize_for_option_match
from orderbot.tasks.parsers.quantity_utils import extract_leading_quantity


class InputNormalizer:
    """
    Unified text normalization for option matching.

    Handles common patterns users type when ordering:
    - Leading quantities: "2 scrambled eggs" → (2, "scrambled eggs")
    - Plural forms: "scrambled eggs" → "scrambled egg"
    - Multi-item separators: "milk and sugar" → ["milk", "sugar"]
    """

    # Separators for tokenizing multi-item input
    SEPARATORS = [
        r'\s+and\s+',      # " and "
        r'\s*,\s*',        # ", " or ","
        r'\s+&\s+',        # " & "
        r'\s+with\s+',     # " with "
        r'\s+plus\s+',     # " plus "
    ]

    def extract_leading_quantity(self, text: str) -> tuple[int, str]:
        """
        Extract leading quantity from text and return remaining text.

        Args:
            text: Input text like "2 bagels", "three lattes", "a coffee"

        Returns:
            (quantity, remaining_text) - quantity defaults to 1 if not found.

        Examples:
            >>> normalizer = InputNormalizer()
            >>> normalizer.extract_leading_quantity("2 bagels")
            (2, "bagels")
            >>> normalizer.extract_leading_quantity("three lattes")
            (3, "lattes")
            >>> normalizer.extract_leading_quantity("coffee")
            (1, "coffee")
        """
        quantity, remaining = extract_leading_quantity(text)
        return (quantity or 1, remaining)

    def normalize_for_matching(self, text: str) -> str:
        """
        Normalize text for option matching.

        Handles:
        - Lowercasing
        - Strip leading quantities: "2 scrambled eggs" → "scrambled eggs"
        - Singular forms: "eggs" → "egg"

        Args:
            text: Raw user input

        Returns:
            Normalized text suitable for option matching.
        """
        return _normalize_for_option_match(text)

    def singularize(self, text: str) -> str:
        """
        Convert plural to singular form.

        Args:
            text: Text to singularize (e.g., "bagels", "eggs")

        Returns:
            Singular form of the text.
        """
        return singularize(text)

    def tokenize_multi_input(self, user_input: str) -> list[str]:
        """
        Tokenize compound input into individual items.

        Args:
            user_input: Input that may contain multiple items

        Returns:
            List of individual tokens.

        Examples:
            >>> normalizer = InputNormalizer()
            >>> normalizer.tokenize_multi_input("milk and sugar")
            ["milk", "sugar"]
            >>> normalizer.tokenize_multi_input("bacon, cheese, tomato")
            ["bacon", "cheese", "tomato"]
            >>> normalizer.tokenize_multi_input("oat milk and vanilla syrup")
            ["oat milk", "vanilla syrup"]
        """
        pattern = '|'.join(self.SEPARATORS)
        tokens = re.split(pattern, user_input, flags=re.IGNORECASE)
        return [t.strip() for t in tokens if t.strip()]

    def get_all_input_variants(self, user_input: str) -> list[str]:
        """
        Get all variants of user input for comprehensive matching.

        Returns raw, normalized, and tokenized variants.

        Args:
            user_input: Raw user input

        Returns:
            List of unique input variants for matching.
        """
        user_raw_lower = user_input.lower().strip()
        user_normalized = self.normalize_for_matching(user_input)

        # Tokenize input for compound inputs like "milk and sugar"
        tokens = self.tokenize_multi_input(user_input)
        raw_tokens = [t.lower().strip() for t in tokens]
        normalized_tokens = [self.normalize_for_matching(t) for t in tokens]

        # Combine all variants
        all_inputs = [user_raw_lower, user_normalized] + raw_tokens + normalized_tokens

        # Remove duplicates while preserving order
        seen = set()
        return [x for x in all_inputs if x and x not in seen and not seen.add(x)]


# Module-level singleton for convenience
_normalizer = InputNormalizer()


def normalize_for_option_match(text: str) -> str:
    """Module-level wrapper for backward compatibility."""
    return _normalize_for_option_match(text)


def extract_quantity_from_input(user_input: str) -> tuple[int, str]:
    """Module-level wrapper for backward compatibility."""
    return _normalizer.extract_leading_quantity(user_input)


def tokenize_multi_input(user_input: str) -> list[str]:
    """Module-level wrapper for backward compatibility."""
    return _normalizer.tokenize_multi_input(user_input)
