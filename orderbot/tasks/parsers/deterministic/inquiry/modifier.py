"""Modifier inquiry parsing."""

import logging

from ....schemas import OpenInputResponse
from ....utils.text import normalize_text
from ...constants import clean_extracted_text
from ...inquiry_patterns import MODIFIER_INQUIRY_PATTERNS

logger = logging.getLogger(__name__)


def parse_modifier_inquiry(
    text: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
) -> OpenInputResponse | None:
    """Parse modifier/add-on inquiry questions.

    Args:
        text: User input text to parse
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
            If None, modifier category detection is skipped but item detection still works.
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
            If None, item detection is skipped.
    """
    text_lower = normalize_text(text)
    keywords = modifier_category_keywords or {}
    item_keywords = modifier_item_keywords or {}

    for pattern, item_group, category_group in MODIFIER_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = None
            category_text = None

            # Extract item from match if present
            if item_group > 0:
                try:
                    item_text = match.group(item_group).strip()
                    item_text = clean_extracted_text(item_text)
                except (IndexError, AttributeError):
                    pass

            # Extract category from match if present
            if category_group > 0:
                try:
                    category_text = match.group(category_group).strip()
                    category_text = clean_extracted_text(category_text)
                except (IndexError, AttributeError):
                    pass

            # Normalize item type
            item_type = None
            if item_text:
                item_type = item_keywords.get(item_text.lower())
                # If item_text doesn't match known items, it might be a category
                if not item_type and item_text.lower() in keywords:
                    category_text = item_text
                    item_text = None

            # Normalize category
            category = None
            if category_text:
                category = keywords.get(category_text.lower())

            # Only return if we have a valid item or category
            if item_type or category:
                logger.info(
                    "MODIFIER INQUIRY: '%s' -> item=%s, category=%s",
                    text[:50], item_type, category
                )
                return OpenInputResponse(
                    asks_modifier_options=True,
                    modifier_query_item=item_type,
                    modifier_query_category=category,
                )

    return None
