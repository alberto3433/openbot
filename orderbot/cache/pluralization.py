"""
Pluralization utilities for text processing.

This module provides singularize/pluralize functions using the inflect library,
plus variant-generation helpers used across the codebase for matching user input
in both singular and plural forms.

These are general-purpose text utilities, not cache infrastructure.
"""

import logging

import inflect

from .text_utils import normalize_text

logger = logging.getLogger(__name__)

# Shared inflect engine instance (thread-safe for reading)
_inflect_engine = inflect.engine()


def singularize(word: str) -> str:
    """Convert plural to singular form using the inflect library.

    Uses the well-tested inflect library to handle English pluralization rules,
    including irregular plurals and edge cases.

    Examples:
        >>> singularize("pastries")
        'pastry'
        >>> singularize("cookies")
        'cookie'
        >>> singularize("boxes")
        'box'
        >>> singularize("drinks")
        'drink'
        >>> singularize("glass")
        'glass'
        >>> singularize("tomatoes")
        'tomato'
        >>> singularize("children")
        'child'
    """
    word = normalize_text(word)
    if not word:
        return word

    # Words ending in 'ss' are typically already singular (glass, boss, miss)
    # inflect incorrectly tries to singularize these
    if word.endswith("ss"):
        return word

    # inflect.singular_noun returns False if the word is already singular
    try:
        result = _inflect_engine.singular_noun(word)
        return result if result else word
    except (TypeError, ValueError):
        # inflect is fragile with unusual inputs (prepositional phrases, etc.)
        return word


def contains_word_or_singular(word: str, word_set: set | frozenset) -> bool:
    """Check if a word or its singular form exists in a set.

    Useful for matching user input where plurals like "coffees" should match
    a set containing "coffee".

    Args:
        word: The word to check (already lowercased).
        word_set: Set of words to check against.

    Returns:
        True if word or singularize(word) is in the set.
    """
    return word in word_set or singularize(word) in word_set


def pluralize(word: str) -> str:
    """Convert singular to plural form using the inflect library.

    Uses the well-tested inflect library to handle English pluralization rules,
    including irregular plurals and edge cases.

    Examples:
        >>> pluralize("bagel")
        'bagels'
        >>> pluralize("sandwich")
        'sandwiches'
        >>> pluralize("pastry")
        'pastries'
        >>> pluralize("child")
        'children'
        >>> pluralize("glass")
        'glasses'
    """
    word = normalize_text(word)
    if not word:
        return word

    # Skip if already plural (e.g., "snacks", "drinks") to avoid double-pluralization
    try:
        if _inflect_engine.singular_noun(word):
            return word
    except (TypeError, ValueError):
        pass

    # Use inflect to get the plural form
    try:
        result = _inflect_engine.plural_noun(word)
        return result if result else word + 's'
    except (TypeError, ValueError):
        return word + 's'


def get_singular_plural_variants(word: str) -> list[str]:
    """Get both singular and plural variants of a word for matching.

    Returns a list containing the original word and its singular/plural form.
    Useful for matching user input that might be in either form.

    Examples:
        >>> get_singular_plural_variants("bagels")
        ['bagels', 'bagel']
        >>> get_singular_plural_variants("cookie")
        ['cookie', 'cookies']
        >>> get_singular_plural_variants("glass")
        ['glass', 'glasses']
    """
    word = normalize_text(word)
    if not word:
        return [word]

    variants = [word]

    # Try to get singular form
    singular = singularize(word)
    if singular != word and singular not in variants:
        variants.append(singular)
        # If we found a singular form, pluralize that instead of the original
        # This avoids "bagels" -> "bagelss"
        plural = pluralize(singular)
        if plural != word and plural not in variants:
            variants.append(plural)
    else:
        # Word is likely already singular, try to pluralize it
        plural = pluralize(word)
        if plural != word and plural not in variants:
            variants.append(plural)

    return variants
