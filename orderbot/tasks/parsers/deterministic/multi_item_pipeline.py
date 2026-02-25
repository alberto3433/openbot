"""
Multi-Item Order Pipeline.

Entry point and helpers for parsing multi-item orders like
'The Lexington and an orange juice'.

Extracted from tokenization.py during decomposition refactoring.
"""

import re
import logging

from orderbot.cache import menu_cache

from ...schemas import OpenInputResponse
from ..quantity_utils import extract_leading_quantity as _extract_leading_quantity

from .item_parsing import (
    _parse_item_generic,
    _is_modifier_chain,
)
from .item_indicator import (
    _has_item_indicator,
    _strip_ordering_prefix,
    _is_modifier_only,
)

# Import consolidated skip words from constants
from orderbot.tasks.parsers.constants import (
    TOKENIZATION_SKIP_WORDS as _SKIP_WORDS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Multi-Item Order Parsing
# =============================================================================

def _parse_multi_item_order(user_input: str) -> OpenInputResponse | None:
    """Parse multi-item orders like 'The Lexington and an orange juice'.

    This function uses smart tokenization to split multi-item orders while
    properly handling compound phrases (resolved via menu item aliases) and
    modifier chains. All logic is data-driven with no hardcoded food references.

    Returns OpenInputResponse with parsed_items list if 2+ items detected.
    """
    # Import here to avoid circular imports (tokenization imports from us too via re-exports)
    from .tokenization import _smart_split_and_tokenize
    from .token_recombination import _recombine_tokens

    text = user_input.strip()
    text_lower = text.lower()

    # --- Step 1: Check for modifier chains (don't split) ---
    if _is_modifier_chain(text_lower):
        logger.debug("Multi-item: skipping split - detected modifier chain: '%s'", text[:60])
        return None

    if _is_with_modifier_chain(text_lower, text):
        return None

    # --- Step 2: Use smart tokenization to split and classify ---
    tokens = _smart_split_and_tokenize(text_lower)
    if len(tokens) < 2:
        return None

    # --- Step 3: Check if tokens are really modifiers, not separate items ---
    # Skip this check for "with [article] [item]" splits — those were already
    # validated by _has_item_indicator on both sides in _try_split_on_with_article.
    # Without this skip, words like "bagel" (which is both an attribute option for
    # bread type and a configurable item) get incorrectly demoted to modifiers.
    is_with_article_split = (
        " with " in text_lower
        and " and " not in text_lower
        and ", " not in text_lower
    )
    if not is_with_article_split and _all_tokens_are_modifiers(tokens, text):
        return None

    # --- Step 4: Recombine modifier tokens with their items ---
    combined_tokens, dropped_unknowns = _recombine_tokens(tokens)
    logger.info("Multi-item tokens after recombine: %s", [(t.original, t.token_type) for t in combined_tokens])

    # --- Step 5: Filter to only item tokens ---
    item_tokens = [t for t in combined_tokens if t.token_type == "item"]

    if len(item_tokens) < 2:
        # If we have exactly 1 recognized item + dropped unknowns, parse the
        # single item and surface the unknowns instead of silently returning None
        if len(item_tokens) == 1 and dropped_unknowns:
            response = _build_items_from_tokens(item_tokens, min_items=1)
            if response:
                response.unrecognized_item_names = dropped_unknowns
                return response
        return None

    # --- Step 6: Parse each item token and build response ---
    response = _build_items_from_tokens(item_tokens)
    if response and dropped_unknowns:
        response.unrecognized_item_names = dropped_unknowns
    return response


# =============================================================================
# Multi-Item Pipeline Helpers
# =============================================================================

def _is_with_modifier_chain(text_lower: str, text: str) -> bool:
    """Check for "item with modifier and modifier" pattern that should not be split.

    Detects patterns like "bagel with butter and cream cheese" where the "and" joins
    modifiers after "with", not separate items. But allows "latte with vanilla and a
    bagel" through since it's genuinely multi-item (article + item after "and").

    Returns True if input should be treated as a single item (skip multi-item split).
    """
    if " with " not in text_lower or " and " not in text_lower:
        return False

    with_idx = text_lower.find(" with ")
    and_idx = text_lower.find(" and ")

    # Only apply this check if "and" comes AFTER "with" (potential modifier chain)
    if and_idx <= with_idx:
        return False

    # Check what comes after "and" - if it's an article followed by an item, it's multi-item
    after_and = text_lower[and_idx + 5:].strip()  # " and " is 5 chars
    starts_with_article = any(after_and.startswith(art) for art in ("a ", "an ", "the "))

    if starts_with_article:
        # Strip article and check for item indicator
        for art in ("a ", "an ", "the "):
            if after_and.startswith(art):
                after_and = after_and[len(art):]
                break
        # Strip leading amount qualifier words (e.g., "little", "extra", "bit of")
        after_qualifiers = _strip_leading_qualifiers(after_and)
        # Check if the remaining text is a known modifier/ingredient
        if after_qualifiers and menu_cache.is_known_modifier(after_qualifiers):
            logger.debug(
                "Multi-item: skipping split - 'and a [qualifier] [modifier]' pattern: '%s'",
                text[:60],
            )
            return True
        # Check if this contains an item type trigger
        has_item, _, _ = _has_item_indicator(after_and)
        if has_item:
            # It's "with X and a [item]" - this is multi-item, not modifier chain
            logger.debug("Multi-item: proceeding - 'and a [item]' pattern detected: '%s'", text[:60])
            return False
    else:
        # No article after "and" - check if it's a modifier chain
        with_parts = text_lower.split(" with ", 1)
        if len(with_parts) == 2:
            after_with = with_parts[1]
            all_modifiers = menu_cache.get_all_modifier_words()
            first_after_with = after_with.split()[0] if after_with.split() else ""

            if first_after_with in all_modifiers:
                logger.debug(
                    "Multi-item: skipping split - 'with modifier and X' pattern: '%s'", text[:60]
                )
                return True

    return False


def _strip_leading_qualifiers(text: str) -> str:
    """Strip leading amount qualifier words from text.

    Removes qualifier prefixes like "little", "extra", "bit of" so that
    the remaining text can be checked as a modifier/ingredient.

    Args:
        text: Text to strip (lowercase, already article-stripped).

    Returns:
        Text with leading qualifiers removed.
    """
    qualifier_patterns = menu_cache.get_qualifier_patterns()
    for pattern in qualifier_patterns:
        prefix = pattern + " "
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return text


def _all_tokens_are_modifiers(tokens: list["Token"], text: str) -> bool:
    """Check if tokens that look like separate items are really modifiers for the first item.

    Handles two cases:
    1. First token is an item and the rest are pure modifier/attribute/separator tokens.
    2. First token is an item and subsequent tokens are items that double as modifiers
       (e.g., "butter" is both a menu item and a spread).

    Returns True if the tokens should NOT be treated as a multi-item order.
    """
    # Case 1: Check if tokens are all modifiers (don't split)
    # e.g., "butter, cream cheese, not toasted" should not be split
    non_modifier_count = sum(1 for t in tokens if t.token_type in ("item", "unknown"))
    if non_modifier_count < 2:
        if tokens and tokens[0].token_type == "item":
            modifier_types = ("modifier", "attribute", "separator")
            rest_are_modifiers = all(t.token_type in modifier_types for t in tokens[1:])
            if rest_are_modifiers:
                logger.debug("Multi-item: skipping split - item with modifiers: '%s'", text[:60])
                return True

    # Case 2: Check for item + modifiers that also match as items
    # e.g., "pumpernickel bagel, butter, not toasted" - butter is also a menu item
    # but in this context it's a modifier for the bagel
    if tokens and tokens[0].token_type == "item":
        if _other_tokens_are_potential_modifiers(tokens, text):
            return True

    return False


def _other_tokens_are_potential_modifiers(tokens: list["Token"], text: str) -> bool:
    """Check if all tokens after the first are potential modifiers for the first item.

    Builds a set of known modifiers, attribute options, and boolean attributes for
    the first token's item type, then checks if every subsequent non-separator token
    consists only of those known modifier words.

    Returns True if all other tokens could be modifiers (skip multi-item split).
    """
    all_modifiers = menu_cache.get_all_modifier_words()
    attr_options = menu_cache.get_all_attribute_option_words()

    # Get boolean attribute names (like "toasted", "scooped")
    # Check all item types that might match the first token (handles ambiguous detection)
    boolean_attrs: set[str] = set()
    all_triggers = menu_cache.get_item_type_triggers()
    first_text = tokens[0].original.lower()

    # Find all item types that have triggers matching words in the first token
    item_types_to_check: set[str] = set()
    for item_type_slug, triggers in all_triggers.items():
        for trigger in triggers:
            if trigger.lower() in first_text:
                item_types_to_check.add(item_type_slug)
                break

    # Collect boolean attrs from all matching item types
    for check_type in item_types_to_check:
        item_attrs = menu_cache.get_item_type_attributes(check_type)
        if item_attrs:
            for attr_name, attr_info in item_attrs.items():
                # Boolean attrs have input_type: 'boolean'
                if isinstance(attr_info, dict) and attr_info.get("input_type") == "boolean":
                    boolean_attrs.add(attr_name.lower())
                    boolean_attrs.add(attr_name.lower().replace("_", " "))

    def _is_potential_modifier(token_text: str) -> bool:
        """Check if text could be a modifier (ignoring item matches)."""
        # Filter out skip words by word boundary (not substring replace)
        words = [w for w in token_text.lower().strip().split() if w not in _SKIP_WORDS]
        text_clean = " ".join(words)
        # Multi-word phrases matching a real menu item are NOT just modifiers.
        # e.g., "scottish salmon" has words that are individual modifiers, but
        # the phrase itself is a menu item and should not be demoted.
        if " " in text_clean:
            if (menu_cache.find_items_by_word_match(text_clean)
                    or menu_cache.find_all_items_by_word_match(text_clean)):
                return False
        for word in words:
            word = word.strip()
            if not word or word == "and" or word == "not":
                continue
            # Check if it's a known modifier, attribute option, or boolean attr
            if word in all_modifiers or word in attr_options or word in boolean_attrs:
                continue
            # Check multi-word phrases
            if text_clean in all_modifiers or text_clean in attr_options:
                continue
            # Unknown word - not a modifier
            return False
        return True

    other_tokens = [t for t in tokens[1:] if t.token_type != "separator"]
    # Only skip if ALL other tokens could be modifiers (even if also classified as items)
    # e.g., "butter" is both a menu item AND a spread - in "bagel, butter" context, it's a modifier
    first_type = tokens[0].item_type
    if other_tokens:
        for t in other_tokens:
            # A token classified as a different item type that isn't also a known
            # modifier/ingredient cannot be a modifier for the first item.
            # e.g., "earl gray" classified as tea in "bagel and earl gray" is a
            # separate item, not a modifier for the bagel.
            if (
                t.token_type == "item"
                and t.item_type
                and first_type
                and t.item_type != first_type
                and not menu_cache.is_known_modifier(t.original.lower().strip())
            ):
                return False
            if not _is_potential_modifier(t.original):
                return False
        logger.debug("Multi-item: skipping split - item with modifier-like parts: '%s'", text[:60])
        return True

    return False


def _derive_item_name_from_token(token: "Token") -> str:
    """Derive a more specific item_name from a token's original text.

    When the tokenizer resolves "a large orange juice" via trigger matching,
    resolved_name may be just the trigger keyword ("juice"). This function
    recovers qualifier words (like "orange") by stripping only articles and
    attribute option words (like "large") from the original text.

    Returns the derived name if it's more specific than resolved_name,
    otherwise falls back to resolved_name.
    """
    # Start from the original text, strip ordering prefix + articles
    stripped = _strip_ordering_prefix(token.original)
    if not stripped:
        return token.resolved_name or ""

    # Strip leading attribute option words (e.g., "large", "iced")
    attr_option_words = menu_cache.get_all_attribute_option_words()
    text_lower = stripped.lower()
    while text_lower:
        matched = False
        for option_word in sorted(attr_option_words.keys(), key=len, reverse=True):
            if re.match(rf'^{re.escape(option_word)}\s+', text_lower):
                text_lower = text_lower[len(option_word):].strip()
                matched = True
                break
        if not matched:
            break

    # Use the derived name only if it's more specific (longer) than resolved_name
    resolved = token.resolved_name or ""
    if text_lower and len(text_lower) > len(resolved):
        return text_lower

    return resolved


def _build_items_from_tokens(
    item_tokens: list["Token"], min_items: int = 2,
) -> OpenInputResponse | None:
    """Parse item tokens into menu items and build an OpenInputResponse.

    For each item token, attempts to parse it using the generic parser. Falls back
    to the full deterministic parser if generic parsing fails.

    Args:
        item_tokens: List of item tokens to parse.
        min_items: Minimum number of successfully parsed items required (default 2).

    Returns OpenInputResponse with parsed_items if >= min_items found, else None.
    """
    parsed_items: list = []
    for token in item_tokens:
        # Derive a better item_name from the token's original text
        # e.g., "a large orange juice" -> "orange juice" instead of just "juice"
        item_name = _derive_item_name_from_token(token)

        # Use the generic parser with detected item type and resolved name
        # Returns a list (may be >1 for partial modifier splits)
        parsed_result = _parse_item_generic(
            text=token.original,
            item_type=token.item_type,
            item_name=item_name,
        )

        if parsed_result:
            # Apply quantity from token only when result is a single item
            # (partial modifier splits already have correct quantities)
            if token.quantity and token.quantity > 1 and len(parsed_result) == 1:
                parsed_result[0].quantity = token.quantity
            parsed_items.extend(parsed_result)
            logger.debug("Multi-item: parsed '%s' -> %s", token.original[:40], parsed_result[0].item_type)
        else:
            # Fallback: try full deterministic parser
            # Note: import here to avoid circular imports
            from .core import parse_open_input_deterministic
            full_result = parse_open_input_deterministic(token.original)
            if full_result and full_result.parsed_items:
                for item in full_result.parsed_items:
                    parsed_items.append(item)
                logger.debug("Multi-item: fallback parsed '%s'", token.original[:40])

    if len(parsed_items) >= min_items:
        logger.info("Multi-item order parsed: %d items", len(parsed_items))
        return OpenInputResponse(parsed_items=parsed_items)

    return None
