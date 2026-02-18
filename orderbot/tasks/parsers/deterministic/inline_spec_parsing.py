"""
Inline Attribute Specification Parsing.

Handles patterns like "2 bagels 1 everything 1 plain" where the user specifies
attribute values inline with quantity. This reuses the parsing logic from
PackageInputHandler.

Key functions:
- get_primary_configurable_attribute: Gets first required single-select attribute
- parse_inline_attribute_specs: Parses "1 X 1 Y" patterns and returns structured specs
"""

import logging
import re
from typing import TYPE_CHECKING

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize
from ..quantity_utils import QTY_WORDS_RE

if TYPE_CHECKING:
    from ...utils import OptionMatcher, InputNormalizer

logger = logging.getLogger(__name__)


def get_primary_configurable_attribute(item_type_slug: str) -> dict | None:
    """Get the primary configurable attribute for an item type.

    Returns the first required single-select attribute that has options and
    asks in conversation. For bagels, this returns "bread". For other item
    types, it returns their primary distinguishing attribute.

    This is data-driven - no hardcoded attribute names.

    Args:
        item_type_slug: The item type slug (e.g., "bagel")

    Returns:
        Dict with attribute config containing:
        - slug: Attribute slug (e.g., "bread")
        - display_name: Human-readable name
        - options: List of available options
        Or None if no suitable attribute found.
    """
    attrs = menu_cache.get_item_type_attributes(item_type_slug)
    if not attrs:
        return None

    # Find first required single_select attribute with options that asks in conversation
    for attr_slug, attr_config in attrs.items():
        input_type = attr_config.get("input_type", "")
        is_required = attr_config.get("is_required", False)
        ask_in_conversation = attr_config.get("ask_in_conversation", False)
        options = attr_config.get("options", [])

        if (input_type == "single_select" and
                is_required and
                ask_in_conversation and
                options):
            return {
                "slug": attr_slug,
                "display_name": attr_config.get("display_name", attr_slug),
                "options": options,
            }

    return None


def parse_inline_attribute_specs(
    text: str,
    total_qty: int,
    item_type_slug: str,
    option_matcher: "OptionMatcher | None" = None,
    input_normalizer: "InputNormalizer | None" = None,
) -> list[dict] | None:
    """Parse inline attribute specifications from text.

    Handles patterns like "2 bagels 1 everything 1 plain" by extracting
    the "1 everything 1 plain" portion and parsing it into structured specs.

    Uses the same parsing logic as PackageInputHandler._parse_package_contents().

    Args:
        text: Text after the item name (e.g., "1 everything 1 plain")
        total_qty: Total quantity of items ordered
        item_type_slug: The item type slug
        option_matcher: Optional OptionMatcher instance (creates default if None)
        input_normalizer: Optional InputNormalizer instance (creates default if None)

    Returns:
        List of dicts, each containing:
        - attr_slug: The attribute slug (e.g., "bread")
        - attr_value: The option slug (e.g., "everything")
        - quantity: How many items with this spec
        - display_name: Human-readable option name
        Or None if:
        - No valid inline specs found
        - Specs are over-specified (sum > total_qty)
        - No primary attribute found for item type
    """
    # Get primary attribute
    primary_attr = get_primary_configurable_attribute(item_type_slug)
    if not primary_attr:
        logger.debug(
            "INLINE_SPEC: No primary attribute for type '%s'",
            item_type_slug
        )
        return None

    attr_slug = primary_attr["slug"]
    options = primary_attr["options"]

    # Create matchers if not provided
    if option_matcher is None or input_normalizer is None:
        from ...utils import OptionMatcher, InputNormalizer
        if option_matcher is None:
            option_matcher = OptionMatcher()
        if input_normalizer is None:
            input_normalizer = InputNormalizer()

    # Transform options to matcher format
    matcher_options = []
    for opt in options:
        if isinstance(opt, dict):
            matcher_options.append({
                "slug": opt.get("slug"),
                "display_name": opt.get("display_name") or opt.get("name"),
                "aliases": opt.get("aliases") or [],
            })
        else:
            matcher_options.append(opt)

    # Parse specs using the same logic as PackageInputHandler
    specs = _parse_specs(
        text.lower(),
        matcher_options,
        attr_slug,
        option_matcher,
        input_normalizer,
    )

    if not specs:
        return None

    # Calculate total specified quantity
    specified_total = sum(s["quantity"] for s in specs)

    # Validate: specs should not exceed total_qty
    if specified_total > total_qty:
        logger.debug(
            "INLINE_SPEC: Over-specified (%d > %d), ignoring specs",
            specified_total, total_qty
        )
        return None

    logger.info(
        "INLINE_SPEC: Parsed %d specs totaling %d items (of %d total): %s",
        len(specs), specified_total, total_qty,
        [(s["attr_value"], s["quantity"]) for s in specs]
    )

    return specs


def _parse_specs(
    text: str,
    options: list[dict],
    attr_slug: str,
    option_matcher: "OptionMatcher",
    input_normalizer: "InputNormalizer",
) -> list[dict]:
    """Parse quantity+option patterns from text.

    Reuses the parsing algorithm from PackageInputHandler._parse_package_contents().

    Only returns specs when at least one has an explicit quantity (digit or number
    word prefix). This distinguishes true inline specs like "1 everything 1 plain"
    from uniform attributes like "on wheat" which should apply to all items.

    Args:
        text: Lowercase text to parse
        options: List of option dicts for matching
        attr_slug: The attribute slug these specs belong to
        option_matcher: OptionMatcher instance
        input_normalizer: InputNormalizer instance

    Returns:
        List of parsed specs with attr_slug, attr_value, quantity, display_name.
        Returns empty list if no specs have explicit quantities (not an inline
        spec pattern).
    """
    from ..quantity_utils import extract_leading_quantity as extract_qty_raw

    specs = []
    any_explicit_quantity = False

    # Split by common delimiters:
    # - " and " for "1 everything and 1 plain"
    # - ", " for "1 everything, 1 plain"
    # - Transition from word to digit: "1 everything 1 plain"
    parts = re.split(r'\s+and\s+|\s*,\s*|(?<=\w)\s+(?=\d)', text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Use raw extract to detect whether quantity was explicitly stated.
        # Returns (None, text) when no leading quantity found vs (int, remaining).
        raw_qty, _ = extract_qty_raw(part)
        has_explicit_qty = raw_qty is not None

        # Extract quantity and option text (defaults None to 1)
        quantity, option_text = input_normalizer.extract_leading_quantity(part)

        if not option_text.strip():
            continue

        # Try to match the option type
        matched, partials = option_matcher.match_single(option_text.strip(), options)

        # If multiple partial matches, pick the simplest one (shortest name)
        if not matched and partials:
            partials_sorted = sorted(
                partials,
                key=lambda x: len(x.get("display_name", ""))
            )
            matched = partials_sorted[0]
            logger.debug(
                "INLINE_SPEC_PARSE: picked shortest match '%s' from %d partials",
                matched.get("slug"), len(partials),
            )

        if matched:
            if has_explicit_qty:
                any_explicit_quantity = True
            specs.append({
                "attr_slug": attr_slug,
                "attr_value": matched["slug"],
                "quantity": quantity,
                "display_name": matched.get("display_name", matched["slug"]),
            })
        else:
            # Try matching without quantity extraction
            matched2, _ = option_matcher.match_single(part, options)
            if matched2:
                specs.append({
                    "attr_slug": attr_slug,
                    "attr_value": matched2["slug"],
                    "quantity": 1,
                    "display_name": matched2.get("display_name", matched2["slug"]),
                })

    # If no specs had explicit quantities, this is not an inline spec pattern.
    # E.g., "on wheat" is a uniform attribute, not "1 wheat".
    # Return empty so the caller falls through to pipeline.extract_attributes().
    if specs and not any_explicit_quantity:
        logger.debug(
            "INLINE_SPEC_PARSE: rejecting specs - no explicit quantities found "
            "(uniform attribute pattern, not inline spec): %s",
            [(s["attr_value"], s["quantity"]) for s in specs]
        )
        return []

    return specs


def extract_text_after_item_match(
    text: str,
    item_triggers: list[str],
) -> str | None:
    """Extract text appearing after the item trigger word(s).

    Used to find the portion of text that might contain inline specs.
    E.g., "2 bagels 1 everything 1 plain" -> "1 everything 1 plain"

    Args:
        text: Full user input text
        item_triggers: List of trigger words to look for (e.g., ["bagel", "bagels"])

    Returns:
        Text after the matched trigger, or None if no match found.
    """
    text_lower = text.lower()

    # Try each trigger, prefer longer matches
    sorted_triggers = sorted(item_triggers, key=len, reverse=True)

    for trigger in sorted_triggers:
        # Match trigger with optional plural 's'
        pattern = rf'\b{re.escape(trigger.lower())}s?\b'
        match = re.search(pattern, text_lower)
        if match:
            after_match = text[match.end():].strip()
            if after_match:
                return after_match

    return None


def _is_inline_attribute_spec_pattern(text: str) -> bool:
    """Check if text is an inline attribute specification pattern.

    Inline spec pattern: "N items N attr1 N attr2" where:
    - "N items" identifies the item type (e.g., "2 bagels")
    - "N attr1 N attr2" are quantity+attribute pairs (e.g., "1 everything 1 plain")

    This differs from multi-item orders like "2 bagels 2 coffees" where
    each quantity is followed by a different item type.

    Args:
        text: Lowercase user input

    Returns:
        True if this is an inline spec pattern that should NOT be split
        by comma insertion.
    """
    from .item_parsing import _detect_configurable_item_type

    # Pattern: qty word qty word qty word...
    # e.g., "2 bagels 1 everything 1 plain"
    qty_word_pattern = rf'(\d+|{QTY_WORDS_RE})\s+(\w+)'
    raw_matches = list(re.finditer(qty_word_pattern, text, re.IGNORECASE))

    if len(raw_matches) < 2:
        return False  # Not enough qty+word pairs

    matches = [(m.group(1), m.group(2)) for m in raw_matches]

    # First match should identify the item type
    first_word = matches[0][1].lower()

    # Detect item type from the first qty+word pair
    first_phrase = f"{matches[0][0]} {first_word}"
    detected_type, _ = _detect_configurable_item_type(first_phrase)

    if not detected_type:
        return False  # Couldn't identify item type

    # Get attribute options for this item type
    attrs = menu_cache.get_item_type_attributes(detected_type)
    if not attrs:
        return False

    # Build set of all attribute option words (slugs, display names, aliases)
    attr_option_words: set[str] = set()
    for attr_slug, attr_info in attrs.items():
        options = attr_info.get("options", [])
        for opt in options:
            if isinstance(opt, dict):
                slug = opt.get("slug", "")
                display_name = opt.get("display_name", "")
                aliases = opt.get("aliases", [])

                if slug:
                    attr_option_words.add(slug.lower())
                    for part in slug.lower().split("_"):
                        if len(part) >= 3:
                            attr_option_words.add(part)
                if display_name:
                    attr_option_words.add(display_name.lower())
                    for part in display_name.lower().split():
                        if len(part) >= 3:
                            attr_option_words.add(part)
                for alias in aliases:
                    attr_option_words.add(alias.lower())
                    for part in alias.lower().split():
                        if len(part) >= 3:
                            attr_option_words.add(part)

    # If item type triggers appear between qty+word pairs, this is multi-item, not inline spec
    all_trigger_flat = menu_cache.get_all_triggers_flat()

    for i in range(len(raw_matches) - 1):
        gap_text = text[raw_matches[i].end():raw_matches[i + 1].start()].strip()
        if gap_text:
            for word in gap_text.lower().split():
                if word in all_trigger_flat or singularize(word) in all_trigger_flat:
                    return False

    # Check if subsequent qty+word pairs have words that are attribute options
    subsequent_words = [m[1].lower() for m in matches[1:]]
    attr_matches = [w for w in subsequent_words if w in attr_option_words]

    # If ALL subsequent words are attribute options, this is an inline spec pattern
    if len(attr_matches) == len(subsequent_words):
        logger.debug(
            "Inline spec detected: type=%s, specs=%s",
            detected_type, subsequent_words
        )
        return True

    return False
