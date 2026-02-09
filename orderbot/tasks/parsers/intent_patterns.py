"""
Intent Patterns.

Regex patterns for detecting user intents/actions:
- Replace/change item
- Cancel/remove item
- Quantity changes (make it N, reduce to one, one more)
- Duplicate operations
- Order status queries
- Tax questions
- Ordering language detection
- Configurable item detection
"""

import re
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Replace Item Patterns
# =============================================================================

# Replace item patterns: "make it a X instead", "change it to X", "actually X instead", etc.
REPLACE_ITEM_PATTERN = re.compile(
    r"^(?:"
    # "make it X", "make that X", "make this X" - requires "make it/that/this"
    r"make\s+(?:it|that|this)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "can you make it X?", "could you make it X?" - requires "can/could you make it/that/this"
    r"(?:can|could)\s+you\s+make\s+(?:it|that|this)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "change it to X", "change to X" - requires "change"
    r"change\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "switch to X", "switch it to X" - requires "switch"
    r"switch\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "swap for X", "swap it for X" - requires "swap"
    r"swap\s+(?:it\s+)?(?:for\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "replace with X", "replace it with X" - requires "replace"
    r"replace\s+(?:it\s+)?(?:with\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "actually X", "no X", "nope X", "wait X" - requires one of these words
    r"(?:actually|nope|wait)[,]?\s+(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "no X" but NOT "no more X" (cancellation) or "no, I said/meant X" (handled separately)
    r"no[,]?\s+(?!more\s)(?!i\s+(?:said|meant)\s)(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "i meant X", "i said X", "no, i said X" - requires "i meant" or "i said"
    r"(?:no[,]?\s+)?i\s+(?:meant|said)\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "X instead" - requires "instead" at end
    r"(?:a\s+)?(.+?)\s+instead[\s!.,?]*$"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Cancel/Remove Item Patterns
# =============================================================================

CANCEL_ITEM_PATTERN = re.compile(
    r"^(?:"
    r"cancel\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"remove\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"delete\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"clear\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"take\s+(?:off\s+)?(?:the\s+)?(.+?)(?:\s+off)?[\s!.,]*$"
    r"|"
    r"never\s*mind\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"forget\s+(?:about\s+)?(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"scratch\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"(?:i\s+)?don'?t\s+want\s+(?:the\s+)?(.+?)(?:\s+anymore)?[\s!.,]*$"
    r"|"
    r"no\s+more\s+(.+?)[\s!.,]*$"
    r"|"
    # "can you remove X?", "could you remove X?", "would you remove X?"
    r"(?:can|could|would)\s+you\s+(?:remove|delete|cancel|take\s+off)\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "can I remove X?", "could we cancel X?"
    r"(?:can|could)\s+(?:i|we)\s+(?:remove|delete|cancel|take\s+off)\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "please remove X", "please cancel X"
    r"please\s+(?:remove|delete|cancel|take\s+off)\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Filler Words Pattern
# =============================================================================

# Import consolidated hesitation fillers from constants
from .constants import HESITATION_FILLERS


def _build_filler_pattern() -> re.Pattern:
    """Build regex pattern from HESITATION_FILLERS set.

    Special handling:
    - "actually" only matches with comma OR before cancel/remove words
    - "never mind" / "nevermind" only matches with comma
    - Single words match with comma or whitespace after
    - Multi-word phrases match with optional comma/whitespace after
    """
    # Special cases that need context-aware matching
    special_patterns = [
        r"actually,\s*",  # "actually," with comma is filler
        r"actually\s+(?=cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off)",
        r"never\s*mind,\s*",  # "never mind," when followed by another command
    ]

    # Words to exclude from generic pattern (handled specially above)
    special_words = {"actually", "never mind", "nevermind"}

    # Build patterns for remaining fillers
    generic_patterns = []
    for filler in sorted(HESITATION_FILLERS, key=len, reverse=True):
        if filler in special_words:
            continue
        # Escape regex special chars
        escaped = re.escape(filler)
        # Match with comma or whitespace after
        generic_patterns.append(rf"{escaped}[,\s]+")

    # Combine all patterns
    all_patterns = special_patterns + generic_patterns
    pattern_str = r"^(?:" + "|".join(all_patterns) + r")"

    return re.compile(pattern_str, re.IGNORECASE)


# Filler words pattern - words that add no meaning and should be stripped before parsing
FILLER_WORDS_PATTERN = _build_filler_pattern()


def strip_conversational_fillers(text: str) -> str:
    """Remove conversational filler words from the start of user input.

    Strips hesitation markers and conversational fillers that appear at the
    beginning of user input, such as "um", "uh", "actually,", "wait,", etc.

    Unlike normalization.strip_filler_words() which removes articles and
    ordering phrases from anywhere in the text, this function specifically
    handles conversational hesitation at the start of input.

    Args:
        text: User input text

    Returns:
        Text with leading conversational fillers removed

    Examples:
        >>> strip_conversational_fillers("um, I want a bagel")
        "I want a bagel"
        >>> strip_conversational_fillers("actually, make it two")
        "make it two"
        >>> strip_conversational_fillers("wait, cancel that")
        "cancel that"
    """
    result = text
    while True:
        match = FILLER_WORDS_PATTERN.match(result)
        if match:
            result = result[match.end():].strip()
        else:
            break
    return result


# =============================================================================
# Quantity Change Patterns
# =============================================================================

# "Make it 2" pattern - user wants to change quantity of last item to N
MAKE_IT_N_PATTERN = re.compile(
    r"^(?:"
    r"actually[,]?\s+make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"i'?ll\s+(?:take|have|want|get)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"i'?d\s+like\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)(?:\s+of\s+(?:those|them|that))?"
    r"|"
    r"i\s+would\s+like\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)(?:\s+of\s+(?:those|them|that))?"
    r"|"
    r"i\s+(?:want|need)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(?:can|could|may)\s+i\s+(?:get|have)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"actually[,]?\s+(?:let'?s?\s+(?:do|get|have)\s+)?(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(?:give|get)\s+me\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"let'?s?\s+(?:do|have|get|make\s+it)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+of\s+(?:those|them|that)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# Variant of MAKE_IT_N_PATTERN for use during CONFIGURING_ITEM phase
# This pattern allows optional trailing text (the item name) after the quantity
# e.g., "make it two hot teas" when being asked about tea flavor
# The item name is ignored since we already know which item we're configuring
MAKE_IT_N_CONFIG_PATTERN = re.compile(
    r"^(?:"
    r"actually[,]?\s+make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "can you make it two" / "could you make that three"
    r"(?:can|could|would)\s+you\s+make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"i'?ll\s+(?:take|have|want|get)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"i'?d\s+like\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)(?:\s+of\s+(?:those|them|that))?"
    r"|"
    r"i\s+would\s+like\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)(?:\s+of\s+(?:those|them|that))?"
    r"|"
    r"i\s+(?:want|need)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(?:can|could|may)\s+i\s+(?:get|have)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"actually[,]?\s+(?:let'?s?\s+(?:do|get|have)\s+)?(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(?:give|get)\s+me\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"let'?s?\s+(?:do|have|get|make\s+it)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    r"(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+of\s+(?:those|them|that)"
    r")"
    # Allow optional trailing item name (e.g., "hot teas", "plain bagels")
    r"(?:\s+[\w\s]+)?[\s!.,?]*$",
    re.IGNORECASE
)

# "just one" / "only one" pattern - reduces quantity to 1
REDUCE_TO_ONE_PATTERN = re.compile(
    r"^(?:"
    r"actually\s+(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    r"(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    r"make\s+(?:it|that)\s+(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    r"i\s+(?:only|just)\s+(?:want|need|wanted)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    r"(?:one|1)(?:\s+(\w+))?\s+is\s+(?:enough|fine|good)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "one more" / "another" pattern - adds 1 more of the last item
ONE_MORE_PATTERN = re.compile(
    r"^(?:"
    r"(?:and\s+)?one\s+more(?:\s+of\s+(?:those|them|that))?"
    r"|"
    r"(?:and\s+)?another(?:\s+one(?:\s+of\s+(?:those|them|that))?)?"
    r"|"
    r"add\s+(?:one\s+more|another)"
    r"|"
    r"(?:one|1)\s+more\s+(?:of\s+)?(?:those|them|that)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# Generic pattern for "another X" / "one more X"
# Captures multi-word item names (e.g., "another 6 bagel package")
ANOTHER_ITEM_PATTERN = re.compile(
    r"^(?:and\s+)?(?:one\s+more|another)\s+"
    r"(.+?)"  # Capture multi-word item names including numbers
    r"[\s!.,?]*$",
    re.IGNORECASE
)


# =============================================================================
# Duplicate Patterns
# =============================================================================

# "all items" / "everything" pattern for duplicating entire cart
DUPLICATE_ALL_PATTERN = re.compile(
    r"^(?:"
    r"all\s+(?:the\s+)?(?:items?|of\s+(?:them|those)|things?)"
    r"|"
    r"everything(?:\s+(?:in\s+(?:the\s+)?(?:cart|order)|again))?"
    r"|"
    r"(?:the\s+)?(?:whole|entire)\s+(?:order|cart)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "more X" pattern where X references a cart item (e.g., "more chips", "more of those chips")
# This should be checked BEFORE MORE_MENU_ITEMS_PATTERNS to catch cart item references
MORE_OF_SAME_PATTERN = re.compile(
    r"^more\s+(?:of\s+(?:the|those|them|that)\s+)?(.+?)[\s!.,?]*$",
    re.IGNORECASE
)

# "make it/that N [item]" pattern - quantity change with trailing item reference
# e.g., "make that two bags of chips", "make it 3 coffees"
# This is more specific than MAKE_IT_N_PATTERN and captures the item reference
MAKE_IT_N_WITH_ITEM_PATTERN = re.compile(
    r"^make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"\s+(.+?)"  # Capture the item reference
    r"[\s!.,?]*$",
    re.IGNORECASE
)


# =============================================================================
# Configuration Request Patterns
# =============================================================================

# "Can you make it X?" pattern for configuration
CAN_YOU_MAKE_IT_PATTERN = re.compile(
    r"^(?:"
    r"(?:can|could)\s+(?:you|i)\s+(?:make|get|have)\s+(?:it|that|this)\s+(.+?)"
    r"|"
    r"(?:is|are)\s+(?:it|that|this|they)\s+available\s+(.+?)"
    r"|"
    r"(?:do|does)\s+(?:it|that|this)\s+come\s+(?:in\s+)?(.+?)"
    r"|"
    # Direct "make it X" without "can you" prefix
    r"(?:make|change|switch)\s+(?:it|that|this)\s+(?:to\s+)?(?:a\s+)?(.+?)"
    r"|"
    # "actually make it X" variation
    r"actually\s+(?:make|change)\s+(?:it|that|this)\s+(?:to\s+)?(?:a\s+)?(.+?)"
    r")"
    r"[\s?!.,]*$",
    re.IGNORECASE
)


def parse_can_you_make_it(text: str) -> str | None:
    """Parse 'can you make it X?' style requests and extract the modifier."""
    match = CAN_YOU_MAKE_IT_PATTERN.match(text.strip())
    if match:
        modifier = next((g for g in match.groups() if g), None)
        if modifier:
            return modifier.strip().rstrip('?.,!')
    return None


# =============================================================================
# Order/Tax Status Patterns
# =============================================================================

# Tax question pattern
TAX_QUESTION_PATTERN = re.compile(
    r"(?:"
    r"what(?:'?s| is)\s+(?:my|the)\s+total\s+(?:with|including)\s+tax"
    r"|"
    r"how\s+much\s+(?:will\s+it\s+be\s+)?(?:with|including)\s+tax"
    r"|"
    r"what(?:'?s| is)\s+(?:my|the)\s+total"
    r"|"
    r"(?:the\s+)?total\s+(?:with|including)\s+tax"
    r"|"
    r"(?:with|including)\s+tax\??"
    r")",
    re.IGNORECASE
)

# Order status pattern
ORDER_STATUS_PATTERN = re.compile(
    r"(?:"
    r"what(?:'?s| is)\s+(?:my|the)\s+order"
    r"|"
    r"what(?:'?s| is| do i have)\s+in\s+(?:my|the)\s+(?:cart|order)"
    r"|"
    r"what\s+(?:have\s+i|did\s+i)\s+order"
    r"|"
    r"(?:read|say)\s+(?:back\s+)?(?:my|the)\s+order"
    r"|"
    r"repeat\s+(?:my|the)\s+order\s+back"
    r"|"
    r"(?:can|could)\s+you\s+(?:read|repeat|tell\s+me)\s+(?:my|the)\s+order"
    r"|"
    r"(?:my\s+)?order\s+so\s+far"
    r"|"
    r"what\s+(?:do\s+i\s+have|have\s+i\s+got)\s+so\s+far"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Add More Patterns
# =============================================================================

ADD_MORE_PATTERN = re.compile(
    r"(?:can\s+you\s+|could\s+you\s+|please\s+)?"
    r"(?:add|throw\s+in|get\s+me|give\s+me|i(?:'?d|\s+would)?\s+(?:like|want))"
    r"\s+"
    r"(?:"
    r"(?:a\s+)?(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"|"
    r"(?:another|one\s+more|an?\s+additional)"
    r")"
    r"(?:\s+(?:one|1))?"
    r"(?:\s+(.+?))?$",
    re.IGNORECASE
)


# =============================================================================
# Ordering Language Pattern
# =============================================================================

ORDERING_LANGUAGE_PATTERN = re.compile(
    r"(?:"
    r"i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)"
    r"|(?:can|could|may)\s+i\s+(?:get|have)"
    r"|give\s+me"
    r"|let\s*(?:me|'s)\s*(?:get|have)"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Add Item During Config Pattern
# =============================================================================

# Pattern to detect ordering prefixes that indicate a new item during configuration.
# This only matches the PREFIX - the rest is parsed by parse_open_input_deterministic().
# Examples: "and a latte", "also a bagel", "plus a coffee", "I'd also like a muffin"
ADD_ITEM_DURING_CONFIG_PREFIX = re.compile(
    r"^(?:"
    # "and a/an/the X", "and two X"
    r"and\s+(?:a(?:n)?|the|\d+|two|three|four|five)\s+"
    r"|"
    # "also a/an/the X", "also X" (no article)
    r"also\s+(?:a(?:n)?|the)?\s*"
    r"|"
    # "plus a/an/the X"
    r"plus\s+(?:a(?:n)?|the)?\s*"
    r"|"
    # "I'd also like X", "I would also like X", "I also want X"
    r"i(?:'?d|\s+would)?\s+also\s+(?:like|want)\s+"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Configurable Item Pattern (Lazy Built from Database)
# =============================================================================

_CONFIGURABLE_ITEM_PATTERN_CACHE: re.Pattern | None = None


def _get_menu_cache():
    """Get the menu cache singleton, returns None if not available."""
    try:
        from orderbot.cache import menu_cache
        if menu_cache.is_loaded:
            return menu_cache
    except ImportError:
        pass
    return None


def _get_configurable_item_pattern() -> re.Pattern:
    """Get regex pattern for detecting configurable item orders from database.

    Builds a unified pattern matching item type triggers and attribute options.
    """
    global _CONFIGURABLE_ITEM_PATTERN_CACHE
    if _CONFIGURABLE_ITEM_PATTERN_CACHE is not None:
        return _CONFIGURABLE_ITEM_PATTERN_CACHE

    cache = _get_menu_cache()
    if not cache:
        # Return a pattern that matches nothing if cache not loaded
        return re.compile(r"(?!)")

    keywords: set[str] = set()

    # 1. Item type triggers
    all_triggers = cache.get_item_type_triggers()
    for triggers in all_triggers.values():
        keywords.update(triggers)

    # 2. Attribute option words
    attr_options = cache.get_all_attribute_option_words()
    keywords.update(attr_options.keys())

    # 3. Item names from configurable types
    configurable_names = cache.get_configurable_item_names()
    keywords.update(configurable_names)

    # Filter empty strings and very short words
    keywords = {k for k in keywords if k and len(k) >= 2}

    # Sort by length descending
    sorted_keywords = sorted(keywords, key=len, reverse=True)

    # Build pattern
    keywords_pattern = "|".join(re.escape(k) for k in sorted_keywords)
    _CONFIGURABLE_ITEM_PATTERN_CACHE = re.compile(
        rf"\b({keywords_pattern})\b",
        re.IGNORECASE
    )
    return _CONFIGURABLE_ITEM_PATTERN_CACHE


def warmup_patterns() -> None:
    """Pre-compile lazy patterns at startup."""
    _get_configurable_item_pattern()
