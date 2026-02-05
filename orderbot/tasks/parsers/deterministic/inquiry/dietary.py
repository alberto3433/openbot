"""Dietary and allergen inquiry parsing.

Handles parsing of:
- Dietary options inquiries ("do you have vegan options?")
- Specific item dietary inquiries ("is the classic gluten-free?")
- Allergen inquiries ("does X contain nuts?")
- Allergen-free options inquiries ("anything nut-free?")
- Availability inquiries ("do you have X in stock?")
- Customization inquiries ("can I customize X?")
"""

import logging

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text
from ...inquiry_patterns import (
    DIETARY_PROPERTIES,
    ALLERGEN_PROPERTIES,
    DIETARY_CATEGORY_PATTERNS,
    DIETARY_OPTIONS_PATTERNS,
    DIETARY_ITEM_PATTERNS,
    ALLERGEN_ITEM_PATTERNS,
    ALLERGEN_FREE_OPTIONS_PATTERNS,
    AVAILABILITY_PATTERNS,
    CUSTOMIZATION_INQUIRY_PATTERNS,
)

logger = logging.getLogger(__name__)


def _normalize_dietary_property(term: str) -> str | None:
    """Normalize a dietary term to its database column name.

    Args:
        term: User term like "vegan", "gluten-free", "gf"

    Returns:
        Database column name like "is_vegan", "is_gluten_free", or None
    """
    term_lower = term.lower().strip().replace("-", " ").replace("_", " ")
    # Normalize multiple spaces
    term_lower = " ".join(term_lower.split())
    return DIETARY_PROPERTIES.get(term_lower)


def _normalize_allergen_property(term: str) -> str | None:
    """Normalize an allergen term to its database column name.

    Args:
        term: User term like "nuts", "eggs", "fish"

    Returns:
        Database column name like "contains_nuts", "contains_eggs", or None
    """
    term_lower = term.lower().strip().replace("-", " ").replace("_", " ")
    # Normalize multiple spaces
    term_lower = " ".join(term_lower.split())
    return ALLERGEN_PROPERTIES.get(term_lower)


def parse_dietary_category_inquiry(text: str) -> OpenInputResponse | None:
    """Parse combined dietary + category inquiries.

    Examples:
        - "what vegan drinks do you have?" -> dietary_query_type="is_vegan", dietary_query_category="drinks"
        - "any gluten-free bagels?" -> dietary_query_type="is_gluten_free", dietary_query_category="bagels"
        - "vegetarian sandwiches?" -> dietary_query_type="is_vegetarian", dietary_query_category="sandwiches"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with dietary flags and category set, or None if not a match
    """
    text_lower = text.lower().strip()

    for pattern in DIETARY_CATEGORY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            # Group 1 is dietary term, Group 2 is category term
            dietary_term = match.group(1).strip()
            category_term = match.group(2).strip()

            dietary_property = _normalize_dietary_property(dietary_term)

            # Skip if category term is a generic "options/items/menu" word
            # (those should fall through to DIETARY_OPTIONS_PATTERNS)
            generic_terms = {"options", "option", "items", "item", "menu", "choices", "choice", "food"}
            if category_term in generic_terms:
                continue

            if dietary_property and category_term:
                logger.info(
                    "DIETARY CATEGORY INQUIRY: '%s' -> dietary_type=%s, category=%s",
                    text[:50], dietary_property, category_term
                )
                return OpenInputResponse(
                    asks_dietary_options=True,
                    dietary_query_type=dietary_property,
                    dietary_query_category=category_term,
                )

    return None


def parse_dietary_options_inquiry(text: str) -> OpenInputResponse | None:
    """Parse general dietary options inquiries.

    Examples:
        - "do you have vegan options?" -> asks_dietary_options=True, dietary_query_type="is_vegan"
        - "what's gluten-free?" -> asks_dietary_options=True, dietary_query_type="is_gluten_free"
        - "any vegetarian items?" -> asks_dietary_options=True, dietary_query_type="is_vegetarian"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with dietary flags set, or None if not a dietary options inquiry
    """
    text_lower = text.lower().strip()

    for pattern in DIETARY_OPTIONS_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            # Extract the dietary term from the match
            dietary_term = match.group(1).strip()
            dietary_property = _normalize_dietary_property(dietary_term)

            if dietary_property:
                logger.info(
                    "DIETARY OPTIONS INQUIRY: '%s' -> dietary_type=%s",
                    text[:50], dietary_property
                )
                return OpenInputResponse(
                    asks_dietary_options=True,
                    dietary_query_type=dietary_property,
                )

    return None


def parse_dietary_item_inquiry(text: str) -> OpenInputResponse | None:
    """Parse specific item dietary inquiries.

    Examples:
        - "is the classic vegan?" -> dietary_query_item="the classic", dietary_query_type="is_vegan"
        - "is the BLT gluten-free?" -> dietary_query_item="the blt", dietary_query_type="is_gluten_free"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with dietary flags set, or None if not a dietary item inquiry
    """
    text_lower = text.lower().strip()

    for pattern in DIETARY_ITEM_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            # Group 1 is the item, Group 2 is the dietary term
            item_text = match.group(1).strip()
            dietary_term = match.group(2).strip()

            item_text = clean_extracted_text(item_text)
            dietary_property = _normalize_dietary_property(dietary_term)

            if item_text and dietary_property:
                logger.info(
                    "DIETARY ITEM INQUIRY: '%s' -> item='%s', dietary_type=%s",
                    text[:50], item_text, dietary_property
                )
                return OpenInputResponse(
                    asks_dietary_options=True,
                    dietary_query_item=item_text,
                    dietary_query_type=dietary_property,
                )

    return None


def parse_allergen_inquiry(text: str) -> OpenInputResponse | None:
    """Parse allergen inquiries for specific items.

    Examples:
        - "does the classic contain nuts?" -> allergen_query_item="the classic", allergen_query_type="contains_nuts"
        - "is there fish in the BLT?" -> allergen_query_item="the blt", allergen_query_type="contains_fish"
        - "what allergens are in the classic?" -> allergen_query_item="the classic", allergen_query_type=None

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with allergen flags set, or None if not an allergen inquiry
    """
    text_lower = text.lower().strip()

    for pattern in ALLERGEN_ITEM_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            groups = match.groups()

            # Pattern order varies - detect based on content
            item_text = None
            allergen_term = None

            for group in groups:
                if not group:
                    continue
                group_lower = group.lower().strip()

                # Check if this group is an allergen term
                if _normalize_allergen_property(group_lower) or group_lower in ("allergens", "allergen"):
                    allergen_term = group_lower
                else:
                    # Otherwise it's the item
                    item_text = group_lower

            if item_text:
                item_text = clean_extracted_text(item_text)

            # Normalize allergen - None means "all allergens"
            allergen_property = None
            if allergen_term and allergen_term not in ("allergens", "allergen"):
                allergen_property = _normalize_allergen_property(allergen_term)

            if item_text:
                logger.info(
                    "ALLERGEN INQUIRY: '%s' -> item='%s', allergen_type=%s",
                    text[:50], item_text, allergen_property
                )
                return OpenInputResponse(
                    asks_allergen_info=True,
                    allergen_query_item=item_text,
                    allergen_query_type=allergen_property,
                )

    return None


def parse_allergen_free_options_inquiry(text: str) -> OpenInputResponse | None:
    """Parse inquiries for allergen-free options.

    Examples:
        - "anything nut-free?" -> asks_allergen_free_options=True, allergen_query_type="contains_nuts"
        - "options without eggs?" -> asks_allergen_free_options=True, allergen_query_type="contains_eggs"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with allergen-free flags set, or None if not a match
    """
    text_lower = text.lower().strip()

    for pattern in ALLERGEN_FREE_OPTIONS_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            allergen_term = match.group(1).strip()
            allergen_property = _normalize_allergen_property(allergen_term)

            if allergen_property:
                logger.info(
                    "ALLERGEN-FREE OPTIONS INQUIRY: '%s' -> allergen_type=%s",
                    text[:50], allergen_property
                )
                return OpenInputResponse(
                    asks_allergen_free_options=True,
                    allergen_query_type=allergen_property,
                )

    return None


def parse_availability_inquiry(text: str) -> OpenInputResponse | None:
    """Parse availability/stock inquiries.

    Examples:
        - "do you have everything bagels in stock?" -> availability_query_item="everything bagels"
        - "are you out of cream cheese?" -> availability_query_item="cream cheese"
        - "is the special still available?" -> availability_query_item="the special"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with availability flags set, or None if not a match
    """
    text_lower = text.lower().strip()

    for pattern in AVAILABILITY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = match.group(1).strip()
            item_text = clean_extracted_text(item_text)

            if item_text:
                logger.info(
                    "AVAILABILITY INQUIRY: '%s' -> item='%s'",
                    text[:50], item_text
                )
                return OpenInputResponse(
                    asks_availability=True,
                    availability_query_item=item_text,
                )

    return None


def parse_customization_inquiry(text: str) -> OpenInputResponse | None:
    """Parse customization inquiries.

    Examples:
        - "can I customize the classic?" -> customization_query_item="the classic"
        - "is the sandwich customizable?" -> customization_query_item="the sandwich"
        - "what can I change on the BLT?" -> customization_query_item="the blt"

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with customization flags set, or None if not a match
    """
    text_lower = text.lower().strip()

    for pattern in CUSTOMIZATION_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = match.group(1).strip()
            item_text = clean_extracted_text(item_text)

            if item_text:
                logger.info(
                    "CUSTOMIZATION INQUIRY: '%s' -> item='%s'",
                    text[:50], item_text
                )
                return OpenInputResponse(
                    asks_customization_options=True,
                    customization_query_item=item_text,
                )

    return None


def parse_dietary_inquiry(text: str) -> OpenInputResponse | None:
    """Main entry point for all dietary/allergen/availability/customization inquiries.

    Tries each parser in order and returns the first match.

    Args:
        text: User input text to parse

    Returns:
        OpenInputResponse with appropriate flags set, or None if no match
    """
    # Try combined dietary + category first (most specific pattern)
    # e.g., "what vegan drinks do you have?"
    result = parse_dietary_category_inquiry(text)
    if result:
        return result

    # Try dietary options (general "do you have vegan options?")
    result = parse_dietary_options_inquiry(text)
    if result:
        return result

    # Try specific item dietary inquiry ("is the classic vegan?")
    result = parse_dietary_item_inquiry(text)
    if result:
        return result

    # Try allergen inquiry for specific items ("does X contain nuts?")
    result = parse_allergen_inquiry(text)
    if result:
        return result

    # Try allergen-free options inquiry ("anything nut-free?")
    result = parse_allergen_free_options_inquiry(text)
    if result:
        return result

    # Try availability inquiry ("do you have X in stock?")
    result = parse_availability_inquiry(text)
    if result:
        return result

    # Try customization inquiry ("can I customize X?")
    result = parse_customization_inquiry(text)
    if result:
        return result

    return None
