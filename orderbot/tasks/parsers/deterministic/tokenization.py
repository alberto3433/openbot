"""
Tokenization Functions for Multi-Item Order Parsing.

This module contains functions for smart tokenization and classification
of user input to support multi-item order parsing.

Sub-modules (extracted during decomposition):
- item_indicator: Item indicator detection pipeline
- token_recombination: Token recombination into item groups
- multi_item_pipeline: Multi-item order pipeline entry point
"""

import logging

from orderbot.cache import menu_cache

from ..quantity_utils import (
    extract_leading_quantity as _extract_leading_quantity,
    strip_quantity_modifier_prefix,
)
from ...utils.text import normalize_text

from .item_indicator import (
    _has_item_indicator,
    _strip_ordering_prefix,
    _is_modifier_only,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Token Classification
# =============================================================================

def _classify_token(text: str) -> "Token":
    """Classify a token from split input.

    Args:
        text: Token text to classify

    Returns:
        Token with classification info
    """
    from orderbot.tasks.schemas.parser_responses import Token

    text = text.strip()
    original_text = text  # Preserve for Token.original
    text_lower = text.lower()

    # Strip ordering prefixes (e.g., "I'd like a") that may remain on the
    # first token after splitting on " and ".
    stripped = _strip_ordering_prefix(text_lower)
    if stripped != text_lower:
        text_lower = stripped
        text = stripped  # Update matching text too

    # Check for separator
    if text_lower in ("and", ","):
        return Token(original=original_text, token_type="separator")

    # Extract quantity
    quantity, remaining = _extract_leading_quantity(text)

    # If only quantity (e.g., just "a" or "2"), it's a quantity token
    if not remaining and quantity is not None:
        return Token(original=original_text, token_type="quantity", quantity=quantity)

    # Check if it has an item indicator
    has_item, item_type, resolved_name = _has_item_indicator(remaining if remaining else text)
    if has_item:
        return Token(
            original=original_text,
            token_type="item",
            quantity=quantity or 1,
            item_type=item_type,
            resolved_name=resolved_name,
        )

    # Check if it's modifier-only
    is_mod, modifiers = _is_modifier_only(remaining if remaining else text)
    if is_mod:
        return Token(
            original=original_text,
            token_type="modifier",
            resolved_name=", ".join(modifiers) if modifiers else None,
        )

    # Check if it's an attribute option
    attr_options = menu_cache.get_all_attribute_option_words()
    if text_lower in attr_options:
        return Token(
            original=original_text,
            token_type="attribute",
            attribute_slug=attr_options[text_lower],
        )

    # Unknown
    return Token(original=original_text, token_type="unknown")


# =============================================================================
# Smart Tokenization — Helpers
# =============================================================================


def _create_multi_item_split(
    compound_match: str, first_item_text: str, after_and: str,
    next_item_type: str, next_resolved: str,
) -> list["Token"]:
    """Create token list for compound phrase + second item split."""
    from orderbot.tasks.schemas.parser_responses import Token

    _, compound_item_type, compound_resolved = _has_item_indicator(compound_match)
    qty, _ = _extract_leading_quantity(first_item_text.lower())

    compound_token = Token(
        original=first_item_text,
        token_type="item",
        quantity=qty or 1,
        item_type=compound_item_type,
        resolved_name=compound_resolved,
    )

    # Recursively tokenize the remainder (second item + any more items)
    remainder_tokens = _smart_split_and_tokenize(after_and)
    if remainder_tokens:
        return [compound_token] + remainder_tokens

    # Remainder didn't split further - classify it directly
    qty2, _ = _extract_leading_quantity(after_and)
    return [compound_token, Token(
        original=after_and,
        token_type="item",
        quantity=qty2 or 1,
        item_type=next_item_type,
        resolved_name=next_resolved,
    )]


def _try_compound_split(
    text_lower: str, text_for_compound: str, compound_match: str,
) -> list["Token"] | None:
    """Try to split input around a compound phrase and a second item.

    Returns tokens if multi-item split succeeded, None if no second item found.
    """
    remainder = text_for_compound[len(compound_match):].strip()

    # First check if remainder starts with "and " (e.g., "and a latte")
    if remainder.startswith("and "):
        after_and = remainder[4:].strip()
        has_next_item, next_item_type, next_resolved = _has_item_indicator(after_and)
        if has_next_item:
            return _create_multi_item_split(
                compound_match, compound_match, after_and, next_item_type, next_resolved,
            )

    # Search for " and " anywhere in remainder (not just at start)
    and_idx = remainder.find(" and ")
    while and_idx != -1:
        after_and = remainder[and_idx + 5:].strip()
        has_next_item, next_item_type, next_resolved = _has_item_indicator(after_and)

        if has_next_item:
            first_item_text = compound_match + " " + remainder[:and_idx].strip()
            first_item_text = first_item_text.strip()
            return _create_multi_item_split(
                compound_match, first_item_text, after_and, next_item_type, next_resolved,
            )

        and_idx = remainder.find(" and ", and_idx + 5)

    return None


def _reattach_boolean_attributes(parts: list[str]) -> list[str]:
    """Reattach boolean attribute words split by 'and' back to their item.

    When splitting on " and " separates two boolean attrs of the same item type,
    reattach the leading boolean word from part[i+1] back to part[i].
    e.g., ["plain bagel toasted", "scooped plain cream cheese on the side"]
        -> ["plain bagel toasted and scooped", "plain cream cheese on the side"]
    """
    # Build mapping: boolean attr word -> set of item type slugs
    boolean_attr_to_types: dict[str, set[str]] = {}
    for item_type_slug in menu_cache.get_configurable_item_types():
        item_attrs = menu_cache.get_item_type_attributes(item_type_slug)
        if item_attrs:
            for attr_name, attr_info in item_attrs.items():
                if isinstance(attr_info, dict) and attr_info.get("input_type") == "boolean":
                    word = attr_name.lower()
                    boolean_attr_to_types.setdefault(word, set()).add(item_type_slug)
                    word_spaced = word.replace("_", " ")
                    if word_spaced != word:
                        boolean_attr_to_types.setdefault(word_spaced, set()).add(item_type_slug)

    if not boolean_attr_to_types:
        return parts

    parts = list(parts)  # Don't mutate caller's list
    i = 0
    while i < len(parts) - 1:
        left_words = parts[i].split()
        right_words = parts[i + 1].split()
        if left_words and right_words:
            last_left = left_words[-1].lower()
            first_right = right_words[0].lower()
            if (
                last_left in boolean_attr_to_types
                and first_right in boolean_attr_to_types
                and boolean_attr_to_types[last_left] & boolean_attr_to_types[first_right]
            ):
                remainder = " ".join(right_words[1:]).strip()
                if remainder:
                    has_item, _, _ = _has_item_indicator(remainder)
                    if has_item:
                        parts[i] = parts[i] + " and " + first_right
                        parts[i + 1] = remainder
                        logger.debug(
                            "Boolean reattach: moved '%s' back to part[%d]: %s | %s",
                            first_right, i, parts[i], parts[i + 1],
                        )
                        continue  # Re-check same index for triple booleans
        i += 1

    return parts


# =============================================================================
# Smart Tokenization
# =============================================================================


def _try_split_on_with_article(text_lower: str) -> list["Token"] | None:
    """Try to split on 'with [article] [item]' that introduces a new item.

    Handles patterns where two items are connected by "with" instead of "and":
      "onion bagel with cream cheese toasted with an earl gray tea"
      -> ["onion bagel with cream cheese toasted", "earl gray tea"]

    Two modes:
    1. Article mode: 'with' followed by a/an/the + recognized item.
    2. No-article mode: 'with' followed by a recognized menu item that is
       NOT a known modifier (e.g., "rb prime with side of sausage").

    The first part must also contain a recognized item.

    Returns list of tokens if split succeeded, None otherwise.
    """
    from orderbot.tasks.schemas.parser_responses import Token

    # Find all " with " positions
    positions: list[int] = []
    start = 0
    while True:
        pos = text_lower.find(" with ", start)
        if pos == -1:
            break
        positions.append(pos)
        start = pos + 6  # len(" with ")

    if len(positions) < 1:
        return None

    # For 2+ occurrences: only check from 2nd onward (1st is likely modifier)
    # For exactly 1 occurrence: check it (must have article + recognized item)
    positions_to_check = positions[1:] if len(positions) >= 2 else positions

    for pos in positions_to_check:
        after_with = text_lower[pos + 6:]  # skip " with "

        # Must start with an article
        article_len = 0
        for art in ("an ", "a ", "the "):
            if after_with.startswith(art):
                article_len = len(art)
                break

        if not article_len:
            # No article — still split if the after-with text is a recognized
            # menu item and NOT a known modifier.  Handles patterns like
            # "rb prime with side of sausage" where "side of sausage" is a
            # menu item without an article prefix.
            has_next_na, next_type_na, next_resolved_na = _has_item_indicator(after_with)
            if not has_next_na:
                continue

            # Check if after-with text IS or STARTS WITH a known modifier.
            # Also strip leading quantity modifiers ("extra", "double", etc.)
            # so that "extra cream cheese" → "cream cheese" is recognized.
            # Prefix check handles "cream cheese toasted" where only the
            # beginning is a modifier.
            stripped_na = strip_quantity_modifier_prefix(after_with)
            words_na = stripped_na.split()
            modifier_found = menu_cache.is_known_modifier(stripped_na)
            if not modifier_found:
                for i in range(len(words_na) - 1, 0, -1):
                    candidate = " ".join(words_na[:i])
                    if menu_cache.is_known_modifier(candidate):
                        modifier_found = True
                        break
            if modifier_found:
                logger.debug(
                    "Skipping 'with [item]' split - modifier detected: '%s'",
                    after_with[:40],
                )
                continue

            first_part = text_lower[:pos].strip()
            has_first_na, first_type_na, first_resolved_na = _has_item_indicator(first_part)
            if not has_first_na:
                continue

            qty1, _ = _extract_leading_quantity(first_part)
            qty2, _ = _extract_leading_quantity(after_with)

            logger.info(
                "Split on 'with [item]' (no article): '%s' + '%s'",
                first_part[:40], after_with[:40],
            )

            return [
                Token(
                    original=first_part,
                    token_type="item",
                    quantity=qty1 or 1,
                    item_type=first_type_na,
                    resolved_name=first_resolved_na,
                ),
                Token(
                    original=after_with,
                    token_type="item",
                    quantity=qty2 or 1,
                    item_type=next_type_na,
                    resolved_name=next_resolved_na,
                ),
            ]

        after_article = after_with[article_len:].strip()
        if not after_article:
            continue

        # Check if text after article contains a recognized item
        has_next_item, next_type, next_resolved = _has_item_indicator(after_article)
        if not has_next_item:
            continue

        # When there's only one "with", it almost always connects a modifier
        # to the preceding item. Only split if text is NOT a known modifier.
        if len(positions) == 1:
            words = after_article.split()
            is_modifier_context = False
            for i in range(len(words)):
                candidate = " ".join(words[i:])
                if menu_cache.is_known_modifier(candidate):
                    is_modifier_context = True
                    break
            if is_modifier_context:
                logger.debug(
                    "Skipping 'with [article]' split - modifier context: '%s'",
                    after_article[:40],
                )
                continue

        # Verify first part also has an item
        first_part = text_lower[:pos].strip()
        has_first, first_type, first_resolved = _has_item_indicator(first_part)
        if not has_first:
            continue

        # Valid split point found
        qty1, _ = _extract_leading_quantity(first_part)
        qty2, _ = _extract_leading_quantity(after_article)

        logger.info(
            "Split on 'with [article]': '%s' + '%s'",
            first_part[:40], after_article[:40],
        )

        return [
            Token(
                original=first_part,
                token_type="item",
                quantity=qty1 or 1,
                item_type=first_type,
                resolved_name=first_resolved,
            ),
            Token(
                original=after_article,
                token_type="item",
                quantity=qty2 or 1,
                item_type=next_type,
                resolved_name=next_resolved,
            ),
        ]

    return None


def _smart_split_and_tokenize(text: str) -> list["Token"]:
    """Split text on separators and classify each part.

    Args:
        text: Full input text

    Returns:
        List of classified tokens

    Examples:
        >>> _smart_split_and_tokenize("bacon egg and cheese and a coffee")
        [Token("bacon egg", item), Token("cheese", modifier), Token("a coffee", item)]
    """
    from orderbot.tasks.schemas.parser_responses import Token

    text_lower = normalize_text(text)

    # Strip ordering prefixes for compound phrase detection
    text_for_compound = _strip_ordering_prefix(text_lower)

    # First, try to match entire input as a single item
    has_item, item_type, resolved_name = _has_item_indicator(text_lower)

    # Check if this is a compound phrase that shouldn't be split
    is_compound = menu_cache.is_compound_phrase(text_for_compound)
    if not is_compound:
        compound_match = menu_cache.find_compound_phrase_in(text_for_compound)
        if compound_match:
            tokens = _try_compound_split(text_lower, text_for_compound, compound_match)
            if tokens:
                return tokens
            is_compound = True  # Found compound but no second item

    # Before returning as single item, check for "with [article] [item]" pattern
    # e.g., "onion bagel with cream cheese toasted with an earl gray tea"
    # The second "with" + article introduces a second item.
    # Only try this when there's no "and"/"," separator (otherwise normal split handles it).
    if has_item and " with " in text_lower and " and " not in text_lower and ", " not in text_lower:
        with_article_tokens = _try_split_on_with_article(text_lower)
        if with_article_tokens:
            return with_article_tokens

    if has_item and (is_compound or (" and " not in text_lower and ", " not in text_lower)):
        qty, _ = _extract_leading_quantity(text_lower)
        return [Token(
            original=text,
            token_type="item",
            quantity=qty or 1,
            item_type=item_type,
            resolved_name=resolved_name,
        )]

    # Protect compound phrases from being split on " and "
    text_to_split = text_lower
    placeholder = "\x00AND\x00"
    for phrase in sorted(menu_cache.get_compound_phrases(), key=len, reverse=True):
        if phrase in text_to_split:
            text_to_split = text_to_split.replace(phrase, phrase.replace(" and ", placeholder))

    # Split on " and " and ", "
    normalized = text_to_split.replace(", and ", ", ").replace(" and ", ", ")
    parts = [p.strip() for p in normalized.split(",") if p.strip()]

    # Restore protected " and "s
    parts = [p.replace(placeholder, " and ") for p in parts]

    # Reattach boolean attributes split by "and" back to their item
    if len(parts) >= 2:
        parts = _reattach_boolean_attributes(parts)

    if len(parts) < 2:
        return []

    # Classify each part
    return [_classify_token(part) for part in parts]


# =============================================================================
# Re-exports for backward compatibility
# =============================================================================

from .item_indicator import (  # noqa: E402, F401
    _strip_trailing_words,
    _strip_ordering_prefix,
    _try_menu_item_alias_match,
    _try_word_boundary_match,
    _collect_trigger_matches,
    _select_best_trigger_match,
    _has_item_indicator,
    _is_modifier_only,
)

from .token_recombination import (  # noqa: E402, F401
    _is_demotable_to_modifier,
    _flush_current_item,
    _recombine_tokens,
)

from .multi_item_pipeline import (  # noqa: E402, F401
    _parse_multi_item_order,
    _is_with_modifier_chain,
    _all_tokens_are_modifiers,
    _other_tokens_are_potential_modifiers,
    _derive_item_name_from_token,
    _build_items_from_tokens,
)
