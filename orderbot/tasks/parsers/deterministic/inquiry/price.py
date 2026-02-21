"""Price inquiry parsing."""

import logging
import re

from orderbot.cache import menu_cache

from ....schemas import OpenInputResponse
from ....utils.text import normalize_text
from ...constants import clean_extracted_text
from ...inquiry_patterns import PRICE_INQUIRY_PATTERNS

logger = logging.getLogger(__name__)


def _try_category_price_response(item_text: str, original_text: str) -> OpenInputResponse | None:
    """Try to match item_text to a category and return price inquiry response.

    Args:
        item_text: The extracted item text to look up
        original_text: Original user text for logging

    Returns:
        OpenInputResponse if category match found, None otherwise
    """
    category_info = menu_cache.get_category_keyword_mapping(item_text)
    if category_info:
        menu_type = category_info["slug"]
        logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", original_text[:50], menu_type)
        return OpenInputResponse(
            asks_about_price=True,
            menu_query=True,
            menu_query_type=menu_type,
        )
    return None


def parse_price_inquiry(text: str) -> OpenInputResponse | None:
    """Parse price inquiry questions."""
    text_lower = normalize_text(text)

    for pattern in PRICE_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = match.group(1).strip()
            item_text = clean_extracted_text(item_text)

            logger.debug("Price inquiry detected: item_text='%s'", item_text)

            # Try category lookup on item text (and with "your" prefix stripped)
            result = _try_category_price_response(item_text, text)
            if result:
                return result

            your_match = re.match(r"your\s+(.+)", item_text)
            if your_match:
                result = _try_category_price_response(your_match.group(1).strip(), text)
                if result:
                    return result

            logger.info("PRICE INQUIRY (specific): '%s' -> price_query_item=%s", text[:50], item_text)
            return OpenInputResponse(
                asks_about_price=True,
                price_query_item=item_text,
            )

    return None
