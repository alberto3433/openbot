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
# Drink Type Categories
# =============================================================================

# NOTE: Beverage types are now loaded from the database via menu_data_cache.py.
# - Soda/bottled beverages: item_type='beverage' (use get_soda_types())
# - Coffee/tea beverages: item_type='sized_beverage' (use get_coffee_types())
# Both support aliases via the 'aliases' column on menu_items.

def is_soda_drink(drink_type: str | None) -> bool:
    """Check if a drink type is a soda/cold beverage that doesn't need configuration.

    Uses database-loaded soda types (via get_soda_types()) which includes
    both item names and their aliases from the menu_items.aliases column.
    """
    if not drink_type:
        return False
    drink_lower = drink_type.lower().strip()
    soda_types = get_soda_types()
    # Check exact match first
    if drink_lower in soda_types:
        return True
    # Check if any soda type is contained in the drink name
    for soda in soda_types:
        if soda in drink_lower or drink_lower in soda:
            return True
    return False


# =============================================================================
# Word to Number Mapping
# =============================================================================

WORD_TO_NUM = {
    "a": 1, "an": 1, "one": 1,
    "two": 2, "couple": 2, "a couple": 2, "a couple of": 2, "couple of": 2,
    "three": 3, "a few": 3, "few": 3,
    "four": 4,
    "five": 5,
    "six": 6, "half dozen": 6, "half a dozen": 6, "a half dozen": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12, "dozen": 12, "a dozen": 12,
}

# =============================================================================
# Bagel Types and Spreads
# =============================================================================

# NOTE: Bagel types and spreads are now loaded from the database via menu_data_cache.py.
# Use get_bagel_types() for the set (includes aliases) or get_bagel_types_list()
# for an ordered list (display/pagination). Both support aliases via the
# 'aliases' column on ingredients where category='bread'.
#
# Spreads are loaded from ingredients where category='spread'.
# Spread types/varieties are loaded from cream cheese menu items.
# Use get_spreads(), get_spread_types(), and get_bagel_spreads() to access these.

# =============================================================================
# Modifier Category Classification
# =============================================================================
# NOTE: BAGEL_ONLY_TYPES, SPREAD_ONLY_TYPES, and AMBIGUOUS_MODIFIERS are now
# computed dynamically from the database. Use:
# - get_bagel_only_types() - bagel types that are NOT also spread types
# - get_spread_only_types() - spread types that are NOT also bagel types
# - get_ambiguous_modifiers() - types that are BOTH (need disambiguation)

# =============================================================================
# Speed Menu Bagels
# =============================================================================
# NOTE: Speed menu bagels are now loaded from the database via menu_data_cache.py.
# Use get_speed_menu_bagels() to get the mapping from aliases to menu item names.
# The aliases are stored in the `aliases` column of menu_items table.

# =============================================================================
# By-the-Pound Items and Categories
# =============================================================================

# Note: BY_POUND_ITEMS has been moved to the database.
# Items are loaded from menu_items with by_pound_category column set.
# Use get_by_pound_items() to get the category -> item names mapping.
# Use find_by_pound_item() to look up an item by name or alias.

# Note: BY_POUND_CATEGORY_NAMES has been moved to the database.
# Category display names are loaded from the by_pound_categories table.
# Use get_by_pound_category_names() to get the slug -> display_name mapping.

# Note: BY_POUND_PRICES has been moved to the database.
# Prices are now loaded via menu_index_builder._build_by_pound_prices()
# and accessed via PricingEngine.lookup_by_pound_price()

# =============================================================================
# Bagel Modifiers
# =============================================================================

# NOTE: BAGEL_PROTEINS, BAGEL_CHEESES, BAGEL_TOPPINGS have been moved to the database.
# Use get_proteins(), get_cheeses(), get_toppings() to access these from the
# ingredients table. Data is loaded at startup via MenuDataCache and includes
# both ingredient names and their aliases for matching user input.
#
# Example categories in ingredients table:
# - category='protein': bacon, ham, turkey, etc. with aliases (nova -> nova scotia salmon)
# - category='cheese': american cheese, swiss cheese, etc. with aliases
# - category='topping': tomato, onion, lettuce, etc. with aliases
# - category='sauce': mayo, mustard, hot sauce, etc. (also included in toppings)

# NOTE: BAGEL_SPREADS has been moved to the database.
# Use get_bagel_spreads() to access spread patterns for matching.
# Data is loaded from ingredients (category='spread') and cream cheese menu items.

# NOTE: MODIFIER_NORMALIZATIONS has been moved to the database.
# Use menu_cache.normalize_modifier() to normalize modifier names.
# Aliases are stored in the Ingredient.aliases column and loaded at startup.

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

# Greeting patterns
GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|howdy|yo)[\s!.,]*$",
    re.IGNORECASE
)

# Gratitude patterns - thank you, thanks, etc.
GRATITUDE_PATTERNS = re.compile(
    r"^(thanks?(\s+you)?|thank\s+you(\s+(so\s+)?much)?|ty|thx|appreciated?)[\s!.,]*$",
    re.IGNORECASE
)

# Done ordering patterns
DONE_PATTERNS = re.compile(
    r"^(that'?s?\s*(all|it)(\s+for\s+now)?|no(pe|thing)?(\s*(else|more))?|i'?m\s*(good|done|all\s*set)|"
    r"nothing(\s*(else|more))?|done|all\s*set|that\s*will\s*be\s*all|nah|"
    r"just\s+the\s+\w+(\s+\w+)?|just\s+that|only\s+the\s+\w+(\s+\w+)?)[\s!.,]*$",
    re.IGNORECASE
)

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
    # "actually X instead" / "actually make it X"
    # Negative lookahead excludes cancellation keywords so "actually cancel that" is NOT a change request
    (re.compile(r"actually\s+(?!cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off)(?:make\s+it\s+)?(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I meant X" / "I want X instead"
    (re.compile(r"(?:i\s+meant|i\s+want(?:ed)?)\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
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
# now loaded from the database via menu_data_cache._load_known_menu_items().
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
#   from sandwich_bot.menu_data_cache import menu_cache
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
# Category keyword mappings are now stored in the item_types table:
# - item_types.aliases: comma-separated keywords that map to this type
# - item_types.expands_to: JSON array of slugs for meta-categories
# - item_types.name_filter: substring filter for item names (e.g., "tea")
# - item_types.is_virtual: true for meta-categories without direct items
#
# To look up category keywords, use:
#   from sandwich_bot.menu_data_cache import menu_cache
#   category_info = menu_cache.get_category_keyword_mapping("desserts")
#   # Returns: {"slug": "dessert", "expands_to": ["pastry", "snack"], ...}
#
# To get all available category keywords (for error messages):
#   available = menu_cache.get_available_category_keywords()
#
# See migration: g7h8i9j0k1l2_add_category_keywords_to_item_types.py

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

# Recommendation inquiry patterns - these are QUESTIONS, not orders
# When matched, we should answer with recommendations but NOT add to cart
RECOMMENDATION_PATTERNS = [
    # General recommendations - catch-all patterns (order matters, specific first)
    (re.compile(r"what\s+(?:do\s+you|would\s+you|should\s+i|can\s+you)\s+recommend\??$", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular|the\s+best)\??$", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:most\s+)?popular\??$", re.IGNORECASE), "general"),
    (re.compile(r"what\s+(?:are\s+)?(?:your\s+)?(?:best|most\s+popular)\s+(?:sellers?|items?)", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?most\s+popular\s+item", re.IGNORECASE), "general"),
    (re.compile(r"(?:any|have\s+any|got\s+any|do\s+you\s+have\s+any)\s+recommendations?\??", re.IGNORECASE), "general"),
    (re.compile(r"(?:suggest|recommend)\s+(?:something|anything)", re.IGNORECASE), "general"),
    (re.compile(r"what\s+sells\s+best", re.IGNORECASE), "general"),
    # Bagel-specific recommendations
    (re.compile(r"what\s+(?:kind\s+of\s+)?bagels?\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "bagel"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+bagel", re.IGNORECASE), "bagel"),
    (re.compile(r"which\s+bagels?\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE), "bagel"),
    (re.compile(r"recommend\s+(?:a\s+)?bagel", re.IGNORECASE), "bagel"),
    (re.compile(r"(?:best|popular|favorite)\s+bagels?", re.IGNORECASE), "bagel"),
    (re.compile(r"what(?:'?s|\s+is)\s+popular\s+for\s+bagels?\??", re.IGNORECASE), "bagel"),
    # Sandwich-specific recommendations
    (re.compile(r"what\s+sandwi(?:ch|ches)\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "sandwich"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+sandwich", re.IGNORECASE), "sandwich"),
    (re.compile(r"which\s+sandwi(?:ch|ches)\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE), "sandwich"),
    (re.compile(r"recommend\s+(?:a\s+)?sandwich", re.IGNORECASE), "sandwich"),
    (re.compile(r"(?:best|popular|favorite)\s+sandwi(?:ch|ches)", re.IGNORECASE), "sandwich"),
    # Coffee-specific recommendations
    (re.compile(r"what\s+(?:kind\s+of\s+)?(?:coffee|drink)s?\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "coffee"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+(?:coffee|drink)", re.IGNORECASE), "coffee"),
    (re.compile(r"recommend\s+(?:a\s+)?(?:coffee|drink)", re.IGNORECASE), "coffee"),
    (re.compile(r"what\s+coffee\s+is\s+(?:popular|good|best)", re.IGNORECASE), "coffee"),
    # Breakfast/lunch recommendations
    (re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"what(?:'?s|\s+is)\s+good\s+for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"recommend\s+(?:something\s+)?for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+lunch", re.IGNORECASE), "lunch"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular)\s+for\s+lunch", re.IGNORECASE), "lunch"),
    (re.compile(r"recommend\s+(?:something\s+)?for\s+lunch", re.IGNORECASE), "lunch"),
]

# =============================================================================
# Item Description Inquiry Patterns
# =============================================================================

# =============================================================================
# String Normalization Utilities
# =============================================================================

def normalize_for_match(s: str) -> str:
    """
    Normalize a string for fuzzy matching.

    Handles variations like:
    - "blue berry" matching "blueberry"
    - "black and white" matching "black & white"

    Args:
        s: The string to normalize

    Returns:
        Normalized string with spaces removed and & converted to "and"
    """
    return s.replace("&", "and").replace(" ", "")


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
# These functions delegate to the MenuDataCache if loaded, otherwise return
# the hardcoded fallback values defined above. This allows the parsing logic
# to work even before the cache is initialized (e.g., during tests).


def _get_menu_cache():
    """Get the menu cache singleton, returns None if not available."""
    try:
        from sandwich_bot.menu_data_cache import menu_cache
        if menu_cache.is_loaded:
            return menu_cache
    except ImportError:
        pass
    return None


def get_spread_types() -> set[str]:
    """
    Get cream cheese variety types (scallion, honey walnut, etc.).

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_spread_types()
        if cached:
            return cached
    raise RuntimeError(
        "Spread types not available. Ensure menu_data_cache is loaded with spread data from the database."
    )


def get_spreads() -> set[str]:
    """
    Get base spread types (cream cheese, butter, etc.).

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_spreads()
        if cached:
            return cached
    raise RuntimeError(
        "Spreads not available. Ensure menu_data_cache is loaded with spread data from the database."
    )


def get_bagel_spreads() -> set[str]:
    """
    Get all spread patterns for matching in user input.

    Returns combined set of base spreads, spread types, and combined patterns
    (e.g., "cream cheese", "scallion", "scallion cream cheese").

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_bagel_spreads()
        if cached:
            return cached
    raise RuntimeError(
        "Bagel spreads not available. Ensure menu_data_cache is loaded with spread data from the database."
    )


def get_bagel_only_types() -> set[str]:
    """
    Get bagel types that are NOT also spread types (unambiguous bagel types).

    These are types where disambiguation is not needed - e.g., "plain" is only
    a bagel type, never a cream cheese flavor.

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_bagel_only_types()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Bagel-only types not available. Ensure menu_data_cache is loaded from the database."
    )


def get_spread_only_types() -> set[str]:
    """
    Get spread types that are NOT also bagel types (unambiguous spread types).

    These are types where disambiguation is not needed - e.g., "scallion" is only
    a cream cheese flavor, never a bagel type.

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_spread_only_types()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Spread-only types not available. Ensure menu_data_cache is loaded from the database."
    )


def get_ambiguous_modifiers() -> set[str]:
    """
    Get types that are BOTH bagel types AND spread types (need disambiguation).

    These are types like "blueberry" and "jalapeno" that exist as both bagel
    flavors and cream cheese flavors, requiring clarification from the user.

    Returns data from cache. Raises RuntimeError if cache not loaded.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_ambiguous_modifiers()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Ambiguous modifiers not available. Ensure menu_data_cache is loaded from the database."
    )


def get_bagel_types() -> set[str]:
    """
    Get bagel types (plain, everything, etc.) from the database.

    Returns data from cache if loaded (includes item names and aliases).
    Falls back to common bagel types if cache not available.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_bagel_types()
        if cached:
            return cached
    return set()


def get_bagel_types_list() -> list[str]:
    """
    Get ordered list of bagel types for display/pagination.

    Returns data from cache if loaded, otherwise returns empty list.
    Unlike get_bagel_types() which returns a set with aliases,
    this returns an ordered list without aliases for display purposes.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.get_bagel_types_list()
    return []


def get_proteins() -> set[str]:
    """
    Get protein types (bacon, ham, etc.) from the database.

    Returns data from cache which includes both ingredient names and
    their aliases (e.g., "nova" and "lox" both map to Nova Scotia Salmon).

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_proteins()
        if cached:
            return cached
    raise RuntimeError(
        "Proteins not available. Ensure menu_data_cache is loaded with protein data from the database."
    )


def get_toppings() -> set[str]:
    """
    Get topping types (tomato, onion, etc.) from the database.

    Returns data from cache which includes both ingredient names and
    their aliases. Also includes sauces (mayo, mustard, etc.) which
    function as toppings on bagels.

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_toppings()
        if cached:
            return cached
    raise RuntimeError(
        "Toppings not available. Ensure menu_data_cache is loaded with topping data from the database."
    )


def get_cheeses() -> set[str]:
    """
    Get sliced cheese types (american, swiss, etc.) from the database.

    Returns data from cache which includes both ingredient names and
    their aliases. Only returns actual sliced cheeses, not cream cheese
    spreads which are in the "spread" category.

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_cheeses()
        if cached:
            return cached
    raise RuntimeError(
        "Cheeses not available. Ensure menu_data_cache is loaded with cheese data from the database."
    )


# Note: _FALLBACK_BAGEL_TYPES and _FALLBACK_COFFEE_TYPES were removed.
# Bagel and coffee types are now loaded from the database.
# If the cache is not available, functions return empty sets and fail gracefully.


def get_coffee_types() -> set[str]:
    """
    Get coffee/tea beverage types from the database.

    Returns data from cache if loaded (includes item names and aliases).
    Falls back to common coffee types if cache not available.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_coffee_types()
        if cached:
            return cached
    return set()


def get_soda_types() -> set[str]:
    """
    Get soda/bottled beverage types from the database.

    Returns data from cache if loaded (includes item names and aliases).
    Returns empty set if cache not available.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_soda_types()
        if cached:
            return cached
    return set()


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


def get_speed_menu_bagels() -> dict[str, str]:
    """
    Get speed menu bagel alias mapping from database.

    Returns a dict mapping user input variations (aliases) to the actual
    menu item names in the database. This is used for recognizing orders
    like "bec", "bacon egg and cheese", "the classic", etc.

    Returns:
        Dict mapping lowercase alias -> menu item name (with original casing).

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_speed_menu_bagels()
        if cached is not None:
            return cached
    raise RuntimeError(
        "Speed menu bagels not available. Ensure menu_data_cache is loaded from the database."
    )


def get_by_pound_items() -> dict[str, list[str]]:
    """
    Get by-the-pound items organized by category from database.

    Returns a dict mapping category names (fish, spread, cheese, cold_cut, salad)
    to lists of item names available in that category.

    Returns:
        Dict mapping category -> list of item names.

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_by_pound_items()
        if cached:  # Empty dict means cache not loaded
            return cached
    raise RuntimeError(
        "By-pound items not available. Ensure menu_data_cache is loaded from the database."
    )


def find_by_pound_item(item_name: str) -> tuple[str, str] | None:
    """
    Find a by-pound item and its category by name or alias.

    Args:
        item_name: Item name or alias to look up (e.g., "lox", "nova", "whitefish salad")

    Returns:
        Tuple of (canonical_name, category) if found, None otherwise.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.find_by_pound_item(item_name)
    return None


def get_by_pound_category_names() -> dict[str, str]:
    """
    Get by-the-pound category display names from database.

    Returns a dict mapping category slugs (cheese, cold_cut, fish, salad, spread)
    to human-readable display names (cheeses, cold cuts, smoked fish, salads, spreads).

    Returns:
        Dict mapping category slug -> display name.

    Raises:
        RuntimeError: If menu cache is not loaded. There is no fallback -
            code should fail if database isn't properly set up.
    """
    cache = _get_menu_cache()
    if cache:
        cached = cache.get_by_pound_category_names()
        if cached:  # Empty dict means cache not loaded
            return cached
    raise RuntimeError(
        "By-pound category names not available. Ensure menu_data_cache is loaded from the database."
    )


def resolve_coffee_alias(name: str) -> str:
    """
    Resolve a coffee/tea name or alias to its canonical menu item name.

    Args:
        name: User input like "matcha" or "latte"

    Returns:
        Canonical menu item name (e.g., "Seasonal Latte Matcha" for "matcha")
        or the original name if no mapping found.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.resolve_coffee_alias(name)
    return name


def resolve_soda_alias(name: str) -> str:
    """
    Resolve a soda/beverage name or alias to its canonical menu item name.

    Args:
        name: User input like "coke" or "sprite"

    Returns:
        Canonical menu item name (e.g., "Coca-Cola" for "coke")
        or the original name if no mapping found.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.resolve_soda_alias(name)
    return name


def find_spread_matches(query: str) -> list[str]:
    """
    Find spread types that match a partial query.

    Uses the cache's keyword index for efficient partial matching.
    Falls back to simple substring matching if cache not available.

    Args:
        query: User input like "walnut" or "honey walnut"

    Returns:
        List of matching spread types.
        Empty list if no matches.
        Single item if exact match.
        Multiple items if disambiguation needed.

    Examples:
        >>> find_spread_matches("walnut")
        ["honey walnut", "maple raisin walnut"]
        >>> find_spread_matches("scallion")
        ["scallion"]
    """
    cache = _get_menu_cache()
    if cache:
        return cache.find_spread_matches(query)

    raise RuntimeError(
        "Spread matching not available. Ensure menu_data_cache is loaded with spread data from the database."
    )


def find_bagel_matches(query: str) -> list[str]:
    """
    Find bagel types that match a partial query.

    Args:
        query: User input like "cinnamon" or "whole wheat"

    Returns:
        List of matching bagel types, or empty list if cache not available.
    """
    cache = _get_menu_cache()
    if cache:
        return cache.find_bagel_matches(query)
    return []
