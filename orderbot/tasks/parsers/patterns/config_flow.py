"""
Configuration Flow Patterns.

Regex patterns for detecting configuration-related intents:
- "Can you make it X?" requests
- "Make the [item] a [modifier]" requests
- Done ordering during config
- Add item during config
- Configurable item detection (lazy built from database)
"""

import re
import logging

from orderbot.tasks.parsers.parser_utils import _get_menu_cache

logger = logging.getLogger(__name__)


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
    r"(?:make|change)\s+(?:it|that|this)\s+(?:to\s+)?(?:a\s+)?(.+?)"
    r"|"
    # "switch to X", "switch it to X" - pronoun optional when "to" is present
    r"switch\s+(?:(?:it|that|this)\s+)?to\s+(?:a\s+)?(.+?)"
    r"|"
    # "actually make it X" variation
    r"actually\s+(?:make|change|switch)\s+(?:it|that|this)\s+(?:to\s+)?(?:a\s+)?(.+?)"
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


# "make the [ITEM] (a) [MODIFIER]" pattern for modifying a specific named item
# e.g., "make the fruit salad a large", "can you make the fruit salad a large?"
# "change the fruit salad to a large", "upgrade the bagel to plain"
# Captures two groups: (item_name, modifier)
MAKE_NAMED_ITEM_PATTERN = re.compile(
    r"^(?:"
    # "make the [ITEM] (a) [MOD]"
    r"(?:can|could)\s+you\s+make\s+the\s+(.+?)\s+(?:a\s+)?(\w+)"
    r"|"
    r"make\s+the\s+(.+?)\s+(?:a\s+)?(\w+)"
    r"|"
    # "change/upgrade the [ITEM] to (a) [MOD]"
    r"(?:change|upgrade|switch)\s+the\s+(.+?)\s+to\s+(?:a\s+)?(\w+)"
    r")"
    r"[\s?!.,]*$",
    re.IGNORECASE
)


def parse_make_named_item(text: str) -> tuple[str, str] | None:
    """Parse 'make the [item] a [modifier]' style requests.

    Args:
        text: User input text.

    Returns:
        Tuple of (item_name, modifier) if matched, None otherwise.
    """
    match = MAKE_NAMED_ITEM_PATTERN.match(text.strip())
    if not match:
        return None
    groups = match.groups()
    # Groups come in pairs: (item1, mod1, item2, mod2, item3, mod3)
    for i in range(0, len(groups), 2):
        if groups[i] is not None and groups[i + 1] is not None:
            item_name = groups[i].strip().rstrip('?.,!')
            modifier = groups[i + 1].strip().rstrip('?.,!')
            if item_name and modifier:
                return (item_name, modifier)
    return None


# =============================================================================
# Done Ordering During Config Pattern
# =============================================================================

# Explicit "finish my order" type phrases that are unambiguous even during item configuration.
# Short patterns like "done" or "that's it" are NOT included because they're ambiguous
# during config (could mean "done with this item's options"). Only phrases containing
# "order"/"checkout"/"pay" language are matched here.
DONE_ORDERING_DURING_CONFIG_PATTERN = re.compile(
    r"^(?:"
    # "finish/complete/finalize my order"
    r"(?:finish|complete|finalize)\s+(?:my|the|this)\s+order"
    r"|"
    # "that's it/all for my order"
    r"that'?s?\s+(?:it|all)\s+(?:for|with)\s+(?:my|the|this)\s+order"
    r"|"
    # "done ordering" / "done with my order" / "done with the order"
    r"done\s+(?:ordering|with\s+(?:my|the|this)\s+order)"
    r"|"
    # "i'm done ordering" / "i'm done with my order"
    r"i'?m\s+done\s+(?:ordering|with\s+(?:my|the|this)\s+order)"
    r"|"
    # "place/submit my order"
    r"(?:place|submit)\s+(?:my|the|this)\s+order"
    r"|"
    # "check out" / "checkout"
    r"check\s*out"
    r"|"
    # "ready to pay/checkout/order"
    r"(?:i'?m\s+)?ready\s+to\s+(?:pay|check\s*out|order|finish)"
    r"|"
    # "let's wrap it up" / "finish up" / "wrap up my order"
    r"(?:let'?s?\s+)?(?:wrap|finish)\s+(?:it\s+)?up"
    r"|"
    # "no more items" / "nothing else to add"
    r"no\s+more\s+items"
    r"|"
    r"nothing\s+(?:else|more)\s+to\s+(?:add|order)"
    r"|"
    # "I want to pay" / "I'd like to pay" / "can I pay"
    r"(?:i\s+want|i'?d\s+like|can\s+i|let\s+me)\s+(?:to\s+)?(?:pay|check\s*out)"
    r")"
    r"[\s!.,?]*$",
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
    # "I'd also like/want/have/get/take X", "I would also like X", "I also want X"
    r"i(?:'?d|\s+would)?\s+also\s+(?:like|want|have|get|take|need)\s+(?:a(?:n)?\s+)?"
    r"|"
    # "I'll also have/get/take X", "I will also have X"
    r"i(?:'?ll|\s+will)\s+also\s+(?:have|get|take|need)\s+(?:a(?:n)?\s+)?"
    r"|"
    # "can I also get a X", "could I also have X"
    r"(?:can|could)\s+i\s+also\s+(?:get|have|take)\s+(?:a(?:n)?\s+)?"
    r"|"
    # "let me also get/have X"
    r"let\s+me\s+also\s+(?:get|have|take)\s+(?:a(?:n)?\s+)?"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Configurable Item Pattern (Lazy Built from Database)
# =============================================================================

_CONFIGURABLE_ITEM_PATTERN_CACHE: re.Pattern | None = None


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
