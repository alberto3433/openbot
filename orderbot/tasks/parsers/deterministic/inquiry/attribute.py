"""Attribute inquiry parsing.

Handles queries about attribute options like "what bagel types do you have?"
These should return attribute values (bread options), not menu items.
"""

import logging

from orderbot.cache import menu_cache
from orderbot.cache.base import singularize

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text
from ...inquiry_patterns import ATTRIBUTE_INQUIRY_PATTERNS

logger = logging.getLogger(__name__)


def parse_attribute_inquiry(text: str) -> OpenInputResponse | None:
    """Parse attribute inquiry questions like 'what bagel types do you have?'

    These patterns capture:
    1. An item type reference (e.g., "bagel", "coffee")
    2. A signal word (e.g., "types", "flavors", "sizes", "options")

    The combination determines which attribute's options to show.

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with asks_attribute_options=True if matched,
        None if not an attribute inquiry.
    """
    text_lower = text.lower().strip()

    for pattern, item_group, signal_group in ATTRIBUTE_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = None
            signal_text = None

            # Extract item type reference from match
            if item_group > 0:
                try:
                    item_text = match.group(item_group).strip()
                    item_text = clean_extracted_text(item_text)
                except (IndexError, AttributeError):
                    pass

            # Extract signal word from match
            if signal_group > 0:
                try:
                    signal_text = match.group(signal_group).strip()
                    signal_text = clean_extracted_text(signal_text)
                except (IndexError, AttributeError):
                    pass

            # Resolve item type from text
            item_type_slug = _resolve_item_type(item_text) if item_text else None

            # Normalize signal to singular
            signal_normalized = singularize(signal_text) if signal_text else None

            # Need either a resolved item type OR a standalone signal word
            if item_type_slug or signal_normalized in ("size", "temperature"):
                logger.info(
                    "ATTRIBUTE INQUIRY: '%s' -> item_type=%s, signal=%s",
                    text[:50], item_type_slug, signal_normalized
                )
                return OpenInputResponse(
                    asks_attribute_options=True,
                    attribute_query_item_type=item_type_slug,
                    attribute_query_signal=signal_normalized,
                )

    return None


def _resolve_item_type(text: str) -> str | None:
    """Resolve user text to an item type slug.

    Args:
        text: Text that might reference an item type (e.g., "bagel", "bagels", "coffee")

    Returns:
        Item type slug if found, None otherwise.
    """
    if not text:
        return None

    text_lower = text.lower().strip()

    # Try singular form
    text_singular = singularize(text_lower)

    # 1. Check category keyword mapping (e.g., "bagel" -> {"slug": "bagel"})
    category_info = menu_cache.get_category_keyword_mapping(text_lower)
    if not category_info:
        category_info = menu_cache.get_category_keyword_mapping(text_singular)
    if category_info:
        return category_info.get("slug")

    # 2. Check if it's a trigger for any item type
    all_triggers = menu_cache.get_item_type_triggers()
    for item_type_slug, triggers in all_triggers.items():
        if text_lower in triggers or text_singular in triggers:
            return item_type_slug

    # 3. Check configurable item types directly
    all_item_type_slugs = menu_cache.get_configurable_item_types()
    if text_lower in all_item_type_slugs:
        return text_lower
    if text_singular in all_item_type_slugs:
        return text_singular

    return None
