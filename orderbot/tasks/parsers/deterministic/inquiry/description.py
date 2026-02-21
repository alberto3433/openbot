"""Item description inquiry parsing."""

import logging
import re

from orderbot.cache import menu_cache

from ....schemas import OpenInputResponse
from ....utils.text import normalize_text
from ...constants import clean_extracted_text
from ...inquiry_patterns import ITEM_DESCRIPTION_PATTERNS

logger = logging.getLogger(__name__)


# Module-level cache for the item type suffix pattern
_ITEM_TYPE_SUFFIX_PATTERN: re.Pattern | None = None


def _get_item_type_suffix_pattern() -> re.Pattern:
    """Build regex pattern to strip item type suffixes from item names.

    Uses item type slugs from database to create pattern like:
    r'\\s+(bagel|sandwich|omelette|...)$'

    Returns:
        Compiled regex pattern for stripping item type suffixes.
    """
    global _ITEM_TYPE_SUFFIX_PATTERN
    if _ITEM_TYPE_SUFFIX_PATTERN is not None:
        return _ITEM_TYPE_SUFFIX_PATTERN

    # Get all item type slugs from database
    slugs = menu_cache.get_all_item_type_slugs()
    if not slugs:
        # Fallback to empty pattern if no slugs loaded
        _ITEM_TYPE_SUFFIX_PATTERN = re.compile(r'$^')  # Never matches
        return _ITEM_TYPE_SUFFIX_PATTERN

    # Convert underscored slugs to space-separated words (e.g., "egg_sandwich" -> "egg sandwich")
    # and include both forms
    suffix_terms = set()
    for slug in slugs:
        suffix_terms.add(slug.replace("_", " "))
        suffix_terms.add(slug)

    # Sort by length (longest first) for proper matching
    sorted_terms = sorted(suffix_terms, key=len, reverse=True)
    pattern_str = r'\s+(' + '|'.join(re.escape(term) for term in sorted_terms) + r')$'
    _ITEM_TYPE_SUFFIX_PATTERN = re.compile(pattern_str, re.IGNORECASE)
    return _ITEM_TYPE_SUFFIX_PATTERN


def _try_strip_item_type_suffix(item_name: str) -> str:
    """Try to strip item type suffix if the result is still a valid menu item.

    Only strips the suffix if the stripped result can be resolved to a menu item.
    This prevents "chipotle omelette" from becoming just "chipotle" (invalid),
    while allowing "turkey sandwich" to become "turkey" (if "turkey" is an alias).

    Args:
        item_name: The item name to potentially strip

    Returns:
        The stripped name if it resolves to a menu item, otherwise the original name.
    """
    suffix_pattern = _get_item_type_suffix_pattern()
    stripped = suffix_pattern.sub('', item_name).strip()

    # If nothing was stripped, return original
    if stripped == item_name or not stripped:
        return item_name

    # Only use stripped version if it resolves to a known menu item
    resolved = menu_cache.resolve_menu_item_alias(stripped)
    if resolved:
        return stripped

    # Stripped version not recognized - keep original
    return item_name


def parse_item_description_inquiry(text: str) -> OpenInputResponse | None:
    """Parse item description questions."""
    text_lower = normalize_text(text)

    if any(word in text_lower for word in ["my cart", "my order", "the cart", "the order"]):
        return None

    for pattern in ITEM_DESCRIPTION_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_name = match.group(1).strip()
            item_name = clean_extracted_text(item_name)
            # Try stripping item type suffix (e.g., "turkey sandwich" -> "turkey")
            # Only strips if the result resolves to a known menu item
            item_name = _try_strip_item_type_suffix(item_name)
            if item_name:
                logger.info("ITEM DESCRIPTION INQUIRY: '%s' -> item='%s'", text[:50], item_name)
                return OpenInputResponse(
                    asks_item_description=True,
                    item_description_query=item_name,
                )

    return None
