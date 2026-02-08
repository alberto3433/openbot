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

    Args:
        text: Lowercase text to parse
        options: List of option dicts for matching
        attr_slug: The attribute slug these specs belong to
        option_matcher: OptionMatcher instance
        input_normalizer: InputNormalizer instance

    Returns:
        List of parsed specs with attr_slug, attr_value, quantity, display_name
    """
    specs = []

    # Split by common delimiters:
    # - " and " for "1 everything and 1 plain"
    # - ", " for "1 everything, 1 plain"
    # - Transition from word to digit: "1 everything 1 plain"
    parts = re.split(r'\s+and\s+|\s*,\s*|(?<=\w)\s+(?=\d)', text)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract quantity and option text
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
