"""Menu query parsing."""

import logging
import re

from orderbot.cache import menu_cache

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text
from ...inquiry_patterns import MORE_MENU_ITEMS_PATTERNS

logger = logging.getLogger(__name__)


def parse_menu_query(text: str) -> OpenInputResponse | None:
    """Parse 'what X do you have?' type menu queries."""
    text_lower = text.lower().strip()

    # Check for specials/signature menu inquiries first
    # "do you have any specials today?", "what are your specials?", "any specials?"
    specials_patterns = [
        re.compile(r"(?:do\s+you\s+have\s+)?(?:any\s+)?specials?\b", re.IGNORECASE),
        re.compile(r"what(?:'?s|\s+are)\s+(?:your|the)\s+specials?", re.IGNORECASE),
        re.compile(r"(?:got\s+)?any\s+specials?\s*(?:today|right now)?", re.IGNORECASE),
        re.compile(r"today'?s?\s+specials?", re.IGNORECASE),
        re.compile(r"specials?\s+(?:today|of\s+the\s+day)", re.IGNORECASE),
    ]

    for pattern in specials_patterns:
        if pattern.search(text_lower):
            logger.info("SIGNATURE MENU INQUIRY (specials): '%s'", text[:50])
            return OpenInputResponse(
                asking_signature_menu=True,
                signature_menu_type=None,  # None means all signature items
            )

    # Generic terms that should trigger a GENERAL menu listing (all categories)
    # These are not specific category queries - they're asking about the whole menu
    general_menu_terms = {
        "food", "foods", "stuff", "things", "items", "menu items",
        "menu", "options", "choices", "eats", "grub",
    }

    # Patterns for GENERAL menu inquiries (should list all categories)
    general_menu_patterns = [
        # "what's on your/the menu?" / "whats on your menu?" / "what is on your/the menu?"
        re.compile(r"what(?:'?s|\s+is)\s+on\s+(?:your|the)\s+menu", re.IGNORECASE),
        # "what do you have?" / "what do you have on the menu?"
        re.compile(r"what\s+do\s+you\s+have(?:\s+on\s+(?:the|your)\s+menu)?(?:\?|$)", re.IGNORECASE),
        # "what do you serve?" / "what do you sell?"
        re.compile(r"what\s+do\s+you\s+(?:serve|sell|offer|make)", re.IGNORECASE),
        # "what can I order?" / "what can I get?"
        re.compile(r"what\s+can\s+i\s+(?:order|get|have)", re.IGNORECASE),
        # "show me the menu" / "let me see the menu"
        re.compile(r"(?:show|let\s+me\s+see|can\s+i\s+see)\s+(?:me\s+)?(?:the|your)\s+menu", re.IGNORECASE),
        # "menu please" / "the menu"
        re.compile(r"^(?:the\s+)?menu(?:\s+please)?(?:\?|!|\.)?$", re.IGNORECASE),
    ]

    # Check for general menu inquiry patterns first
    for pattern in general_menu_patterns:
        if pattern.search(text_lower):
            logger.info("GENERAL MENU QUERY: '%s'", text[:50])
            return OpenInputResponse(
                menu_query=True,
                menu_query_type=None,  # None means list all categories
            )

    # Patterns for menu category queries
    # "what desserts do you have?", "what sweets do you have?", "what pastries do you have?"
    # "what kind of muffins do you have?"
    menu_query_patterns = [
        # "what kind of X do you have" - capture X
        re.compile(r"what\s+(?:kind|type|types|kinds)\s+of\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        # "what X do you have" - capture X
        re.compile(r"what\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|have\s+you)\s+got", re.IGNORECASE),
        re.compile(r"what\s+(?:are\s+)?(?:your|the)\s+(.+?)(?:\s+options)?(?:\?|$)", re.IGNORECASE),
        re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    ]

    for pattern in menu_query_patterns:
        match = pattern.search(text_lower)
        if match:
            category_text = match.group(1).strip()
            # Remove trailing punctuation
            category_text = clean_extracted_text(category_text)

            # Check if it's a generic term that should trigger general menu listing
            if category_text in general_menu_terms:
                logger.info("GENERAL MENU QUERY (generic term '%s'): '%s'", category_text, text[:50])
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=None,  # None means list all categories
                )

            # Check if it maps to a known category (DB lookup)
            category_info = menu_cache.get_category_keyword_mapping(category_text)
            if category_info:
                menu_type = category_info["slug"]
                logger.info("MENU QUERY: '%s' -> menu_query_type=%s (DB category)", text[:50], menu_type)
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=menu_type,
                )

            # Not in DB category mapping, but still a valid menu inquiry pattern
            # Return with the extracted category text so handler can do word-boundary search
            # This handles "what lattes do you have?" where "lattes" isn't a DB category
            # but should search menu items containing "latte"
            logger.info("MENU QUERY: '%s' -> menu_query_type=%s (fallback search)", text[:50], category_text)
            return OpenInputResponse(
                menu_query=True,
                menu_query_type=category_text,
            )

    return None


def parse_more_menu_items(text: str) -> OpenInputResponse | None:
    """Parse 'show more' menu requests like 'what other drinks do you have?'

    Also extracts the category from "what other X" patterns so the handler can
    start a fresh query if no pagination context exists.
    """
    text_lower = text.lower().strip()

    for pattern in MORE_MENU_ITEMS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("MORE MENU ITEMS: '%s'", text[:50])

            # Try to extract the category from "what other X" patterns
            # e.g., "what other signature sandwiches do you have?" -> "signature sandwiches"
            category_match = re.search(
                r'what (?:other|else|more) ([a-z]+(?: [a-z]+)*?)(?:\s+(?:do you have|are there|can i get|you got)|\?|$)',
                text_lower
            )
            category = None
            if category_match:
                category = category_match.group(1).strip()
                # Clean up common suffixes
                if category.endswith(' options'):
                    category = category[:-8].strip()
                if category:
                    logger.info("MORE MENU ITEMS: extracted category '%s'", category)

            return OpenInputResponse(wants_more_menu_items=True, more_menu_category=category)

    return None
