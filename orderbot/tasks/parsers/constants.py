"""
Parser Constants.

This module contains constants used by both LLM and deterministic parsers
for recognizing and normalizing user input.

Sub-modules:
- selection_patterns: Ordinal words and list selection patterns
- inquiry_patterns: Price, store, recommendation, description inquiry patterns
- intent_patterns: Replace, cancel, quantity, duplicate, order status patterns
"""

import logging
import re

logger = logging.getLogger(__name__)

# =============================================================================
# Pagination Configuration
# =============================================================================

# Standard pagination size for all list displays
DEFAULT_PAGINATION_SIZE = 5

# =============================================================================
# Quantity Extraction (imported from quantity_utils for single source of truth)
# Re-exported for other modules that import from constants
# =============================================================================
from orderbot.tasks.parsers.quantity_utils import (
    WORD_TO_NUM,
    extract_quantity_for_pattern,
)

# =============================================================================
# Selection Patterns (re-exported from selection_patterns module)
# =============================================================================
from .selection_patterns import (
    ORDINAL_WORDS,
    SELECTION_PATTERNS,
)


# =============================================================================
# Skip Words for Parsing
# =============================================================================
# Import base skip words from cache.base to avoid circular imports
# (cache.base cannot import from here, so the canonical definitions live there)
from orderbot.cache.base import (
    SKIP_WORDS_BASIC,
    SKIP_WORDS_CONJUNCTIONS,
    SKIP_WORDS_PREPOSITIONS,
)

# Additional filler words for parsing (not needed in cache/base.py)
SKIP_WORDS_FILLER = {'please', 'thanks', 'it', 'that', 'yes', 'no'}

# Combined set for general-purpose parsing
SKIP_WORDS = SKIP_WORDS_BASIC | SKIP_WORDS_CONJUNCTIONS | SKIP_WORDS_PREPOSITIONS | SKIP_WORDS_FILLER

# =============================================================================
# Add Modifier Request Patterns
# =============================================================================

# Patterns that indicate user wants to add a modifier to an existing item
# Used in taking_items_handler.py and other modifier detection logic
ADD_MODIFIER_PATTERNS = [
    r"^add\s+",  # "add vanilla syrup"
    r"^with\s+",  # "with caramel"
    r"^can\s+(?:i|you)\s+(?:get|add)\s+",  # "can I get vanilla"
    r"^(?:i'?d?\s+)?like\s+(?:to\s+)?add\s+",  # "I'd like to add vanilla"
    r"^put\s+",  # "put vanilla in it"
    r"^can\s+you\s+put\s+",  # "can you put milk in that"
    r"put\s+.+?\s+in\s+(?:it|that|the|my)",  # "put milk in that"
]

# =============================================================================
# Qualifier Patterns for Special Instructions
# =============================================================================

# Qualifier patterns for special instructions extraction
# These are phrases that modify a standard modifier in a non-standard way
QUALIFIER_PATTERNS = [
    # "light on the X" / "light X" / "go light on X"
    (r'\b(?:go\s+)?light\s+(?:on\s+(?:the\s+)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'light'),
    # "easy on the X" / "go easy on the X"
    (r'\b(?:go\s+)?easy\s+on\s+(?:the\s+)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'light'),
    # "extra X" / "extra heavy on the X"
    (r'\bextra\s+(?:heavy\s+(?:on\s+(?:the\s+)?)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "lots of X" / "a lot of X"
    (r'\b(?:a\s+)?lot(?:s)?\s+of\s+(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "heavy on the X"
    (r'\bheavy\s+(?:on\s+(?:the\s+)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "a splash of X" / "splash of X"
    (r'\b(?:a\s+)?splash\s+of\s+(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'a splash of'),
    # "a little X" / "just a little X"
    (r'\b(?:just\s+)?a\s+little\s+(?:bit\s+of\s+)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'a little'),
    # "no X" / "hold the X" / "without X"
    (r'\b(?:no\s+|hold\s+the\s+|without\s+)(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'no'),
    # "X on the side" - captures single-word modifiers like sugar, cream, milk
    # Uses negative lookbehind to avoid matching "coffee cream" when user says "coffee cream on the side"
    (r'\b(\w+)\s+on\s+the\s+side\b', 'on the side'),
]

# =============================================================================
# Response Patterns
# =============================================================================

# Note: STANDALONE_INSTRUCTION_PATTERNS moved to database (response_pattern table with pattern_type='standalone_instruction')
# Use menu_cache.get_standalone_instruction_patterns() instead.

# Note: GREETING_PATTERNS moved to database (response_pattern table with pattern_type='greeting')
# Use menu_cache.is_greeting(text) or menu_cache.get_response_regex("greeting") instead.

# Gratitude patterns - thank you, thanks, etc.
GRATITUDE_PATTERNS = re.compile(
    r"^(thanks?(\s+you)?|thank\s+you(\s+(so\s+)?much)?|ty|thx|appreciated?)[\s!.,]*$",
    re.IGNORECASE
)

# Note: DONE_PATTERNS moved to database (response_pattern table with pattern_type='done')
# Use menu_cache.is_done(text) or menu_cache.get_response_regex("done") instead.

# Help request patterns - user needs assistance
HELP_PATTERNS = re.compile(
    r"^("
    r"help(\s+me)?|"  # "help", "help me"
    r"i('?m|\s+am)\s+(confused|lost|not\s+sure)|"  # "I'm confused", "I am lost"
    r"what\s+can\s+you\s+do|"  # "what can you do"
    r"how\s+do(es)?\s+(this|it)\s+work|"  # "how does this work"
    r"i\s+don'?t\s+(understand|know)|"  # "I don't understand"
    r"can\s+you\s+help(\s+me)?|"  # "can you help me"
    r"i\s+need\s+help"  # "I need help"
    r")[\s?!.,]*$",
    re.IGNORECASE
)

# =============================================================================
# Modifier Change Request Patterns
# =============================================================================

# Change request patterns - detect when user wants to modify an item
# These patterns extract the target (what to change) and the new_value
# Returns (pattern, group_indices) where group_indices is (target_group, new_value_group)
# target_group can be None for "change it to X" patterns (refers to last item)
CHANGE_REQUEST_PATTERNS = [
    # "change it to X" / "make it X" - target is implicit (last item)
    (re.compile(r"(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "change the bagel to X" / "make the spread X"
    (re.compile(r"(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "change X to Y" without "the" - e.g., "change corned beef to pastrami"
    # Note: This must come after "change it to X" pattern so "it" is matched as implicit target
    (re.compile(r"(?:change|switch)\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "can you change it to X" / "could you make it X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "can you change the bagel to X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "make it with X" / "can you make it with X instead"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:make|have|do)\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make it with X" (without "can you") - target is implicit (last item)
    (re.compile(r"make\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make [quantity] [modifier]" - e.g., "make 2 vanilla syrups"
    (re.compile(r"make\s+(\d+\s+.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "actually X instead" / "actually make it X"
    # Negative lookahead excludes cancellation keywords so "actually cancel that" is NOT a change request
    (re.compile(r"actually\s+(?!cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off)(?:make\s+it\s+)?(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I meant X" - clearly signals correction
    (re.compile(r"i\s+meant\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I want X instead" - requires "instead" to signal change (without "instead", treat as answer)
    (re.compile(r"i\s+want(?:ed)?\s+(.+?)\s+instead(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "no wait, X" / "wait, X instead"
    (re.compile(r"(?:no\s+)?wait[,.]?\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
]

# Repeat order patterns: "repeat my order", "same as last time", "my usual", etc.
REPEAT_ORDER_PATTERNS = re.compile(
    r"^(repeat\s+(my\s+)?(last\s+)?order|same\s+(as\s+)?(last\s+time|before)|"
    r"(my\s+)?usual|what\s+i\s+(usually\s+)?(get|have|order)|"
    r"same\s+(thing|order)(\s+as\s+(last\s+time|before))?|"
    r"(i'?ll\s+have\s+)?(the\s+)?same(\s+(thing|order))?(\s+again)?|"
    r"repeat\s+(that|it)|order\s+again)[\s!.,]*$",
    re.IGNORECASE
)

# =============================================================================
# String Normalization Utilities
# =============================================================================


def normalize_text(text: str) -> str:
    """
    Normalize text for comparison by lowercasing and stripping whitespace.

    This is the canonical function for preparing user input for pattern matching,
    lookups, and comparisons. Using this function ensures consistent normalization
    across the codebase.

    Args:
        text: The text to normalize

    Returns:
        Lowercased, whitespace-stripped text
    """
    return text.lower().strip()


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


def get_signature_item_aliases() -> dict[str, str]:
    """
    Get signature item alias mapping from database.

    Returns a dict mapping user input variations (aliases) to the actual
    menu item names in the database. This is used for recognizing orders
    like "bec", "bacon egg and cheese", "the classic", "the leo", etc.

    Returns:
        Dict mapping lowercase alias -> menu item name (with original casing).

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_signature_item_aliases()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Signature item aliases not available. Ensure menu_data_cache is loaded from the database."
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


