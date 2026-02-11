"""
Tokenization Functions for Multi-Item Order Parsing.

This module contains functions for smart tokenization and classification
of user input to support multi-item order parsing.
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ...schemas import OpenInputResponse
from ..quantity_utils import extract_leading_quantity as _extract_leading_quantity

from .item_parsing import _detect_item_type, _parse_item_generic, _is_modifier_chain

logger = logging.getLogger(__name__)


# =============================================================================
# Constants for Tokenization
# =============================================================================

# Import consolidated skip words from constants
from orderbot.tasks.parsers.constants import (
    TOKENIZATION_SKIP_WORDS as _SKIP_WORDS,
    ORDERING_PREFIXES,
    ARTICLES,
)

# Trailing politeness words that should be stripped before menu item matching
_TRAILING_STRIP_WORDS = {"please", "thanks", "thank you", "ok", "okay", "alright", "pls", "thx"}


def _strip_trailing_words(text: str) -> str:
    """Strip trailing politeness words from text for menu item matching."""
    words = text.split()
    while words and words[-1].lower().rstrip(".,!?") in _TRAILING_STRIP_WORDS:
        words.pop()
    return " ".join(words)


def _strip_ordering_prefix(text: str) -> str:
    """Strip ordering prefixes and following articles from text.

    Handles phrases like "I'd like an egg and cheese sandwich" -> "egg and cheese sandwich"

    Args:
        text: Text to strip

    Returns:
        Text with ordering prefix and article stripped
    """
    text_lower = text.lower().strip()

    # Strip ordering prefixes (sorted by length, longest first)
    for prefix in sorted(ORDERING_PREFIXES, key=len, reverse=True):
        if text_lower.startswith(prefix):
            # Check for word boundary
            if len(text_lower) > len(prefix) and text_lower[len(prefix)].isalnum():
                continue
            text_lower = text_lower[len(prefix):].strip()
            break

    # Strip leading articles (a, an, the)
    for article in sorted(ARTICLES, key=len, reverse=True):
        if text_lower.startswith(article + " "):
            text_lower = text_lower[len(article):].strip()
            break

    return text_lower


# =============================================================================
# Item Indicator Detection
# =============================================================================

def _has_item_indicator(text: str) -> tuple[bool, str | None, str | None]:
    """Check if text contains an item type trigger or matches a menu item.

    Prioritizes item triggers that appear early in the text (especially after
    articles like "a", "an") over longer triggers that appear later. This
    correctly identifies "a bagel with cream cheese" as a bagel, not cream cheese.

    Args:
        text: Text to check

    Returns:
        (has_indicator, item_type, resolved_name)
        - (True, "sized_beverage", "Latte") if triggers coffee
        - (True, "egg_sandwich", "The Classic BEC") if matches menu item
        - (False, None, None) if no item indicator

    Examples:
        >>> _has_item_indicator("large iced latte")
        (True, "sized_beverage", "latte")
        >>> _has_item_indicator("bacon egg and cheese")
        (True, "egg_sandwich", "The Classic BEC")  # if alias exists
        >>> _has_item_indicator("cream cheese")
        (False, None, None)
    """
    text_lower = text.lower().strip()

    # Strip trailing politeness words (please, thanks, etc.) before matching
    text_for_matching = _strip_trailing_words(text_lower)

    # Also prepare singularized version for matching plurals like "coffees" -> "coffee"
    # Singularize each word to handle "three coffees" -> "three coffee"
    words = text_for_matching.split()
    singularized_words = [singularize(w) for w in words]
    text_singularized = " ".join(singularized_words)

    # First, check if entire text matches a menu item (including aliases)
    # Try both original and singularized forms
    resolved = menu_cache.resolve_menu_item_alias(text_for_matching)
    if not resolved and text_singularized != text_for_matching:
        resolved = menu_cache.resolve_menu_item_alias(text_singularized)
    if resolved:
        # Get the item type from the resolved menu item (not from text triggers)
        # This ensures "egg and cheese" → "Egg and Cheese Sandwich" → "egg_sandwich"
        item_type = menu_cache.get_item_type_for_menu_item(resolved)
        if not item_type:
            # Fallback to trigger-based detection if menu item lookup fails
            item_type, _ = _detect_item_type(text_lower)
        return True, item_type, resolved

    # Second, check if text matches menu items by word boundary (for ambiguous cases)
    # This handles "the classic" which matches multiple items (The Classic BEC, etc.)
    # We return True to indicate it's an item indicator, even if disambiguation is needed later
    word_matches = menu_cache.find_items_by_word_match(text_for_matching)
    if word_matches:
        # Multiple matches - pick the first one's item_type (disambiguation happens later)
        first_match = word_matches[0]
        item_type = first_match.get("item_type")
        # Use the search term as resolved_name since we don't have a single match
        return True, item_type, text_for_matching

    # Check for item type triggers - prioritize early matches
    all_triggers = menu_cache.get_item_type_triggers()

    # Common words that should not be treated as item triggers
    skip_trigger_words = {
        "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "the", "a", "an", "and", "or", "with", "on", "in", "of", "to", "for",
    }

    # Find all matches and their positions
    matches: list[tuple[int, int, str, str]] = []  # (position, length, item_type, trigger)

    # Try matching triggers against both original and singularized text
    texts_to_try = [text_for_matching]
    if text_singularized != text_for_matching:
        texts_to_try.append(text_singularized)

    for item_type_slug, triggers in all_triggers.items():
        for keyword in triggers:
            # Skip common words that appear as triggers from menu item names
            if keyword.lower() in skip_trigger_words:
                continue
            keyword_lower = keyword.lower()
            # Use word boundary matching to prevent partial matches
            # (e.g., "hot" matching inside "shot")
            pattern = rf'\b{re.escape(keyword_lower)}\b'
            for try_text in texts_to_try:
                match = re.search(pattern, try_text)
                if match:
                    pos = match.start()
                    matches.append((pos, len(keyword_lower), item_type_slug, keyword))
                    break  # Found in one form, no need to try singularized

    # Add implicit triggers for item type names themselves
    # This handles cases where "bagel" type doesn't have "bagel" as explicit trigger
    # Use get_configurable_item_types() to include all item types, not just those with triggers
    all_item_types = menu_cache.get_configurable_item_types()
    for item_type_slug in all_item_types:
        # Check for the item type name (with underscores replaced by spaces)
        type_variants = [
            item_type_slug.lower(),
            item_type_slug.lower().replace("_", " "),
        ]
        for variant in type_variants:
            # Use word boundary matching to prevent partial matches
            pattern = rf'\b{re.escape(variant)}\b'
            for try_text in texts_to_try:
                match = re.search(pattern, try_text)
                if match:
                    pos = match.start()
                    # Only add if not already matched at this position
                    existing = [(m[0], m[2]) for m in matches]
                    if (pos, item_type_slug) not in existing:
                        matches.append((pos, len(variant), item_type_slug, variant))
                    break  # Found in one form, no need to try singularized

    if not matches:
        return False, None, None


    # Get modifiers and attribute options for deprioritizing modifier-based triggers
    all_modifiers = menu_cache.get_all_modifier_words()
    all_attr_options = menu_cache.get_all_attribute_option_words()

    # Item type priority: prefer specific types over generic ones
    # When trigger is the same word for multiple types, prefer the type
    # that matches the trigger word itself (e.g., "bagel" -> bagel type)
    def _type_priority(item_type: str, trigger: str) -> int:
        """Return priority score (lower = better)."""
        trigger_lower = trigger.lower()
        # Best: item type matches the trigger word (bagel -> bagel)
        if item_type.lower() == trigger_lower:
            return 0
        # Also best: trigger is a known item name for this specific item_type
        # e.g., "latte" is in sized_beverage's item names, so sized_beverage gets high priority
        # This is fully data-driven - works for any item type, not just beverages
        item_type_names = menu_cache.get_item_names_by_type(item_type)
        if trigger_lower in {n.lower() for n in item_type_names}:
            return 1
        # Also best: trigger matches another item type name exactly
        # This means the trigger is likely targeting that specific type, not this one
        # e.g., "bagel" trigger for "side" type should yield to "bagel" type if it exists
        if trigger_lower in all_item_types or trigger_lower.replace(" ", "_") in all_item_types:
            # This item_type doesn't match the trigger, but another type does
            # Demote this match significantly
            return 6
        # Deprioritize triggers that are actually modifiers/attributes (but not coffee types)
        # e.g., "large" is a size, not an item indicator
        if trigger_lower in all_modifiers or trigger_lower in all_attr_options:
            return 5
        # Good: item type contains the trigger word (e.g., "egg_sandwich" contains "egg")
        if trigger_lower in item_type.lower():
            return 1
        # Generic types have lower priority
        generic_types = {"side", "snack", "beverage", "menu_item"}
        if item_type in generic_types:
            return 4
        return 2

    # Check if any trigger word matches an item type name
    # Add implicit match for that item type (with position from the trigger location)
    added_implicit = []
    for pos, length, item_type, trigger in list(matches):
        trigger_lower = trigger.lower()
        if trigger_lower in all_item_types and trigger_lower != item_type:
            # The trigger word is an item type name, add it as a match
            matches.append((pos, length, trigger_lower, trigger))
            added_implicit.append((pos, length, trigger_lower, trigger))
        trigger_underscore = trigger_lower.replace(" ", "_")
        if trigger_underscore in all_item_types and trigger_underscore != item_type:
            matches.append((pos, length, trigger_underscore, trigger))
            added_implicit.append((pos, length, trigger_underscore, trigger))

    # PRIORITY RULES:
    # 1. Priority 0 matches (trigger == item_type, e.g., "bagel" -> bagel) always win
    # 2. Among same-priority matches, prefer earlier position
    # 3. For position < 15, prefer that match unless priority 0 exists elsewhere

    # First, check if any match has priority 0 (trigger matches item type)
    priority_0_matches = [
        m for m in matches
        if _type_priority(m[2], m[3]) == 0
    ]

    if priority_0_matches:
        # Sort priority 0 matches by position, then length
        priority_0_matches.sort(key=lambda x: (x[0], -x[1]))
        best = priority_0_matches[0]
        return True, best[2], best[3]

    # No priority 0 matches - use priority + position logic
    # Sort by priority first, then position (within first 30 chars), then length
    def _match_score(m):
        pos, length, item_type, trigger = m
        priority = _type_priority(item_type, trigger)
        # Group positions: early (<=15), mid (16-30), late (>30)
        pos_group = 0 if pos <= 15 else (1 if pos <= 30 else 2)
        return (priority, pos_group, pos, -length)

    matches.sort(key=_match_score)

    best = matches[0]
    return True, best[2], best[3]


# =============================================================================
# Modifier-Only Detection
# =============================================================================

def _is_modifier_only(text: str) -> tuple[bool, list[str]]:
    """Check if text contains ONLY modifiers (no item triggers).

    Modifiers include:
    - Known ingredients (bacon, cheese, cream cheese, lox)
    - Known attribute options (large, medium, iced, hot)
    - Quantity words are skipped

    Args:
        text: Text to check

    Returns:
        (is_modifier_only, list_of_modifiers)
        - (True, ["cream cheese"]) if only modifiers
        - (False, []) if contains item trigger or unknown words

    Examples:
        >>> _is_modifier_only("cream cheese")
        (True, ["Cream Cheese"])
        >>> _is_modifier_only("bacon and cheese")
        (True, ["Bacon", "American Cheese"])
        >>> _is_modifier_only("large iced latte")
        (False, [])  # "latte" is an item trigger
    """
    text_lower = text.lower().strip()

    # Remove quantity prefix
    _, remaining = _extract_leading_quantity(text_lower)
    if not remaining:
        return False, []

    # Check if this has any item indicators
    has_item, _, _ = _has_item_indicator(remaining)
    if has_item:
        return False, []

    # Get lookup data
    all_modifiers = menu_cache.get_all_modifier_words()
    attr_options = menu_cache.get_all_attribute_option_words()

    # Tokenize and check each word/phrase
    # First try to match multi-word modifiers (e.g., "cream cheese")
    found_modifiers = []
    remaining_to_check = remaining

    # Try to match known multi-word modifiers first
    for modifier in sorted(all_modifiers, key=len, reverse=True):
        if modifier in remaining_to_check:
            normalized = menu_cache.normalize_modifier(modifier)
            found_modifiers.append(normalized)
            remaining_to_check = remaining_to_check.replace(modifier, " ").strip()

    # Check remaining words
    words = remaining_to_check.split()
    for word in words:
        word = word.strip().lower()
        if not word:
            continue

        # Skip common words
        if word in _SKIP_WORDS:
            continue

        # Skip "and" separator
        if word == "and":
            continue

        # Check if it's a known modifier
        if word in all_modifiers:
            normalized = menu_cache.normalize_modifier(word)
            if normalized not in found_modifiers:
                found_modifiers.append(normalized)
            continue

        # Check if it's a known attribute option
        if word in attr_options:
            continue

        # Unknown word - this is NOT modifier-only
        return False, []

    return True, found_modifiers


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
    text_lower = text.lower()

    # Check for separator
    if text_lower in ("and", ","):
        return Token(original=text, token_type="separator")

    # Extract quantity
    quantity, remaining = _extract_leading_quantity(text)

    # If only quantity (e.g., just "a" or "2"), it's a quantity token
    if not remaining and quantity is not None:
        return Token(original=text, token_type="quantity", quantity=quantity)

    # Check if it has an item indicator
    has_item, item_type, resolved_name = _has_item_indicator(remaining if remaining else text)
    if has_item:
        return Token(
            original=text,
            token_type="item",
            quantity=quantity or 1,
            item_type=item_type,
            resolved_name=resolved_name,
        )

    # Check if it's modifier-only
    is_mod, modifiers = _is_modifier_only(remaining if remaining else text)
    if is_mod:
        return Token(
            original=text,
            token_type="modifier",
            resolved_name=", ".join(modifiers) if modifiers else None,
        )

    # Check if it's an attribute option
    attr_options = menu_cache.get_all_attribute_option_words()
    if text_lower in attr_options:
        return Token(
            original=text,
            token_type="attribute",
            attribute_slug=attr_options[text_lower],
        )

    # Unknown
    return Token(original=text, token_type="unknown")


# =============================================================================
# Smart Tokenization
# =============================================================================

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

    text_lower = text.lower().strip()

    # Strip ordering prefixes for compound phrase detection
    # "I'd like an egg and cheese sandwich" -> "egg and cheese sandwich"
    text_for_compound = _strip_ordering_prefix(text_lower)

    # First, try to match entire input as a single item
    has_item, item_type, resolved_name = _has_item_indicator(text_lower)

    # Check if this is a compound phrase that shouldn't be split (e.g., "bacon egg and cheese")
    # First check exact match, then check if input STARTS with a compound phrase
    # Use stripped text for compound detection to handle "I'd like an egg and cheese sandwich"
    is_compound = menu_cache.is_compound_phrase(text_for_compound)
    compound_match = None
    if not is_compound:
        # Check if a compound phrase appears at the start (e.g., "egg and cheese on plain bagel")
        compound_match = menu_cache.find_compound_phrase_in(text_for_compound)
        if compound_match:
            # Found a compound phrase at start - check if there's a second item anywhere
            # Use text_for_compound (stripped version) for remainder since compound_match is from it
            remainder = text_for_compound[len(compound_match):].strip()

            # Helper function to create the multi-item split result
            def _create_multi_item_split(
                first_item_text: str, after_and: str, next_item_type: str, next_resolved: str
            ) -> list:
                """Create token list for compound phrase + second item split."""
                # Get item type for the compound phrase
                _, compound_item_type, compound_resolved = _has_item_indicator(compound_match)
                qty, _ = _extract_leading_quantity(first_item_text.lower())

                # Use the full first item text (with modifiers) for original
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
                else:
                    # Remainder didn't split further - classify it directly
                    qty2, _ = _extract_leading_quantity(after_and)
                    return [compound_token, Token(
                        original=after_and,
                        token_type="item",
                        quantity=qty2 or 1,
                        item_type=next_item_type,
                        resolved_name=next_resolved,
                    )]

            # First check if remainder starts with "and " (e.g., "and a latte")
            if remainder.startswith("and "):
                after_and = remainder[4:].strip()  # skip "and "
                has_next_item, next_item_type, next_resolved = _has_item_indicator(after_and)
                if has_next_item:
                    return _create_multi_item_split(compound_match, after_and, next_item_type, next_resolved)

            # Search for " and " anywhere in remainder (not just at start)
            # e.g., "on plain bagel and a coffee" -> find " and " at position 14
            and_idx = remainder.find(" and ")
            while and_idx != -1:
                # Check if what follows " and " is an item
                after_and = remainder[and_idx + 5:].strip()  # skip " and "
                has_next_item, next_item_type, next_resolved = _has_item_indicator(after_and)

                if has_next_item:
                    # Multi-item: compound phrase + modifiers + second item
                    # First item = compound + everything before " and "
                    first_item_text = compound_match + " " + remainder[:and_idx].strip()
                    first_item_text = first_item_text.strip()
                    return _create_multi_item_split(first_item_text, after_and, next_item_type, next_resolved)

                # Not an item after this " and " - search for next occurrence
                and_idx = remainder.find(" and ", and_idx + 5)

            # No multi-item split found - treat entire input as single item
            is_compound = True

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

    if len(parts) < 2:
        # Not a multi-item order
        return []

    # Classify each part
    tokens = []
    for part in parts:
        token = _classify_token(part)
        tokens.append(token)

    return tokens


# =============================================================================
# Token Recombination
# =============================================================================

def _recombine_tokens(tokens: list["Token"]) -> list["Token"]:
    """Recombine modifier tokens with their associated item tokens.

    Modifier tokens are attached to the PREVIOUS item token.

    Args:
        tokens: List of classified tokens

    Returns:
        List of item tokens with modifiers combined

    Examples:
        >>> tokens = [Token("bacon egg", item), Token("cheese", modifier), Token("coffee", item)]
        >>> _recombine_tokens(tokens)
        [Token("bacon egg and cheese", item), Token("coffee", item)]
    """
    from orderbot.tasks.schemas.parser_responses import Token

    if not tokens:
        return []

    result = []
    current_item = None
    accumulated_modifiers = []

    for token in tokens:
        if token.token_type == "item":
            # Save previous item with its modifiers
            if current_item:
                if accumulated_modifiers:
                    # Combine item with modifiers
                    combined_text = current_item.original + " and " + " and ".join(
                        m.original for m in accumulated_modifiers
                    )
                    # Re-check if combined text matches a menu item
                    has_item, item_type, resolved = _has_item_indicator(combined_text.lower())
                    result.append(Token(
                        original=combined_text,
                        token_type="item",
                        quantity=current_item.quantity,
                        item_type=item_type or current_item.item_type,
                        resolved_name=resolved or current_item.resolved_name,
                    ))
                else:
                    result.append(current_item)
            current_item = token
            accumulated_modifiers = []

        elif token.token_type == "modifier":
            if current_item:
                accumulated_modifiers.append(token)
            else:
                # Modifier without preceding item - treat as unknown/skip
                logger.debug("Modifier token without preceding item: %s", token.original)

        elif token.token_type == "attribute":
            # Attributes attach to current item
            if current_item:
                accumulated_modifiers.append(token)

        elif token.token_type == "unknown":
            # Unknown tokens might be part of an item name
            # Try combining with previous
            if current_item:
                combined = current_item.original + " " + token.original
                has_item, item_type, resolved = _has_item_indicator(combined.lower())
                if has_item:
                    current_item = Token(
                        original=combined,
                        token_type="item",
                        quantity=current_item.quantity,
                        item_type=item_type,
                        resolved_name=resolved,
                    )
                else:
                    # Can't combine - save current and start fresh
                    result.append(current_item)
                    current_item = None
                    accumulated_modifiers = []

    # Don't forget the last item
    if current_item:
        if accumulated_modifiers:
            combined_text = current_item.original + " and " + " and ".join(
                m.original for m in accumulated_modifiers
            )
            has_item, item_type, resolved = _has_item_indicator(combined_text.lower())
            result.append(Token(
                original=combined_text,
                token_type="item",
                quantity=current_item.quantity,
                item_type=item_type or current_item.item_type,
                resolved_name=resolved or current_item.resolved_name,
            ))
        else:
            result.append(current_item)

    return result


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
    text = user_input.strip()
    text_lower = text.lower()

    # --- Step 1: Check for modifier chain (don't split) ---
    # e.g., "large iced coffee with sugar and 2 vanilla syrups" should NOT be split
    if _is_modifier_chain(text_lower):
        logger.debug("Multi-item: skipping split - detected modifier chain: '%s'", text[:60])
        return None

    # --- Step 1b: Check for "item with modifier and modifier" pattern ---
    # e.g., "bagel with butter and cream cheese" - the "and" is AFTER "with", suggesting a modifier chain
    # But NOT "latte with vanilla and a bagel" - after "and" there's an article + item (two items)
    if " with " in text_lower and " and " in text_lower:
        with_idx = text_lower.find(" with ")
        and_idx = text_lower.find(" and ")

        # Only apply this check if "and" comes AFTER "with" (potential modifier chain)
        if and_idx > with_idx:
            # Check what comes after "and" - if it's an article followed by an item, it's multi-item
            after_and = text_lower[and_idx + 5:].strip()  # " and " is 5 chars
            starts_with_article = any(after_and.startswith(art) for art in ("a ", "an ", "the "))

            if starts_with_article:
                # Strip article and check for item indicator
                for art in ("a ", "an ", "the "):
                    if after_and.startswith(art):
                        after_and = after_and[len(art):]
                        break
                # Check if this contains an item type trigger
                has_item, _, _ = _has_item_indicator(after_and)
                if has_item:
                    # It's "with X and a [item]" - this is multi-item, not modifier chain
                    logger.debug("Multi-item: proceeding - 'and a [item]' pattern detected: '%s'", text[:60])
                    # Don't return None, let it proceed to multi-item parsing
                else:
                    # After article there's no item - might still be modifier chain
                    pass
            else:
                # No article after "and" - check if it's a modifier chain
                with_parts = text_lower.split(" with ", 1)
                if len(with_parts) == 2:
                    after_with = with_parts[1]
                    all_modifiers = menu_cache.get_all_modifier_words()
                    first_after_with = after_with.split()[0] if after_with.split() else ""

                    if first_after_with in all_modifiers:
                        logger.debug("Multi-item: skipping split - 'with modifier and X' pattern: '%s'", text[:60])
                        return None

    # --- Step 2: Use smart tokenization to split and classify ---
    tokens = _smart_split_and_tokenize(text_lower)
    if len(tokens) < 2:
        # Not a multi-item order (single item or nothing)
        return None

    # --- Step 3: Check if tokens are all modifiers (don't split) ---
    # e.g., "butter, cream cheese, not toasted" should not be split
    non_modifier_count = sum(1 for t in tokens if t.token_type in ("item", "unknown"))
    if non_modifier_count < 2:
        # Check if first token is item and rest are modifiers
        if tokens and tokens[0].token_type == "item":
            modifier_types = ("modifier", "attribute", "separator")
            rest_are_modifiers = all(t.token_type in modifier_types for t in tokens[1:])
            if rest_are_modifiers:
                logger.debug("Multi-item: skipping split - item with modifiers: '%s'", text[:60])
                return None

    # --- Step 3b: Check for item + modifiers that also match as items ---
    # e.g., "pumpernickel bagel, butter, not toasted" - butter is also a menu item
    # but in this context it's a modifier for the bagel
    if tokens and tokens[0].token_type == "item":
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
            text_clean = token_text.lower().strip()
            # Remove common words
            for skip in _SKIP_WORDS:
                text_clean = text_clean.replace(skip, " ").strip()
            # Split and check each word
            words = text_clean.split()
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
        if other_tokens:
            # Check if all other tokens are potential modifiers
            # (This includes items that double as modifiers, like "butter")
            if all(_is_potential_modifier(t.original) for t in other_tokens):
                logger.debug("Multi-item: skipping split - item with modifier-like parts: '%s'", text[:60])
                return None

    # --- Step 4: Recombine modifier tokens with their items ---
    combined_tokens = _recombine_tokens(tokens)
    logger.info("Multi-item tokens after recombine: %s", [(t.original, t.token_type) for t in combined_tokens])

    # --- Step 5: Filter to only item tokens ---
    item_tokens = [t for t in combined_tokens if t.token_type == "item"]
    if len(item_tokens) < 2:
        return None

    # --- Step 6: Parse each item token using generic parser ---
    parsed_items: list = []
    for token in item_tokens:
        # Use the generic parser with detected item type and resolved name
        parsed_item = _parse_item_generic(
            text=token.original,
            item_type=token.item_type,
            item_name=token.resolved_name,
        )

        if parsed_item:
            # Apply quantity from token if detected
            if token.quantity and token.quantity > 1:
                parsed_item.quantity = token.quantity
            parsed_items.append(parsed_item)
            logger.debug("Multi-item: parsed '%s' -> %s", token.original[:40], parsed_item.item_type)
        else:
            # Fallback: try full deterministic parser
            # Note: import here to avoid circular imports
            from .core import parse_open_input_deterministic
            full_result = parse_open_input_deterministic(token.original)
            if full_result and full_result.parsed_items:
                for item in full_result.parsed_items:
                    parsed_items.append(item)
                logger.debug("Multi-item: fallback parsed '%s'", token.original[:40])

    # --- Step 7: Return if 2+ items found ---
    if len(parsed_items) >= 2:
        logger.info("Multi-item order parsed: %d items", len(parsed_items))
        return OpenInputResponse(parsed_items=parsed_items)

    return None
