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
import random
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
# Filler Words and Skip Words - SINGLE SOURCE OF TRUTH
# =============================================================================
# All filler/skip word definitions are consolidated here to avoid duplication
# and inconsistency across the codebase.
#
# Note: Basic skip words (SKIP_WORDS_BASIC, etc.) are defined in cache/base.py
# to avoid circular imports, and re-exported here.

# Category 0: MID_SENTENCE_HESITATION_FILLERS - Strip from ANYWHERE in input
# Pure hesitation sounds that never appear in food/menu item names.
# Safe to strip mid-sentence because they are meaningless noise sounds.
# e.g., "Can uh you add skim" -> "Can you add skim"
MID_SENTENCE_HESITATION_FILLERS = frozenset({
    "uh", "um", "er", "err", "hm", "hmm", "mm", "mmm",
    "ah", "aha", "umm", "ummm", "hmmm", "uhh",
    # Extended variants - users type variable-length hesitation sounds
    "hmmmm", "hmmmmm", "mmmm", "mmmmm", "uhhh", "uhhhh",
    "ummmm", "errr",
    # Polite filler - safe mid-sentence, never appears in food names
    "please",
})

# Category 1: HESITATION_FILLERS - Strip from START of input only
# Conversational hesitation/thinking sounds that add no ordering meaning.
# These are single words or short phrases that when followed by comma/space
# don't contribute to the order meaning.
#
# Note: Multi-word phrases like "let me", "i mean", "you know" are NOT included
# here because they're often part of meaningful phrases ("let me think",
# "I mean a latte"). Those are handled by ORDERING_PREFIXES or context-specific
# patterns in intent_patterns.py.
HESITATION_FILLERS = frozenset({
    # Existing fillers
    "actually", "never mind", "nevermind", "oh", "wait", "um", "uh", "hmm",
    "well", "so", "ok", "okay", "hey", "like", "sorry",
    # Informal affirmative/negative
    "yeah", "yep", "yup", "nah", "nope", "sure", "alright", "right",
    # Hesitation sounds and variants
    "er", "err", "hm", "mm", "mmm", "ah", "aha",
    "umm", "ummm", "hmmm", "uhh",
    # Extended variants - users type variable-length hesitation sounds
    "hmmmm", "hmmmmm", "mmmm", "mmmmm", "uhhh", "uhhhh",
    "ummmm", "errr",
    # Discourse markers
    "basically", "honestly", "literally",
    # Greetings used as filler before orders
    "hi", "hello", "hi there", "hey there", "howdy", "yo",
    # Polite interjections
    "please", "thanks", "thank you", "thx", "excuse me", "pardon", "pardon me",
    # Topic changers
    "anyway", "anyways",
})

# Category 2: ORDERING_PREFIXES - Strip from START of input only
# Phrases that begin orders but don't add meaning
ORDERING_PREFIXES = frozenset({
    "i want", "i'd like", "i need", "i'll have", "i'll take",
    "can i get", "can i have", "could i get", "could i have",
    "give me", "gimme", "get me", "make it", "let's go with", "let's do",
    "just", "some",
})

# Category 3: ARTICLES_AND_CONNECTORS - Context-dependent
# Sometimes stripped, sometimes needed for item name matching
ARTICLES = frozenset({'the', 'a', 'an', 'some'})
CONNECTORS = frozenset({'and', 'or', 'with', 'plus'})
PREPOSITIONS = frozenset({'on', 'in', 'to', 'of', 'for'})

# Category 4: POLITENESS_WORDS - Strip anywhere in input
POLITENESS_WORDS = frozenset({'please', 'thanks', 'thank you', 'thx'})

# =============================================================================
# Combined Skip Word Sets for Different Contexts
# =============================================================================
# Import base skip words from cache.base to avoid circular imports
# (cache.base cannot import from here, so the canonical definitions live there)
from orderbot.cache.base import (
    SKIP_WORDS_BASIC,
    SKIP_WORDS_CONJUNCTIONS,
    SKIP_WORDS_PREPOSITIONS,
)

# Additional filler words for parsing
SKIP_WORDS_FILLER = frozenset({'please', 'thanks', 'it', 'that', 'yes', 'no'})

# Combined set for general-purpose parsing (tokenization, keyword indexing)
SKIP_WORDS = SKIP_WORDS_BASIC | SKIP_WORDS_CONJUNCTIONS | SKIP_WORDS_PREPOSITIONS | SKIP_WORDS_FILLER

# For tokenization: skip words when classifying tokens
TOKENIZATION_SKIP_WORDS = frozenset({
    "please", "thanks", "thank", "you", "with", "the", "some", "of"
})

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
    r"^make\s+it\s+",  # "make it 3 eggs"
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
    (re.compile(r"actually\s+(?!cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off|no\s+)(?:make\s+it\s+)?(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I meant X" - clearly signals correction
    (re.compile(r"i\s+meant\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I want X instead" - requires "instead" to signal change (without "instead", treat as answer)
    (re.compile(r"i\s+want(?:ed)?\s+(.+?)\s+instead(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "no wait, X" / "wait, X instead"
    (re.compile(r"(?:no\s+)?wait[,.]?\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "make the bagel not toasted" - negate boolean attribute on specific item
    (re.compile(r"(?:make|have)\s+(?:the|my)\s+(\w+(?:\s+\w+)?)\s+(not\s+\w+)(?:\s+please)?(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "make it not toasted" - negate boolean attribute on implicit target
    (re.compile(r"(?:make|have)\s+(?:it|that)\s+(not\s+\w+)(?:\s+please)?(?:\?|$)", re.IGNORECASE), (None, 1)),
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


