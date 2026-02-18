"""
Parser Utility Functions.

Runtime helper functions extracted from constants.py to separate pure
constants from functions that perform I/O, randomisation, or cache lookups.

Constants remain in constants.py; this module holds the runtime logic.
"""

import logging
import random
import re

logger = logging.getLogger(__name__)


# =============================================================================
# Small Talk Patterns - social/conversational inputs
# =============================================================================

# Each entry is (compiled_regex, response_text)
SMALL_TALK_RESPONSES: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"^(?:how(?:'s|\s+is)\s+it\s+going|how\s+are\s+you(?:\s+doing)?|how\s+do\s+you\s+do)[\s?!.,]*$",
        re.IGNORECASE,
    ), "I'm doing great, thanks for asking!"),
    (re.compile(
        r"^good\s+(morning|afternoon|evening)[\s!.,]*$",
        re.IGNORECASE,
    ), "Good {1}!"),
    (re.compile(
        r"^(?:what'?s\s+up|sup|what'?s\s+new)[\s?!.,]*$",
        re.IGNORECASE,
    ), "Not much, just ready to help with your order!"),
    (re.compile(
        r"^nice\s+to\s+meet\s+you[\s!.,]*$",
        re.IGNORECASE,
    ), "Nice to meet you too!"),
    (re.compile(
        r"^i'?m\s+(?:doing\s+)?(?:good|great|fine|well|okay|ok|alright)[\s!.,]*$",
        re.IGNORECASE,
    ), "Glad to hear it!"),
    (re.compile(
        r"^how(?:'s|\s+is)\s+your\s+day[\s?!.,]*$",
        re.IGNORECASE,
    ), "It's going well, thanks!"),
    (re.compile(
        r"^how\s+are\s+things|how(?:'s|\s+is)\s+everything[\s?!.,]*$",
        re.IGNORECASE,
    ), "All great over here!"),
]


def match_small_talk(text: str) -> str | None:
    """Check if text is a small talk phrase and return the response.

    Args:
        text: User input text (stripped).

    Returns:
        Response string if matched, None otherwise.
    """
    for pattern, response_template in SMALL_TALK_RESPONSES:
        m = pattern.match(text)
        if m:
            # Support dynamic placeholders like {1} for capture groups
            response = response_template
            for i in range(1, len(m.groups()) + 1):
                if m.group(i):
                    response = response.replace(f"{{{i}}}", m.group(i))
            return response
    return None


# =============================================================================
# Order Redirect Phrases - varied prompts to redirect back to ordering
# =============================================================================

ORDER_REDIRECTS = [
    "What can I get for you?",
    "Can I take your order?",
    "How can I help you?",
    "What can I get started for you?",
    "What are you in the mood for?",
    "Ready to order?",
]

ORDER_REDIRECTS_HAS_ITEMS = [
    "Anything else I can get for you?",
    "What else can I get you?",
    "Can I get you anything else?",
]


def get_order_redirect(has_items: bool) -> str:
    """Pick a random order redirect phrase.

    Args:
        has_items: True if the order already has items in the cart.

    Returns:
        A redirect phrase string.
    """
    pool = ORDER_REDIRECTS_HAS_ITEMS if has_items else ORDER_REDIRECTS
    return random.choice(pool)


# =============================================================================
# Text Extraction Utility
# =============================================================================


def clean_extracted_text(text: str) -> str:
    """
    Clean extracted text by removing trailing punctuation and whitespace.

    This is commonly used after extracting text from regex match groups
    to normalize user input.

    Args:
        text: The text to clean

    Returns:
        The cleaned text with trailing punctuation removed and whitespace stripped
    """
    return re.sub(r'[.!?,]+$', '', text).strip()


# =============================================================================
# Item Type Display Names
# =============================================================================

# Display name pluralization is now stored in the database (item_types.display_name_plural)
# and loaded into menu_data["item_type_display_names"] by menu_index_builder.py


def _pluralize(word: str) -> str:
    """
    Pluralize a word using simple English rules.

    Rules:
    - Words likely already plural (ending in common plural patterns) are returned as-is
    - Words ending in 'ch', 'sh', 'ss', 'us', 'x', 'z' get 'es'
    - Words ending in consonant + 'y' get 'ies'
    - Most others get 's'
    """
    if not word:
        return word

    # Check if word is likely already plural
    # Words ending in consonant+s (but not ss, us, is, os) are probably already plural
    # e.g., "items", "bagels", "drinks" vs "bus", "glass", "thesis"
    if word.endswith('s') and len(word) > 2:
        # These endings suggest the word is singular and needs 'es'
        singular_endings = ('ss', 'us', 'is', 'os')
        if not word.endswith(singular_endings):
            # Words like "items", "salads", "drinks" - already plural
            return word

    # Words ending in ch, sh, ss, us, x, z get 'es'
    if word.endswith(('ch', 'sh', 'ss', 'us', 'x', 'z')):
        return word + 'es'

    # Words ending in consonant + y get 'ies'
    if word.endswith('y') and len(word) > 1 and word[-2] not in 'aeiou':
        return word[:-1] + 'ies'

    # Default: add 's'
    return word + 's'


def get_item_type_display_name(slug: str, display_names: dict = None) -> str:
    """
    Convert an item type slug to a user-friendly plural display name.

    Uses the display_names mapping (from menu data) for special cases, otherwise
    converts underscores to spaces and pluralizes the last word.

    Args:
        slug: The item type slug (e.g., 'by_the_lb', 'egg_sandwich')
        display_names: Optional mapping from slug to custom display name
                       (typically from menu_data["item_type_display_names"])

    Returns:
        Plural display name (e.g., 'food by the pound', 'egg sandwiches')
    """
    # Check for custom display name from database
    if display_names and slug in display_names:
        return display_names[slug]

    # Convert underscores to spaces
    display = slug.replace("_", " ")

    # Pluralize the last word
    words = display.split()
    if words:
        words[-1] = _pluralize(words[-1])
        return " ".join(words)

    return display


# =============================================================================
# Dynamic Menu Data Cache Getters
# =============================================================================
#
# These functions delegate to the MenuDataCache if loaded. There are no
# hardcoded fallbacks - if the cache is not loaded, these functions raise
# RuntimeError. This ensures all menu data comes from the database.


def _get_menu_cache():
    """Get the menu cache singleton, returns None if not available."""
    try:
        from orderbot.cache import menu_cache
        if menu_cache.is_loaded:
            return menu_cache
    except ImportError:
        pass
    return None


def get_known_menu_items() -> set[str]:
    """
    Get all known menu item names and aliases from the database.

    Returns data from cache. If cache is not loaded or empty, returns an
    empty set and logs a warning. This function no longer falls back to
    hardcoded KNOWN_MENU_ITEMS - all data comes from the database.

    The cached set includes:
    - Full menu item names (lowercased)
    - Names without "The " prefix
    - All aliases from the aliases column
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_known_menu_items()
        if cached:
            return cached
    logger.warning("get_known_menu_items: cache not loaded, returning empty set")
    return set()


def get_items_with_defaults_aliases() -> dict[str, str]:
    """
    Get alias mapping for items that have default ingredients.

    Returns a dict mapping user input variations (aliases) to the actual
    menu item names in the database. Items with default ingredients need
    special recognition to prevent trigger-based detection from overriding them.

    Returns:
        Dict mapping lowercase alias -> menu item name (with original casing).

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_items_with_defaults_aliases()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Items with defaults aliases not available. Ensure menu_data_cache is loaded from the database."
    )


def find_item_by_unit_type(item_name: str, unit_type: str) -> tuple[str, str] | None:
    """
    Find an item by name or alias within a specific unit type.

    This is the generic, data-driven replacement for find_by_pound_item().
    Use this for all unit-type-based lookups.

    Args:
        item_name: Item name or alias to look up (e.g., "lox", "nova", "whitefish salad")
        unit_type: How items are sold - 'by_weight', 'dozen', or 'each'.

    Returns:
        Tuple of (canonical_name, item_type_slug) if found, None otherwise.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.find_item_by_unit_type(item_name, unit_type)
    return None


# ── Cancellation sentinel constants ──────────────────────────────────
CANCEL_LAST_ITEM = "__last_item__"
CANCEL_ALL_ITEMS = "__all_items__"
CANCEL_LAST_N_PREFIX = "__last_n_items_"
REDUCE_TO_ONE = "__reduce_to_one__"
REDUCE_TO_ONE_PREFIX = "__reduce_to_one_"


def make_last_n_sentinel(count: int) -> str:
    """Build a 'cancel last N items' sentinel, e.g. '__last_n_items_3__'."""
    return f"{CANCEL_LAST_N_PREFIX}{count}__"


def parse_last_n_sentinel(value: str) -> int | None:
    """Extract N from '__last_n_items_N__', or return None."""
    if value.startswith(CANCEL_LAST_N_PREFIX) and value.endswith("__"):
        try:
            return int(value[len(CANCEL_LAST_N_PREFIX):-2])
        except ValueError:
            return None
    return None


def make_reduce_to_one_sentinel(item_type: str) -> str:
    """Build a 'reduce to one' sentinel, e.g. '__reduce_to_one_bagel__'."""
    return f"{REDUCE_TO_ONE_PREFIX}{item_type}__"


def parse_reduce_to_one_sentinel(value: str) -> str | None:
    """Extract item_type from '__reduce_to_one_<type>__', or return None."""
    if value.startswith(REDUCE_TO_ONE_PREFIX) and value.endswith("__"):
        inner = value[len(REDUCE_TO_ONE_PREFIX):-2]
        return inner if inner else None
    return None
