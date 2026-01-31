"""Store info inquiry parsing."""

import logging

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text
from ...inquiry_patterns import (
    DELIVERY_ZONE_PATTERNS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
)

logger = logging.getLogger(__name__)


def parse_store_info_inquiry(text: str) -> OpenInputResponse | None:
    """Parse store info inquiries."""
    text_lower = text.lower().strip()

    for pattern in STORE_HOURS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (hours): '%s'", text[:50])
            return OpenInputResponse(asks_store_hours=True)

    for pattern in STORE_LOCATION_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (location): '%s'", text[:50])
            return OpenInputResponse(asks_store_location=True)

    for pattern in DELIVERY_ZONE_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            location_query = match.group(1).strip()
            location_query = clean_extracted_text(location_query)
            logger.info("STORE INFO INQUIRY (delivery zone): '%s' -> '%s'", text[:50], location_query)
            return OpenInputResponse(
                asks_delivery_zone=True,
                delivery_zone_query=location_query,
            )

    return None
