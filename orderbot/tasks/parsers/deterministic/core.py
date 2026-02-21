"""
Core Deterministic Parser - Main Entry Point.

This module contains the main deterministic parsing function that orchestrates
all sub-parsers to parse user input without LLM calls.
"""

import re
import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import contains_word_or_singular

from ...schemas import OpenInputResponse

from ..quantity_utils import QTY_WORDS_RE, parse_make_it_n_quantity
from ..intent_patterns import (
    strip_conversational_fillers,
    REPLACE_ITEM_PATTERN,
    MAKE_IT_N_WITH_ITEM_PATTERN,
)
from .result_types import ParserContext
from .item_parsing import (
    _parse_configurable_item,
    _parse_split_quantity_items,
)
from .tokenization import _parse_multi_item_order
from .inline_spec_parsing import _is_inline_attribute_spec_pattern
from .meta_parsing import _is_only_filler, _try_parse_greeting_or_meta
from .order_type_parsing import _extract_order_type, _strip_order_type_phrase
from .another_item_parsing import _try_parse_another_item
from .inquiry_dispatch import _try_parse_inquiry
from .quantity_change_parsing import _try_parse_quantity_change
from .cancellation_parsing import _try_parse_cancellation
from .text_cleaning import (  # noqa: F401
    _extract_replacement_item,
    _filter_duplicate_modifications,
    _strip_noise_phrases,
    _strip_leading_attribute_words,
)
from .item_resolution import (  # noqa: F401
    _try_parse_modification,
    _parse_direct_menu_item,
    _try_parse_new_items,
    _check_standalone_ingredient,
)

logger = logging.getLogger(__name__)


def parse_open_input_deterministic(
    user_input: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
    ctx: ParserContext | None = None,
) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Spread options are loaded from the database cache (GlobalAttributeOption for "spread").

    Args:
        user_input: The user's input string
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
        ingredient_to_items: Mapping of ingredient names to menu items containing them
            (e.g., {"chicken": [{"name": "Chicken Salad Sandwich", ...}]})

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.
    """
    # Build ParserContext from legacy kwargs if not provided
    if ctx is None:
        ctx = ParserContext(
            modifier_category_keywords=modifier_category_keywords,
            modifier_item_keywords=modifier_item_keywords,
            ingredient_to_items=ingredient_to_items,
        )

    text = user_input.strip()

    # Expand abbreviations before any parsing (e.g., "cc" -> "cream cheese")
    # This must happen first so downstream parsers see canonical forms
    text = menu_cache.expand_abbreviations(text)

    # Check for greetings, gratitude, help, done ordering, repeat order
    greeting_or_meta = _try_parse_greeting_or_meta(text)
    if greeting_or_meta:
        return greeting_or_meta

    # Strip conversational fillers (after greeting/done checks, before order parsing)
    # e.g., "actually, make it two" -> "make it two"
    text = strip_conversational_fillers(text)

    # Strip container words, indifference phrases, and conditional phrases
    text = _strip_noise_phrases(text)

    # Check for order type mentions (pickup/delivery)
    order_type = _extract_order_type(text)
    if order_type:
        logger.debug("Deterministic parse: order type '%s' detected", order_type)
        # Strip order type phrase from text to continue parsing any items
        text_for_items = _strip_order_type_phrase(text)

        # If nothing meaningful left, return just order type
        if not text_for_items.strip() or _is_only_filler(text_for_items):
            return OpenInputResponse(order_type=order_type)

        # Continue parsing with cleaned text, will add order_type at the end
        text = text_for_items

    # Check for all inquiry types (price, dietary, menu, store, modifier, etc.)
    inquiry_result = _try_parse_inquiry(text, ctx)
    if inquiry_result:
        return inquiry_result

    # Check for make-it-N, reduce-to-one quantity changes
    quantity_result = _try_parse_quantity_change(text)
    if quantity_result:
        return quantity_result

    # Check for "another" patterns, "one more", "make it N [item]"
    another_result = _try_parse_another_item(text)
    if another_result:
        return another_result

    # Check for modify-existing-item and replacement phrases
    modification_result = _try_parse_modification(text)
    if modification_result:
        return modification_result

    # Check for cancellation and "add more" patterns
    cancellation_result = _try_parse_cancellation(text)
    if cancellation_result:
        return cancellation_result

    # Strip ordering prefixes ("just", "some") before new-item parsing.
    # These are in ORDERING_PREFIXES but not HESITATION_FILLERS. Must happen AFTER
    # quantity change checks (e.g., "just one bagel" = reduce-to-one needs "just")
    # but BEFORE item parsing (e.g., "just a 6 Bagel Package" needs "just a" stripped).
    # Also strip the trailing article (a/an/the) so "just a bagel" -> "bagel".
    text = re.sub(r'^(?:just|some)\b[,\s]*(?:(?:a|an|the)\b\s*)?', '', text, flags=re.IGNORECASE).strip()

    # Check for new item orders (split-qty, multi-item, configurable, direct, simple)
    new_items_result = _try_parse_new_items(text, order_type)
    if new_items_result:
        return new_items_result

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None


# =============================================================================
# Multi-line Merge Helper
# =============================================================================

def _merge_multiline_results(
    lines: list[str],
    ctx: "ParserContext",
    require_all_produce_items: bool = False,
) -> OpenInputResponse | None:
    """Parse each line independently and merge results.

    Args:
        lines: Segments to parse independently.
        ctx: Parser context.
        require_all_produce_items: If True, every segment must produce at least
            one parsed item for the merge to succeed. Use this for weak
            boundaries (commas) where the split might be wrong.

    Returns merged OpenInputResponse, or None to fall back to single-input parsing.
    """
    all_items: list = []
    order_type = None
    done_ordering = False

    for line in lines:
        try:
            result = parse_open_input(line, ctx=ctx)
        except (ValueError, KeyError, TypeError, AttributeError, re.error):
            logger.debug("Segment parse error for '%s', aborting split", line[:50])
            if require_all_produce_items:
                return None
            continue
        if result.parsed_items:
            all_items.extend(result.parsed_items)
        elif require_all_produce_items:
            return None  # A segment produced no items — don't trust this split
        if result.order_type and not order_type:
            order_type = result.order_type
        if result.done_ordering:
            done_ordering = True

    if all_items:
        return OpenInputResponse(
            parsed_items=all_items,
            order_type=order_type,
            done_ordering=done_ordering,
        )

    return None


# =============================================================================
# Main Parse Open Input Function
# =============================================================================

def parse_open_input(
    user_input: str,
    context: str = "",
    model: str = "gpt-4o-mini",
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
    ctx: ParserContext | None = None,
) -> OpenInputResponse:
    """Parse user input when open for new orders.

    Uses deterministic parsing only - no LLM fallback.
    All parsing is data-driven via database-loaded patterns.

    Args:
        user_input: The user's input string
        context: Unused (kept for API compatibility)
        model: Unused (kept for API compatibility)
        modifier_category_keywords: Mapping of keywords to category slugs
        modifier_item_keywords: Mapping of item keywords to item type slugs
        ingredient_to_items: Mapping of ingredient names to menu items containing them
        ctx: ParserContext bundling the keyword arguments above
    """
    # Build ParserContext from legacy kwargs if not provided
    if ctx is None:
        ctx = ParserContext(
            modifier_category_keywords=modifier_category_keywords,
            modifier_item_keywords=modifier_item_keywords,
            ingredient_to_items=ingredient_to_items,
        )
    # --- Sentence boundary splitting ---
    # Split on natural boundaries and parse each statement independently.
    # Must happen before strip_conversational_fillers which collapses \n to space.
    raw_text = user_input.strip()

    # 1. Strong boundaries: newlines (user explicitly pressed Enter)
    nl_segments = [s.strip() for s in raw_text.split('\n') if s.strip()]
    if len(nl_segments) > 1:
        merged = _merge_multiline_results(nl_segments, ctx=ctx)
        if merged is not None:
            return merged

    # 2. Period boundaries: "two teas one with oat milk one without. two bagels"
    period_segments = re.split(r'\.\s+', raw_text)
    period_segments = [s.strip().rstrip('.') for s in period_segments if s.strip()]
    if len(period_segments) > 1:
        merged = _merge_multiline_results(
            period_segments, ctx=ctx, require_all_produce_items=True,
        )
        if merged is not None:
            return merged

    # Strip greetings/fillers early so ALL paths get clean text
    user_input = strip_conversational_fillers(raw_text)

    # 3. Comma boundaries (weak — commas also separate modifiers within one item,
    #    so only use the split if every segment independently produces items)
    comma_segments = [s.strip() for s in user_input.split(', ') if s.strip()]
    if len(comma_segments) > 1:
        merged = _merge_multiline_results(
            comma_segments, ctx=ctx, require_all_produce_items=True,
        )
        if merged is not None:
            return merged

    # Check for "make it N [item]" quantity pattern BEFORE replacement patterns
    # e.g., "make it two bagels" should duplicate the configured bagel, not replace it
    make_n_item_match = MAKE_IT_N_WITH_ITEM_PATTERN.match(user_input)
    if make_n_item_match:
        num_str = make_n_item_match.group(1).lower()
        target_qty = parse_make_it_n_quantity(num_str)
        if target_qty is not None:
            item_ref = make_n_item_match.group(2).strip()
            additional = target_qty - 1
            logger.info(
                "Quantity-with-item detected early, target=%d, item_ref='%s', adding %d more",
                target_qty, item_ref, additional,
            )
            return OpenInputResponse(
                duplicate_last_item=additional,
                duplicate_by_reference=item_ref,
            )

    # Check for replacement patterns FIRST, before configurable item parsing
    # This ensures "No, I said plain bagel" triggers replacement, not a new item
    replace_match = REPLACE_ITEM_PATTERN.match(user_input)
    if replace_match:
        replacement_item = _extract_replacement_item(replace_match)
        if replacement_item:
            logger.info("Replacement pattern detected early, item='%s'", replacement_item)

            # Parse the replacement item
            parsed_replacement = parse_open_input_deterministic(
                replacement_item,
                ctx=ctx,
            )
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    # Check if input likely contains multiple items
    input_lower = user_input.lower()
    # Clean up compound phrases that contain "and" but aren't multi-item orders
    # These are loaded from database (menu item names/aliases with "and")
    # Order matters: longer phrases first to match properly
    cleaned = input_lower
    compound_phrases = menu_cache.get_compound_phrases()
    for phrase in sorted(compound_phrases, key=len, reverse=True):
        cleaned = cleaned.replace(phrase, "")

    # Check for repeated quantity patterns (e.g., "2 plain bagels 2 everything bagels")
    # This handles space-separated items without "and" or commas
    quantity_pattern = re.compile(
        rf'(?:^|\s)(\d+|{QTY_WORDS_RE})\s+\w+',
        re.IGNORECASE
    )
    quantity_matches = quantity_pattern.findall(cleaned)
    has_repeated_quantities = len(quantity_matches) >= 2

    # If "and" or comma still appears, it might be multi-item OR a single item with modifiers
    # Also try multi-item parsing if we detect repeated quantity patterns
    # Try multi-item parsing first - the multi-item parser has built-in logic to detect
    # modifier chains ("bagel with butter and cream cheese") and will return None for those.
    if " and " in cleaned or ", " in cleaned or " with " in cleaned or has_repeated_quantities:
        logger.info("Potential multi-item detected, trying multi-item parse: %s", user_input[:50])

        # If we detected repeated quantities without commas, normalize by inserting commas
        # e.g., "2 plain bagels 2 everything bagels" -> "2 plain bagels, 2 everything bagels"
        # BUT: skip if this looks like an inline attribute spec pattern
        # e.g., "2 bagels 1 everything 1 plain" should NOT be split - it's 2 bagels with inline specs
        parse_input = user_input
        if has_repeated_quantities and ", " not in input_lower and " and " not in cleaned:
            # Check if this is an inline attribute spec pattern before inserting commas
            if not _is_inline_attribute_spec_pattern(input_lower):
                # Build trigger set from cache for boundary detection
                all_trigger_flat = menu_cache.get_all_triggers_flat()

                qty_words = rf'\d+|{QTY_WORDS_RE}'

                def _comma_if_trigger(m: re.Match) -> str:
                    word = m.group(1).lower()
                    if contains_word_or_singular(word, all_trigger_flat):
                        return f"{m.group(1)}, {m.group(2)}"
                    return m.group(0)

                parse_input = re.sub(
                    rf'(\w+)\s+({qty_words})(?=\s+\w)',
                    _comma_if_trigger,
                    user_input,
                    flags=re.IGNORECASE,
                )
                if parse_input != user_input:
                    logger.info("Normalized repeated quantities: %s", parse_input[:60])
            else:
                logger.info("Detected inline attribute spec pattern, skipping comma: %s", input_lower[:60])

        # Try split-quantity FIRST (e.g., "two bagels one with lox one with cream cheese")
        # Mirrors priority in _try_parse_new_items() (lines 722-734).
        split_qty_result = _parse_split_quantity_items(parse_input)
        if split_qty_result is not None:
            logger.info("Parsed split-quantity order: %s", user_input[:50])
            return split_qty_result

        result = _parse_multi_item_order(parse_input)
        if result is not None:
            logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
            return result
        # Fall through to configurable item if multi-item parse fails
        logger.info("Multi-item parse failed, trying configurable item: %s", user_input[:50])

        # Try configurable item patterns (bagels, coffees, etc.)
        # e.g., "plain bagel with Egg Whites, Swiss, and Spinach", "large iced latte"
        logger.info("Trying configurable item pattern: %s", user_input[:50])
        result = _parse_configurable_item(user_input)
        if result is not None:
            logger.info("Parsed configurable item: %s", user_input[:50])
            return result

    # Try deterministic parsing for single-item orders
    result = parse_open_input_deterministic(
        user_input,
        ctx=ctx,
    )
    if result is not None:
        logger.info("Parsed deterministically: %s", user_input[:50])
        return result

    # No LLM fallback - return unclear response
    logger.info("Unable to parse deterministically, returning unclear: %s", user_input[:50])
    return OpenInputResponse(unclear=True)
