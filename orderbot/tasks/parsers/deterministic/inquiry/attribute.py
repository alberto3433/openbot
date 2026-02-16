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


def _resolve_attribute_slug(text: str) -> str | None:
    """Check if text is a valid attribute slug with options.

    Args:
        text: Text that might be an attribute slug (e.g., "bread", "size")

    Returns:
        Attribute slug if it has global options, None otherwise.
    """
    text_lower = text.lower().strip()
    text_singular = singularize(text_lower)

    # Check if it's a global attribute with options
    if menu_cache.get_global_attribute_options(text_lower):
        return text_lower
    if menu_cache.get_global_attribute_options(text_singular):
        return text_singular
    return None


def _resolve_compound_attribute(item_text: str, signal_text: str) -> str | None:
    """Check if item + signal forms a valid compound attribute slug.

    Handles queries like "what tea flavors?" where "tea_flavor" is a global attribute.

    Args:
        item_text: The item part (e.g., "tea", "chai", "syrup")
        signal_text: The signal part (e.g., "flavors", "types", "options")

    Returns:
        Compound attribute slug if it has global options, None otherwise.
    """
    if not item_text or not signal_text:
        return None

    item_lower = item_text.lower().strip()
    signal_lower = signal_text.lower().strip()
    signal_singular = singularize(signal_lower)

    # Try {item}_{signal} patterns (e.g., "tea_flavor", "chai_flavor", "syrup_flavor")
    candidates = [
        f"{item_lower}_{signal_singular}",  # tea_flavor
        f"{item_lower}_{signal_lower}",     # tea_flavors (unlikely but check)
    ]

    for candidate in candidates:
        if menu_cache.get_global_attribute_options(candidate):
            return candidate

    return None


def _resolve_ingredient_category(text: str) -> str | None:
    """Check if text matches an ingredient category.

    This enables queries like "what sweeteners do you have?" to route
    to the modifier inquiry handler instead of falling through to
    the generic menu query.

    Args:
        text: Text that might be an ingredient category (e.g., "sweetener", "syrup", "milk")

    Returns:
        Ingredient category slug if found, None otherwise.
    """
    text_lower = text.lower().strip()
    text_singular = singularize(text_lower)

    # Get all ingredient categories from cache
    all_categories = menu_cache.get_all_ingredient_categories()

    # Check exact match (e.g., "syrup" -> "syrup")
    if text_lower in all_categories:
        return text_lower
    if text_singular in all_categories:
        return text_singular

    # Check with common suffixes removed (e.g., "sweeteners" -> "sweetener")
    # The singularize function handles most cases
    return None


def _signal_resolves_to_attribute(item_type: str, signal: str) -> bool:
    """Check if a signal word maps to a valid attribute for the given item_type.

    This validates that "what kind of X" is actually asking about an attribute
    of X, not just asking for X items. For example:
    - "what kind of bagel" → True (bagel has "bread" attribute for "kind")
    - "what kind of drink" → False (drink has no attribute for "kind")

    Uses data-driven lookup via menu_cache.get_attribute_for_inquiry_keyword()
    which reads from the attribute_inquiry_keywords database table.

    Args:
        item_type: Item type slug (e.g., "bagel", "drink")
        signal: Signal word (e.g., "kind", "type", "size")

    Returns:
        True if signal maps to an attribute for this item_type, False otherwise.
    """
    if not item_type or not signal:
        return False

    signal_lower = signal.lower()
    attrs = menu_cache.get_item_type_attributes(item_type)

    # If signal is itself a valid global attribute slug, check if item_type has it
    if menu_cache.get_global_attribute_options(signal_lower):
        return signal_lower in attrs

    # Try data-driven lookup from attribute_inquiry_keywords table
    if hasattr(menu_cache, 'get_attribute_for_inquiry_keyword'):
        attr_slug = menu_cache.get_attribute_for_inquiry_keyword(signal_lower, item_type)
        if attr_slug:
            # Verify the item_type actually has this attribute
            return attr_slug in attrs

    # Check if signal directly matches an attribute for this item_type
    if signal_lower in attrs:
        return True

    return False


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

            # FIRST: Check for compound attribute slugs like "tea_flavor", "chai_flavor"
            # This handles "what tea flavors do you have?" where tea_flavor is a global attribute
            if item_text and signal_text:
                compound_attr = _resolve_compound_attribute(item_text, signal_text)
                if compound_attr:
                    logger.info(
                        "ATTRIBUTE INQUIRY (compound): '%s' -> attribute=%s",
                        text[:50], compound_attr
                    )
                    return OpenInputResponse(
                        asks_attribute_options=True,
                        attribute_query_item_type=None,
                        attribute_query_signal=compound_attr,
                    )

            # Resolve item type from text
            item_type_slug = _resolve_item_type(item_text) if item_text else None

            # If not an item_type, check if it's an attribute slug with options
            attr_slug_from_text = None
            if not item_type_slug and item_text:
                attr_slug_from_text = _resolve_attribute_slug(item_text)

            # If not an item_type or attribute, check if it's an ingredient category
            # This handles queries like "what sweeteners do you have?"
            ingredient_category = None
            if not item_type_slug and not attr_slug_from_text and item_text:
                ingredient_category = _resolve_ingredient_category(item_text)
                if ingredient_category:
                    logger.info(
                        "MODIFIER INQUIRY (from attribute parser): '%s' -> category=%s",
                        text[:50], ingredient_category
                    )
                    return OpenInputResponse(
                        asks_modifier_options=True,
                        modifier_query_item=None,
                        modifier_query_category=ingredient_category,
                    )

            # Normalize signal to singular
            signal_normalized = singularize(signal_text) if signal_text else None

            # Validate: if we have an item_type, the signal must map to a real attribute
            # Otherwise "what kind of drinks" would incorrectly be treated as attribute inquiry
            if item_type_slug and signal_normalized:
                if not _signal_resolves_to_attribute(item_type_slug, signal_normalized):
                    # Signal doesn't directly map to an attribute for this item_type.
                    # Check if item type has askable attributes — if so, let the handler's
                    # _get_primary_attribute() fallback resolve it (e.g., "flavor" → "bread" for bagels).
                    attrs = menu_cache.get_item_type_attributes(item_type_slug)
                    has_askable = any(a.get("ask_in_conversation") for a in attrs.values())
                    if not has_askable:
                        # No configurable attributes → let menu_query handle it
                        logger.debug(
                            "ATTRIBUTE INQUIRY REJECTED: '%s' - signal '%s' doesn't map to attribute for '%s'",
                            text[:50], signal_normalized, item_type_slug
                        )
                        continue  # Try next pattern or fall through
                    logger.debug(
                        "ATTRIBUTE INQUIRY ALLOWED (has askable attrs): '%s' - signal '%s' for '%s'",
                        text[:50], signal_normalized, item_type_slug
                    )

            # Need either a resolved item type, attribute slug, OR a standalone signal word
            if item_type_slug or attr_slug_from_text or signal_normalized in ("size", "temperature"):
                # If we found an attribute slug in the item_text, use it as the signal
                final_signal = attr_slug_from_text or signal_normalized
                logger.info(
                    "ATTRIBUTE INQUIRY: '%s' -> item_type=%s, signal=%s",
                    text[:50], item_type_slug, final_signal
                )
                return OpenInputResponse(
                    asks_attribute_options=True,
                    attribute_query_item_type=item_type_slug,
                    attribute_query_signal=final_signal,
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
