"""Menu query parsing."""

import logging
import re

from orderbot.cache import menu_cache

from ....schemas import OpenInputResponse
from ...constants import clean_extracted_text
from ...inquiry_patterns import MORE_MENU_ITEMS_PATTERNS

logger = logging.getLogger(__name__)

# Strips trailing category suffixes: "breakfast options" → "breakfast"
_CATEGORY_SUFFIX_RE = re.compile(
    r"\s+(?:options|items|choices|menu\s+items|menu)\s*$", re.IGNORECASE
)


def _strip_category_suffix(text: str) -> str:
    """Strip trailing words like 'options', 'items', 'choices' from category text."""
    return _CATEGORY_SUFFIX_RE.sub("", text).strip()

# Strips common question prefixes from captured text before "by the pound"
# e.g., "what's your food" -> "food", "do you have any fish" -> "fish"
_QUESTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"what(?:'s|'s|\s+is|\s+are)\s+(?:your|the)\s+"
    r"|what\s+"
    r"|do\s+you\s+(?:have|sell|carry|offer|make)\s+(?:any\s+)?"
    r"|show\s+me\s+(?:your|the)\s+"
    r"|tell\s+me\s+about\s+(?:your|the)\s+"
    r"|can\s+i\s+see\s+(?:your|the)\s+"
    r")",
    re.IGNORECASE,
)


def parse_signature_menu_inquiry(text: str) -> OpenInputResponse | None:
    """Parse inquiries about signature items, specials, popular items, etc.

    This function should be called BEFORE parse_dietary_inquiry to prevent
    "do you have any specials today" from being caught by availability patterns.

    Returns:
        OpenInputResponse with asking_signature_menu=True, or None if not a match
    """
    text_lower = text.lower().strip()

    # Patterns for specials/signature menu inquiries
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

    # Patterns for signature items, popular items, best sellers, favorites
    # "what are your signature items?", "signature items", "popular items", "best sellers"
    signature_patterns = [
        # Signature items
        re.compile(r"(?:what\s+are\s+)?(?:your|the)\s+signature\s+items?", re.IGNORECASE),
        re.compile(r"signature\s+(?:items?|menu|dishes?)", re.IGNORECASE),
        re.compile(r"(?:show|list)\s+(?:me\s+)?(?:your\s+)?signature\s+items?", re.IGNORECASE),
        # Popular items
        re.compile(r"(?:what\s+are\s+)?(?:your|the)\s+(?:most\s+)?popular\s+(?:items?|dishes?)?", re.IGNORECASE),
        re.compile(r"popular\s+(?:items?|menu|dishes?)", re.IGNORECASE),
        re.compile(r"what(?:'?s|\s+is)\s+popular", re.IGNORECASE),
        # Best sellers
        re.compile(r"(?:what\s+are\s+)?(?:your|the)\s+best\s*sellers?", re.IGNORECASE),
        re.compile(r"best\s*sell(?:ers?|ing)", re.IGNORECASE),
        # Favorites / house favorites
        re.compile(r"(?:what\s+are\s+)?(?:your|the)\s+(?:house\s+)?favorites?", re.IGNORECASE),
        re.compile(r"(?:house|customer|staff)\s+favorites?", re.IGNORECASE),
        # Featured items
        re.compile(r"(?:what\s+are\s+)?(?:your|the)\s+featured\s+(?:items?|dishes?)?", re.IGNORECASE),
        re.compile(r"featured\s+(?:items?|menu|dishes?)", re.IGNORECASE),
    ]

    for pattern in signature_patterns:
        if pattern.search(text_lower):
            logger.info("SIGNATURE MENU INQUIRY (signature/popular): '%s'", text[:50])
            return OpenInputResponse(
                asking_signature_menu=True,
                signature_menu_type=None,
            )

    return None


def parse_menu_query(text: str) -> OpenInputResponse | None:
    """Parse 'what X do you have?' type menu queries."""
    text_lower = text.lower().strip()

    # Check for "X by the pound" pattern first (e.g., "fish by the pound", "cheese by the pound")
    # This is a bare category reference that should list available items in that category
    by_pound_pattern = re.compile(
        r"^(?:the\s+)?(.+?)\s+by\s+the\s+pound\s*(?:please)?[.?!]?$",
        re.IGNORECASE
    )
    by_pound_match = by_pound_pattern.match(text_lower)
    if by_pound_match:
        category_term = by_pound_match.group(1).strip()
        # Strip question prefixes like "what's your", "do you have any"
        category_term = _QUESTION_PREFIX_RE.sub("", category_term).strip()
        if category_term:
            # Check if it maps to a known category (DB lookup)
            category_info = menu_cache.get_category_keyword_mapping(category_term)
            if category_info:
                menu_type = category_info["slug"]
                logger.info("MENU QUERY (by the pound): '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=menu_type,
                )
            # Even if not in DB mapping, return as a menu query for fallback search
            logger.info("MENU QUERY (by the pound fallback): '%s' -> menu_query_type=%s", text[:50], category_term)
            return OpenInputResponse(
                menu_query=True,
                menu_query_type=category_term,
            )
        # Empty after stripping prefix (e.g., "what's by the pound?") — fall through

    # NOTE: Specials/signature menu inquiries are now handled by parse_signature_menu_inquiry()
    # which is called earlier in the parsing pipeline (before dietary inquiry)

    # Generic terms that should trigger a GENERAL menu listing (all categories)
    # These are not specific category queries - they're asking about the whole menu
    general_menu_terms = {
        "food", "foods", "stuff", "things", "items", "menu items",
        "menu", "options", "choices", "eats", "grub",
    }

    # Patterns for GENERAL menu inquiries (should list all categories)
    general_menu_patterns = [
        # "what's on your/the menu?" / "whats on your menu?" / "what is on your/the menu?"
        # Also handles typo "what on your menu?" (missing 's)
        re.compile(r"what(?:'?s|\s+is)?\s+on\s+(?:your|the)\s+menu", re.IGNORECASE),
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
        # "what am I ordering?" - asking about available options
        re.compile(r"what\s+am\s+i\s+ordering", re.IGNORECASE),
        # "what's available?" / "what is available?"
        re.compile(r"what(?:'?s|\s+is)\s+available", re.IGNORECASE),
        # "can you tell me what you have?" / "tell me what you have" / "tell me what's available"
        re.compile(r"(?:(?:can|could|would)\s+you\s+)?tell\s+me\s+what(?:\s+you\s+(?:have|serve|offer|sell|make)|(?:'?s|\s+is)\s+(?:available|on\s+(?:the|your)\s+menu))", re.IGNORECASE),
        # "what have you got?" / "what've you got?"
        re.compile(r"what(?:'ve|\s+have)\s+you\s+got", re.IGNORECASE),
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
        # "what X do you have/sell/carry/offer/make" - capture X
        re.compile(r"what\s+(.+?)\s+do\s+you\s+(?:have|sell|carry|offer|make)", re.IGNORECASE),
        re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|have\s+you)\s+got", re.IGNORECASE),
        re.compile(r"what\s+(?:are\s+)?(?:your|the)\s+(.+?)(?:\s+options)?(?:\?|$)", re.IGNORECASE),
        re.compile(r"do\s+you\s+(?:have|sell|carry|offer|make)\s+(?:any\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
        # "tell me about your X" / "tell me about the X"
        re.compile(r"tell\s+me\s+about\s+(?:your|the)\s+(.+?)(?:\?|$)", re.IGNORECASE),
        # "show me your X" / "list your X"
        re.compile(r"(?:show|list)\s+(?:me\s+)?(?:your|the)\s+(.+?)(?:\?|$)", re.IGNORECASE),
        # "what X are available?" / "what X do you offer?"
        re.compile(r"what\s+(.+?)\s+(?:are\s+available|is\s+available)", re.IGNORECASE),
        # "can I see your X?" / "can I get a list of X?"
        re.compile(r"can\s+i\s+(?:see|get)\s+(?:your|the|a\s+list\s+of)\s+(.+?)(?:\?|$)", re.IGNORECASE),
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

    # Broader "tell me about X" — only match if X resolves to a known DB category.
    # This catches "tell me about breakfast options" without requiring "your"/"the",
    # but does NOT catch "tell me about the classic" (not a category → falls through).
    tell_me_match = re.search(r"tell\s+me\s+about\s+(.+?)(?:\?|$)", text_lower)
    if tell_me_match:
        category_text = clean_extracted_text(tell_me_match.group(1).strip())
        stripped = _strip_category_suffix(category_text)
        if stripped:
            category_info = menu_cache.get_category_keyword_mapping(stripped)
            if category_info:
                logger.info(
                    "MENU QUERY (tell me about category): '%s' -> menu_query_type=%s",
                    text[:50], category_info["slug"],
                )
                return OpenInputResponse(menu_query=True, menu_query_type=category_info["slug"])

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
                # Filter out common phrases that aren't real categories
                # "what else do you have?" captures "do you have" which is not a category
                non_category_phrases = {
                    "do you have", "are there", "can i get", "you got",
                    "is there", "have you got", "do you got",
                }
                if category and category not in non_category_phrases:
                    logger.info("MORE MENU ITEMS: extracted category '%s'", category)
                else:
                    category = None

            return OpenInputResponse(wants_more_menu_items=True, more_menu_category=category)

    return None
