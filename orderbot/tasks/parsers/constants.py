"""
Parser Constants.

This module contains constants used by both LLM and deterministic parsers
for recognizing and normalizing user input.

Sub-modules:
- selection_patterns: Ordinal words and list selection patterns
- inquiry_patterns: Price, store, recommendation, description inquiry patterns
- intent_patterns: Replace, cancel, quantity, duplicate, order status patterns
- parser_utils: Runtime helper functions (small talk, redirects, menu cache, sentinels)
"""

import re

# =============================================================================
# Pagination Configuration
# =============================================================================

# Standard pagination size for all list displays
DEFAULT_PAGINATION_SIZE = 5

# =============================================================================
# Weight Quantity Patterns
# =============================================================================

# Matches "half a pound", "a half pound", "1/2 lb", etc.
HALF_POUND_PATTERN = re.compile(
    r"^(?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)s?$|^1\s*/\s*2\s*(?:pound|lb)s?$",
    re.IGNORECASE,
)

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
# Note: Basic skip words (SKIP_WORDS_BASIC, etc.), ARTICLES, ORDERING_PREFIXES,
# CONNECTORS, PREPOSITIONS, and POLITENESS_WORDS are imported from
# orderbot/tasks/shared_constants.py (a pure module with no project imports).

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
    # Discourse markers - safe mid-sentence, never appear in food names
    "basically", "honestly", "literally",
    # Vocatives / address terms - never appear in food names
    "sir", "ma'am", "madam", "dude", "man",
    "bro", "bruh", "boss", "buddy", "bud",
    "mate", "chief", "pal", "fam",
})

# Category 1: HESITATION_FILLERS - Strip from START of input only
# Build from MID_SENTENCE_HESITATION_FILLERS plus start-of-input-only extras.
HESITATION_FILLERS = MID_SENTENCE_HESITATION_FILLERS | frozenset({
    # Conversational fillers
    "actually", "never mind", "nevermind", "oh", "wait",
    "well", "so", "ok", "okay", "hey", "like", "sorry",
    # Informal affirmative/negative
    "yeah", "yep", "yup", "nah", "nope", "sure", "alright", "right",
    # Discourse markers
    "basically", "honestly", "literally",
    # Greetings used as filler before orders
    "hi", "hello", "hi there", "hey there", "howdy", "yo",
    # Polite interjections
    "thanks", "thank you", "thx", "excuse me", "pardon", "pardon me",
    # Topic changers
    "anyway", "anyways",
    # Retraction fillers - "no wait, untoasted" means hesitation, not cancellation
    "no wait", "no, wait",
    "no, but", "no but",
    "scratch that",
})

# Category 2–4: Shared constants imported from the pure shared_constants module.
# Previously defined inline here and/or imported from cache.base. Consolidated
# into shared_constants.py to eliminate duplication and circular import chains.
from orderbot.tasks.shared_constants import (
    ORDERING_PREFIXES,
    ARTICLES,
    CONNECTORS,
    PREPOSITIONS,
    POLITENESS_WORDS,
    SKIP_WORDS_BASIC,
    SKIP_WORDS_CONJUNCTIONS,
    SKIP_WORDS_PREPOSITIONS,
)

# =============================================================================
# Combined Skip Word Sets for Different Contexts
# =============================================================================

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
# Re-exports from parser_utils (public API surface)
# =============================================================================
from .parser_utils import (  # noqa: F401
    match_small_talk,
    get_order_redirect,
    clean_extracted_text,
    get_item_type_display_name,
    _get_menu_cache,
    get_known_menu_items,
    get_items_with_defaults_aliases,
    find_item_by_unit_type,
    CANCEL_LAST_ITEM,
    CANCEL_ALL_ITEMS,
    CANCEL_LAST_N_PREFIX,
    REDUCE_TO_ONE,
    REDUCE_TO_ONE_PREFIX,
    make_last_n_sentinel,
    parse_last_n_sentinel,
    make_reduce_to_one_sentinel,
    parse_reduce_to_one_sentinel,
)

# Note: CHANGE_REQUEST_PATTERNS moved to intent_patterns.py.
# Cannot re-export here due to circular import. Import directly from intent_patterns.
