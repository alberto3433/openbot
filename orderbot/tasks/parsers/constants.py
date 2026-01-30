"""
Parser Constants.

This module contains constants used by both LLM and deterministic parsers
for recognizing and normalizing user input. These include menu items,
ingredient lists, regex patterns for intent detection, and price data.
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
# Ordinal Words Mapping
# =============================================================================

# Maps ordinal words to 1-indexed positions
# Used for "the second bagel", "3rd coffee", "first one", etc.
ORDINAL_WORDS = {
    "first": 1, "1st": 1,
    "second": 2, "2nd": 2,
    "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4,
    "fifth": 5, "5th": 5,
    "sixth": 6, "6th": 6,
    "seventh": 7, "7th": 7,
    "eighth": 8, "8th": 8,
    "ninth": 9, "9th": 9,
    "tenth": 10, "10th": 10,
}

# Extended patterns for selection from numbered lists (maps to 0-indexed)
# Sorted by length descending so longer matches are checked first
# e.g., "the second one" should match "the second" not "one"
_SELECTION_PATTERNS: list[tuple[str, int]] = sorted([
    ("the first", 0), ("number one", 0), ("number 1", 0), ("first", 0), ("one", 0), ("1", 0),
    ("the second", 1), ("number two", 1), ("number 2", 1), ("second", 1), ("two", 1), ("2", 1),
    ("the third", 2), ("number three", 2), ("number 3", 2), ("third", 2), ("three", 2), ("3", 2),
    ("the fourth", 3), ("number four", 3), ("number 4", 3), ("fourth", 3), ("four", 3), ("4", 3),
    ("the fifth", 4), ("number five", 4), ("number 5", 4), ("fifth", 4), ("five", 4), ("5", 4),
    ("the sixth", 5), ("number six", 5), ("number 6", 5), ("sixth", 5), ("six", 5), ("6", 5),
], key=lambda x: len(x[0]), reverse=True)


def extract_selection_index(user_input: str, max_options: int) -> int | None:
    """Extract a 0-indexed selection from user input.

    Handles patterns like "the first one", "number 2", "third", "3", etc.
    Returns None if no valid selection is found or if selection is out of range.

    Args:
        user_input: The user's input string
        max_options: Maximum number of options (selections >= max_options are invalid)

    Returns:
        0-indexed selection, or None if not found/invalid
    """
    user_lower = user_input.lower().strip()

    for pattern, index in _SELECTION_PATTERNS:
        if pattern in user_lower:
            if index < max_options:
                return index
            return None  # Out of range

    return None


# Re-export extract_quantity_for_pattern as extract_quantity for backward compatibility
extract_quantity = extract_quantity_for_pattern

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
# Regex Patterns
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
    # "can you change it to X" / "could you make it X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "can you change the bagel to X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "make it with X" / "can you make it with X instead"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:make|have|do)\s+(?:it|that)\s+with\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
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
# Side Items
# =============================================================================
# Note: SIDE_ITEM_MAP was moved to the database - use menu_cache.resolve_side_alias()
# Side item aliases are stored in the menu_items.aliases column.

# =============================================================================
# Menu Item Recognition
# =============================================================================
# NOTE: KNOWN_MENU_ITEMS has been removed. All menu item names and aliases are
# now loaded from the database via menu_data_cache._load_known_menu_items_from_bulk().
# Use get_known_menu_items() to access the cached set of recognized item names.
#
# The database stores:
# - menu_items.name: canonical item names
# - menu_items.aliases: comma-separated short forms and synonyms
#
# The cache includes all names (lowercased), names without "The " prefix,
# and all aliases. This enables matching user input like "blt", "the blt",
# "bacon egg and cheese", etc. to their canonical database entries.

# =============================================================================
# Menu Item Recognition (MOVED TO DATABASE)
# =============================================================================
# NOTE: NO_THE_PREFIX_ITEMS and MENU_ITEM_CANONICAL_NAMES have been moved to
# the database. All menu item aliases are now stored in the MenuItem.aliases
# column and loaded via menu_cache.
#
# To resolve user input to canonical menu item names, use:
#   from orderbot.menu_data_cache import menu_cache
#   canonical_name = menu_cache.resolve_menu_item_alias("tuna salad")
#   # Returns: "Tuna Salad Sandwich" or None if not found
#
# See migrations:
# - b2c3d4e5f6g8_migrate_menu_item_canonical_names.py
# - c3d4e5f6g7h9_add_remaining_menu_aliases.py

# =============================================================================
# Price Inquiry Patterns
# =============================================================================

PRICE_INQUIRY_PATTERNS = [
    # "how much are/is X"
    re.compile(r"how\s+much\s+(?:are|is|does?|do)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\s+cost)?(?:\?|$)", re.IGNORECASE),
    # "what's the price of X" / "what is the price of X"
    re.compile(r"what(?:'?s|\s+is)\s+the\s+price\s+(?:of|for)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what do X cost"
    re.compile(r"what\s+do(?:es)?\s+(?:the\s+)?(?:a\s+)?(.+?)\s+cost(?:\?|$)", re.IGNORECASE),
    # "cost of X"
    re.compile(r"(?:the\s+)?cost\s+of\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "price of X"
    re.compile(r"(?:the\s+)?price\s+(?:of|for)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "how much for X"
    re.compile(r"how\s+much\s+for\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Menu Category Keywords (MOVED TO DATABASE)
# =============================================================================
# NOTE: MENU_CATEGORY_KEYWORDS has been moved to the database.
# Category keyword mappings are loaded from two sources:
# 1. item_types table: For direct item type lookups (lookup_type="item_type")
# 2. categories table: For category-based lookups (lookup_type="category")
#
# The categories table uses the menu_item_category join table to group
# items into categories (e.g., "sandwich" category includes egg_sandwich,
# fish_sandwich, deli_sandwich items).
#
# To look up category keywords, use:
#   from orderbot.menu_data_cache import menu_cache
#   category_info = menu_cache.get_category_keyword_mapping("sandwiches")
#   # Returns: {"slug": "sandwich", "lookup_type": "category", ...}
#
# To get all available category keywords (for error messages):
#   available = menu_cache.get_available_category_keywords()

# =============================================================================
# Store Info Inquiry Patterns
# =============================================================================

STORE_HOURS_PATTERNS = [
    re.compile(r"what\s+(?:are|is)\s+(?:your|the)\s+hours", re.IGNORECASE),
    re.compile(r"when\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:are\s+you|you)\s+open\s+(?:today|now|on)", re.IGNORECASE),
    re.compile(r"what\s+time\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:hours|opening\s+hours|business\s+hours)", re.IGNORECASE),
    re.compile(r"how\s+late\s+(?:are\s+you|do\s+you\s+stay)\s+open", re.IGNORECASE),
]

STORE_LOCATION_PATTERNS = [
    re.compile(r"where\s+(?:are\s+you|is\s+the\s+store)\s+located", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your|the)\s+address", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:address|location)", re.IGNORECASE),
    re.compile(r"where\s+(?:are\s+you|is\s+(?:this|the\s+store))", re.IGNORECASE),
    re.compile(r"how\s+do\s+i\s+(?:get|find)\s+(?:you|there|the\s+store)", re.IGNORECASE),
]

# Delivery zone inquiry patterns - capture the location they're asking about
DELIVERY_ZONE_PATTERNS = [
    # "do you deliver to X" / "can you deliver to X"
    re.compile(r"(?:do|can|will)\s+you\s+deliver\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "is X in your delivery area/zone"
    re.compile(r"is\s+(.+?)\s+in\s+(?:your|the)\s+delivery\s+(?:area|zone|range)", re.IGNORECASE),
    # "can I get delivery to X"
    re.compile(r"can\s+i\s+get\s+delivery\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "do you deliver in X"
    re.compile(r"(?:do|can)\s+you\s+deliver\s+in\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "delivery to X" / "deliver to X"
    re.compile(r"deliver(?:y)?\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Recommendation Inquiry Patterns
# =============================================================================

# General recommendation patterns (no term extraction) - domain-agnostic
# These return "general" as the recommendation type
RECOMMENDATION_GENERAL_PATTERNS = [
    re.compile(r"what\s+(?:do\s+you|would\s+you|should\s+i|can\s+you)\s+recommend\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular|the\s+best)\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:most\s+)?popular\??$", re.IGNORECASE),
    re.compile(r"what\s+(?:are\s+)?(?:your\s+)?(?:best|most\s+popular)\s+(?:sellers?|items?)", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?most\s+popular\s+item", re.IGNORECASE),
    re.compile(r"(?:any|have\s+any|got\s+any|do\s+you\s+have\s+any)\s+recommendations?\??", re.IGNORECASE),
    re.compile(r"(?:suggest|recommend)\s+(?:something|anything)", re.IGNORECASE),
    re.compile(r"what\s+sells\s+best", re.IGNORECASE),
    # Meal-based recommendations (breakfast/lunch) - treat as general
    re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular)\s+for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
    re.compile(r"recommend\s+(?:something\s+)?for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
]

# Term-extracting recommendation patterns - data-driven item/type lookup
# These patterns capture a search term (e.g., "bagels", "coffee", "teas")
# The term is singularized and used for menu_items -> item_type fallback search
RECOMMENDATION_TERM_PATTERNS = [
    # "what {TERM} do you recommend" - captures term before verb phrase
    re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE),
    # "what's your best/popular {TERM}" - captures term after adjective
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "which {TERM} is/are best/popular/good" - captures term after "which"
    re.compile(r"which\s+(.+?)\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE),
    # "recommend a {TERM}" - captures term after "recommend a/some"
    re.compile(r"recommend\s+(?:a\s+|some\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "best/popular/favorite {TERM}" - captures term after adjective
    re.compile(r"(?:best|popular|favorite)\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "what's popular for {TERM}" - captures term after "for"
    re.compile(r"what(?:'?s|\s+is)\s+popular\s+for\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "what {TERM} is popular/good/best" - captures term between what and is
    re.compile(r"what\s+(.+?)\s+is\s+(?:popular|good|best)", re.IGNORECASE),
]

# =============================================================================
# Item Description Inquiry Patterns
# =============================================================================

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
    - Words ending in 'ch', 'sh', 's', 'x', 'z' get 'es'
    - Words ending in consonant + 'y' get 'ies'
    - Most others get 's'
    """
    if not word:
        return word

    # Words ending in ch, sh, s, x, z get 'es'
    if word.endswith(('ch', 'sh', 's', 'x', 'z')):
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
# Item Description Inquiry Patterns
# =============================================================================

# Pattern to extract item name from "what's on/in the X?" questions
ITEM_DESCRIPTION_PATTERNS = [
    # "what's on the health nut?" "what's in the BLT?"
    re.compile(r"what(?:'s|s| is) (?:on|in) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what comes on the health nut?"
    re.compile(r"what comes (?:on|in|with) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what does the health nut have on it?"
    re.compile(r"what does (?:the |a )?(.+?) (?:have|come with)", re.IGNORECASE),
    # "tell me about the health nut"
    re.compile(r"tell me (?:about|what's in) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "describe the health nut"
    re.compile(r"describe (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "ingredients in the health nut"
    re.compile(r"ingredients (?:in|of|for) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Modifier/Add-on Inquiry Patterns
# =============================================================================

# Note: MODIFIER_CATEGORY_KEYWORDS was moved to the database (modifier_categories table)
# - use menu_data["modifier_categories"]["keyword_to_category"] instead
# - see migration j0k1l2m3n4o5_add_modifier_categories_table.py

# Note: MODIFIER_ITEM_KEYWORDS was moved to the database (item_types.aliases column)
# - use menu_data["item_keywords"] instead
# - populated by menu_index_builder._build_item_keywords()

# Patterns for modifier inquiries - each returns (pattern, item_group_index, category_group_index)
# Group indices are 1-based, or 0 if not captured
MODIFIER_INQUIRY_PATTERNS = [
    # "what can I add to coffee?" / "what can I add to my coffee?"
    (re.compile(r"what (?:can|could) (?:i|you|we) (?:add|put|get) (?:to|on|in|for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what do you have for coffee?" / "what options for coffee?"
    (re.compile(r"what (?:do you have|options?|choices?) (?:for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what goes on a bagel?" / "what goes in coffee?"
    (re.compile(r"what (?:goes|can go) (?:on|in|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what kind of bagel toppings do you have?" / "what types of spreads do you have?"
    (re.compile(r"what (?:kind|kinds|type|types) of (\w+(?:\s+\w+)?) do you (?:have|offer|carry)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "what sweeteners do you have?" / "what milks do you have?"
    (re.compile(r"what (\w+(?:\s+\w+)?) do you (?:have|offer|carry)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "do you have sweeteners?" / "do you have flavored syrups?"
    (re.compile(r"do you (?:have|offer|carry) (?:any )?(\w+(?:\s+\w+)?)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "what sweeteners for coffee?" / "what milks for lattes?"
    (re.compile(r"what (\w+(?:\s+\w+)?) (?:for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 2, 1),
    # "coffee options" / "bagel toppings"
    (re.compile(r"^(.+?) (options?|choices?|add-?ons?|extras?)(?:\?|$)", re.IGNORECASE), 1, 2),
]

# =============================================================================
# Off-Topic Request Patterns (during item configuration)
# =============================================================================

# Patterns to detect off-topic requests during configuration
# These are questions or requests that aren't answers to the current config question
OFF_TOPIC_PATTERNS = [
    # Menu inquiries: "what syrups do you have?" / "what sweeteners do you have?"
    re.compile(r"what (\w+(?:\s+\w+)?)\s+do\s+you\s+(?:have|offer|carry)", re.IGNORECASE),
    # "what options do you have?" / "what are my options?"
    re.compile(r"what (?:are (?:my|the) )?options", re.IGNORECASE),
    # "what can I add?" / "what can I get?"
    re.compile(r"what (?:can|could)\s+(?:i|you)\s+(?:add|get|put)", re.IGNORECASE),
    # "do you have vanilla?" / "do you have oat milk?"
    re.compile(r"do you (?:have|offer|carry)\s+(?:any\s+)?(\w+)", re.IGNORECASE),
    # "what flavors do you have?" / "what sizes are there?"
    re.compile(r"what (\w+)\s+(?:are there|do you offer)", re.IGNORECASE),
    # "can I get vanilla?" / "can I add sugar?"
    re.compile(r"can\s+(?:i|you)\s+(?:get|add|have)\s+\w+\?", re.IGNORECASE),
    # "what kinds of X do you have?"
    re.compile(r"what (?:kind|type|kinds|types)\s+of\s+\w+", re.IGNORECASE),
    # Modifier additions: "add vanilla syrup" / "add oat milk"
    re.compile(r"^add\s+\w+", re.IGNORECASE),
    # "with vanilla" / "with caramel syrup"
    re.compile(r"^with\s+\w+", re.IGNORECASE),
    # "put vanilla in it" / "put some sugar"
    re.compile(r"^put\s+\w+", re.IGNORECASE),
    # "I want vanilla" / "I'd like oat milk"
    re.compile(r"^i(?:'?d)?\s*(?:want|like|need)\s+(?:to\s+add\s+)?\w+", re.IGNORECASE),
    # "make it with vanilla" / "make it iced" (but not "make it small/large")
    re.compile(r"^make\s+it\s+(?:with\s+)?\w+", re.IGNORECASE),
]

# =============================================================================
# "Show More" Menu Items Patterns
# =============================================================================

# Patterns to detect when user wants to see more items from a previous menu query
MORE_MENU_ITEMS_PATTERNS = [
    # "what other pastries do you have?" / "what other options?"
    re.compile(r"what (?:other|else|more)\b", re.IGNORECASE),
    # "any other pastries?" / "any more options?"
    re.compile(r"any (?:other|more)\b", re.IGNORECASE),
    # "more pastries" / "more options" / "more please"
    re.compile(r"^more\b", re.IGNORECASE),
    # "show me more" / "tell me more"
    re.compile(r"(?:show|tell|give) (?:me )?more\b", re.IGNORECASE),
    # "what else?" / "anything else?" (when asking about menu, not ordering)
    re.compile(r"(?:what|anything) else\??\s*$", re.IGNORECASE),
    # "keep going" / "continue"
    re.compile(r"^(?:keep going|continue|go on)\s*\??$", re.IGNORECASE),
    # "and?" / "and what else?"
    re.compile(r"^and\s*\??\s*$", re.IGNORECASE),
]


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
        from orderbot.menu_data_cache import menu_cache
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


