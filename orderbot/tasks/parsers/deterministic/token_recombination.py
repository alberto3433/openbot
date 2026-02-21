"""
Token Recombination Functions.

Recombines classified tokens back into item groups, merging modifier tokens
with their associated item tokens.

Extracted from tokenization.py during decomposition refactoring.
"""

import logging

from orderbot.cache import menu_cache

from ..quantity_utils import extract_leading_quantity as _extract_leading_quantity
from ...utils.text import normalize_text
from .item_indicator import _has_item_indicator

logger = logging.getLogger(__name__)


def _is_demotable_to_modifier(token: "Token") -> bool:
    """Check if an item-classified token could be demoted to a modifier.

    When a token like "lox" is classified as an item (because it matches a menu item),
    but it's also a known modifier/ingredient, it can be demoted to attach to a
    preceding item in a "with X and Y" chain.

    Args:
        token: An item-classified token to check

    Returns:
        True if the token's text is also a known modifier
    """
    text = normalize_text(token.original)
    # Strip quantity prefix (e.g., "2 lox" -> "lox")
    _, remaining = _extract_leading_quantity(text)
    check_text = remaining if remaining else text
    return menu_cache.is_known_modifier(check_text)


def _flush_current_item(
    current_item: "Token",
    accumulated_modifiers: list["Token"],
) -> "Token":
    """Merge an item token with its accumulated modifier tokens.

    If there are modifiers, combines them with the item text and re-checks
    the combined text against the menu. Returns the (possibly enriched) token.
    """
    if not accumulated_modifiers:
        return current_item

    from orderbot.tasks.schemas.parser_responses import Token

    combined_text = current_item.original + " and " + " and ".join(
        m.original for m in accumulated_modifiers
    )
    has_item, item_type, resolved = _has_item_indicator(combined_text.lower())
    return Token(
        original=combined_text,
        token_type="item",
        quantity=current_item.quantity,
        item_type=item_type or current_item.item_type,
        resolved_name=resolved or current_item.resolved_name,
    )


def _recombine_tokens(tokens: list["Token"]) -> tuple[list["Token"], list[str]]:
    """Recombine modifier tokens with their associated item tokens.

    Modifier tokens are attached to the PREVIOUS item token.

    Args:
        tokens: List of classified tokens

    Returns:
        Tuple of (item tokens with modifiers combined, dropped unknown token texts)

    Examples:
        >>> tokens = [Token("bacon egg", item), Token("cheese", modifier), Token("coffee", item)]
        >>> _recombine_tokens(tokens)
        ([Token("bacon egg and cheese", item), Token("coffee", item)], [])
    """
    from orderbot.tasks.schemas.parser_responses import Token

    if not tokens:
        return [], []

    result = []
    dropped_unknowns: list[str] = []
    current_item = None
    accumulated_modifiers = []

    for token in tokens:
        if token.token_type == "item":
            # Demote item to modifier if it follows an active "with" clause
            # e.g., "bagel with cream cheese" + "lox" → lox attaches as modifier
            if (
                current_item
                and " with " in current_item.original.lower()
                and _is_demotable_to_modifier(token)
            ):
                accumulated_modifiers.append(token)
                continue

            # Save previous item with its modifiers
            if current_item:
                result.append(_flush_current_item(current_item, accumulated_modifiers))
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
                    text = token.original.strip()
                    if text:
                        dropped_unknowns.append(text)
            else:
                # No current item to combine with - track as dropped
                text = token.original.strip()
                if text:
                    dropped_unknowns.append(text)

    # Don't forget the last item
    if current_item:
        result.append(_flush_current_item(current_item, accumulated_modifiers))

    return result, dropped_unknowns
