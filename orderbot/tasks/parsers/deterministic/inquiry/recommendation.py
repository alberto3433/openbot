"""Recommendation inquiry parsing."""

import logging
import re

from orderbot.cache.base import singularize
from orderbot.cache import menu_cache

from ....schemas import OpenInputResponse
from ...inquiry_patterns import RECOMMENDATION_GENERAL_PATTERNS, RECOMMENDATION_TERM_PATTERNS

logger = logging.getLogger(__name__)


def parse_recommendation_inquiry(text: str) -> OpenInputResponse | None:
    """Parse recommendation questions using data-driven two-tier lookup.

    1. Check general patterns (domain-agnostic) - return "general" match type
    2. Check term-extracting patterns - singularize term and do lookup:
       a. Search menu_items by partial name/alias match
       b. Fallback: Search item_types by display_name/aliases
    3. Return structured match result with menu_item_ids or item_type_slug
    """
    text_lower = text.lower().strip()

    # 1. Check general patterns first (domain-agnostic, no term extraction)
    for pattern in RECOMMENDATION_GENERAL_PATTERNS:
        if pattern.search(text_lower):
            logger.info("RECOMMENDATION INQUIRY (general): '%s'", text[:50])
            return OpenInputResponse(
                asks_recommendation=True,
                recommendation_match_type="general",
            )

    # 2. Check term-extracting patterns
    for pattern in RECOMMENDATION_TERM_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            # Extract and clean the captured term
            raw_term = match.group(1).strip()

            # Skip if term is too short or generic
            if len(raw_term) < 2 or raw_term in {"a", "an", "the", "some", "any"}:
                continue

            # Remove trailing punctuation and common words
            term = re.sub(r"[?!.,]+$", "", raw_term).strip()
            if not term:
                continue

            # Singularize the term
            term_singular = singularize(term)

            logger.info(
                "RECOMMENDATION INQUIRY (term): '%s' -> term='%s' (singular='%s')",
                text[:50], term, term_singular
            )

            # 3a. Search menu items first
            matching_items = menu_cache.search_menu_items_for_recommendation(term_singular)
            if matching_items:
                menu_item_ids = [item["id"] for item in matching_items]
                logger.info(
                    "RECOMMENDATION: Found %d menu items for '%s': %s",
                    len(menu_item_ids), term_singular, menu_item_ids[:5]
                )
                return OpenInputResponse(
                    asks_recommendation=True,
                    recommendation_match_type="menu_items",
                    recommendation_menu_item_ids=menu_item_ids,
                    recommendation_search_term=term_singular,
                )

            # 3b. Fallback: Search item types
            item_type_slug = menu_cache.search_item_type_for_recommendation(term_singular)
            if item_type_slug:
                logger.info(
                    "RECOMMENDATION: Found item type '%s' for '%s'",
                    item_type_slug, term_singular
                )
                return OpenInputResponse(
                    asks_recommendation=True,
                    recommendation_match_type="item_type",
                    recommendation_item_type_slug=item_type_slug,
                    recommendation_search_term=term_singular,
                )

            # No matches found, but it's still a recommendation question - return general
            logger.info(
                "RECOMMENDATION: No matches for '%s', returning general",
                term_singular
            )
            return OpenInputResponse(
                asks_recommendation=True,
                recommendation_match_type="general",
            )

    return None
