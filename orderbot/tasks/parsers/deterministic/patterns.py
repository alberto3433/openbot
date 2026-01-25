"""
Compiled Regex Patterns for Deterministic Parsing.

This module contains all regex patterns used for deterministic parsing
of user input. Patterns are organized by their purpose.
"""

import re

from orderbot.menu_data_cache import menu_cache


# =============================================================================
# Replace/Cancel Item Patterns
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
    # "no X" but NOT "no more X" (which is cancellation)
    r"no[,]?\s+(?!more\s)(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "i meant X" - requires "i meant"
    r"i\s+meant\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "X instead" - requires "instead" at end
    r"(?:a\s+)?(.+?)\s+instead[\s!.,?]*$"
    r")",
    re.IGNORECASE
)

# Cancel/remove item patterns
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
    r")",
    re.IGNORECASE
)


# =============================================================================
# Filler Word Stripping
# =============================================================================

# Filler words pattern - words that add no meaning and should be stripped before parsing
# e.g., "actually, make it two" -> "make it two"
# Note: "actually" is only stripped when followed by comma (filler), not when followed directly
# by an item name (e.g., "actually coke" means replacement, not filler + new order)
FILLER_WORDS_PATTERN = re.compile(
    r"^(?:"
    r"actually,\s*"  # "actually," with comma is filler
    r"|actually\s+(?=cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off)"  # "actually cancel/remove" etc.
    r"|oh[,\s]+"     # "oh" is always filler
    r"|wait,\s*"     # "wait," with comma is filler
    r"|um+[,\s]+"    # "um" is always filler
    r"|uh+[,\s]+"    # "uh" is always filler
    r"|hmm+[,\s]+"   # "hmm" is always filler
    r"|well[,\s]+"   # "well" is always filler
    r"|so[,\s]+"     # "so" is always filler
    r"|ok(?:ay)?[,\s]+"  # "ok/okay" is always filler
    r"|hey[,\s]+"    # "hey" is always filler
    r"|like[,\s]+"   # "like" is always filler
    r"|sorry[,\s]+"  # "sorry" is filler
    r")",
    re.IGNORECASE
)


def strip_filler_words(text: str) -> str:
    """
    Remove common filler words from the start of user input.

    These words add no semantic meaning and can confuse parsing.
    e.g., "actually, make it two" -> "make it two"
    """
    result = text
    # Keep stripping filler words until none remain at the start
    while True:
        match = FILLER_WORDS_PATTERN.match(result)
        if match:
            result = result[match.end():].strip()
        else:
            break
    return result


# =============================================================================
# Quantity Modification Patterns
# =============================================================================

# "Make it 2" pattern - user wants to change quantity of last item to N
# e.g., "make it 2", "I'll take 2", "actually 2", "give me 2", "let's do 2", "can I get 2?"
MAKE_IT_N_PATTERN = re.compile(
    r"^(?:"
    # "make it 2", "make it two", "make that 2"
    r"make\s+(?:it|that)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "I'll take 2", "I'll have 2", "I'll want 2"
    r"i'?ll\s+(?:take|have|want|get)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "I want 2", "I want two" (without "ll")
    r"i\s+(?:want|need)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "can I get 2?", "can I have 2?", "could I get 2?", "may I have 2?"
    r"(?:can|could|may)\s+i\s+(?:get|have)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "actually 2", "actually let's do 2"
    r"actually\s+(?:let'?s?\s+(?:do|get|have)\s+)?(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "give me 2", "get me 2"
    r"(?:give|get)\s+me\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # "let's do 2", "let's make it 2"
    r"let'?s?\s+(?:do|have|get|make\s+it)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten)"
    r"|"
    # Just a number by itself when we have context (e.g., "2" after adding item) - handled differently
    # "2 of those", "2 of them"
    r"(\d+|two|three|four|five|six|seven|eight|nine|ten)\s+of\s+(?:those|them|that)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "just one" / "only one" pattern - reduces quantity to 1 (removes extras)
# e.g., "actually just one bagel", "only one", "just one", "make it just one"
# The item type word is optional and validated at runtime against menu_cache (data-driven)
REDUCE_TO_ONE_PATTERN = re.compile(
    r"^(?:"
    # "actually just one bagel", "actually only one coffee"
    r"actually\s+(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    # "just one bagel", "only one coffee", "just one", "only one"
    r"(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    # "make it just one", "make it only one"
    r"make\s+(?:it|that)\s+(?:just|only)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    # "i only want one", "i just want one bagel", "i only need one"
    r"i\s+(?:only|just)\s+(?:want|need|wanted)\s+(?:one|1)(?:\s+(\w+))?"
    r"|"
    # "one is enough", "one bagel is enough"
    r"(?:one|1)(?:\s+(\w+))?\s+is\s+(?:enough|fine|good)"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "one more" / "another" pattern - adds 1 more of the last item
ONE_MORE_PATTERN = re.compile(
    r"^(?:"
    r"(?:and\s+)?one\s+more(?:\s+of\s+(?:those|them|that))?"  # "one more", "one more of those"
    r"|"
    r"(?:and\s+)?another(?:\s+one(?:\s+of\s+(?:those|them|that))?)?"  # "another", "another one", "another one of those"
    r"|"
    r"add\s+(?:one\s+more|another)"  # "add one more", "add another"
    r"|"
    r"(?:one|1)\s+more\s+(?:of\s+)?(?:those|them|that)"  # "1 more of those"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# Generic pattern for "another X" / "one more X" - captures any word after the phrase
# The captured word is validated against menu_cache.get_item_type_triggers() at runtime
ANOTHER_ITEM_PATTERN = re.compile(
    r"^(?:and\s+)?(?:one\s+more|another)\s+"
    r"(\w+)"  # Capture any single word (item type keyword)
    r"s?"  # Optional plural 's'
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "all items" / "everything" pattern for duplicating entire cart
DUPLICATE_ALL_PATTERN = re.compile(
    r"^(?:"
    r"all\s+(?:the\s+)?(?:items?|of\s+(?:them|those)|things?)"  # "all the items", "all of them"
    r"|"
    r"everything(?:\s+(?:in\s+(?:the\s+)?(?:cart|order)|again))?"  # "everything", "everything in the cart"
    r"|"
    r"(?:the\s+)?(?:whole|entire)\s+(?:order|cart)"  # "the whole order"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)


# =============================================================================
# "Can You Make It X?" Pattern
# =============================================================================

# Pattern to detect "can you make it X?" style requests during configuration
# Captures the modifier (e.g., "iced", "decaf", "hot")
# Used when user wants to change an aspect of the item being configured
CAN_YOU_MAKE_IT_PATTERN = re.compile(
    r"^(?:"
    # "can you make it iced?", "could you make it decaf?"
    r"(?:can|could)\s+(?:you|i)\s+(?:make|get|have)\s+(?:it|that|this)\s+(.+?)"
    r"|"
    # "is it available iced?", "is that available hot?"
    r"(?:is|are)\s+(?:it|that|this|they)\s+available\s+(.+?)"
    r"|"
    # "does it come in iced?", "does it come iced?"
    r"(?:do|does)\s+(?:it|that|this)\s+come\s+(?:in\s+)?(.+?)"
    r")"
    r"[\s?!.,]*$",
    re.IGNORECASE
)


def parse_can_you_make_it(text: str) -> str | None:
    """
    Parse 'can you make it X?' style requests and extract the modifier.

    Args:
        text: User input to parse

    Returns:
        The extracted modifier (e.g., "iced", "decaf") or None if no match
    """
    match = CAN_YOU_MAKE_IT_PATTERN.match(text.strip())
    if match:
        # Get first non-None group (different branches capture to different groups)
        modifier = next((g for g in match.groups() if g), None)
        if modifier:
            return modifier.strip().rstrip('?.,!')
    return None


# =============================================================================
# Order/Inquiry Detection Patterns
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

# "Add more" patterns - phrases that mean "add 1 more" like "add a third", "add another"
# These ordinals mean "add 1 more to reach that total", NOT "add that quantity"
ADD_MORE_PATTERN = re.compile(
    r"(?:can\s+you\s+|could\s+you\s+|please\s+)?"
    r"(?:add|throw\s+in|get\s+me|give\s+me|i(?:'?d|\s+would)?\s+(?:like|want))"
    r"\s+"
    r"(?:"
    # "a third", "a fourth", "a fifth" etc. - ordinals meaning "one more"
    r"(?:a\s+)?(?:third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    r"|"
    # "another", "one more", "an additional"
    r"(?:another|one\s+more|an?\s+additional)"
    r")"
    r"(?:\s+(?:one|1))?"  # optional "one" after
    r"(?:\s+(.+?))?$",  # optional item description
    re.IGNORECASE
)

# Ordering language pattern - phrases that indicate user wants to order
# This is independent of specific menu items
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
# Unified Configurable Item Pattern (Lazy Built from Database)
# =============================================================================

_CONFIGURABLE_ITEM_PATTERN_CACHE: re.Pattern | None = None


def _get_configurable_item_pattern() -> re.Pattern:
    """Get regex pattern for detecting configurable item orders from database.

    Builds a unified pattern that matches any of:
    - Item type triggers
    - Attribute option words (e.g., "small", "medium", "large", "iced", "hot")

    The pattern doesn't enforce word order - it detects presence of
    item-related keywords to signal a potential new order attempt.

    Returns:
        Compiled regex pattern matching configurable item keywords.
    """
    global _CONFIGURABLE_ITEM_PATTERN_CACHE
    if _CONFIGURABLE_ITEM_PATTERN_CACHE is not None:
        return _CONFIGURABLE_ITEM_PATTERN_CACHE

    # Collect all keywords that indicate a new item order
    keywords: set[str] = set()

    # 1. Item type triggers
    all_triggers = menu_cache.get_item_type_triggers()
    for triggers in all_triggers.values():
        keywords.update(triggers)

    # 2. Attribute option words (small, medium, large, iced, hot, etc.)
    attr_options = menu_cache.get_all_attribute_option_words()
    keywords.update(attr_options.keys())

    # 3. Item names from configurable types (for full menu item names)
    configurable_names = menu_cache.get_configurable_item_names()
    keywords.update(configurable_names)

    # Filter out empty strings and very short words (< 2 chars)
    keywords = {k for k in keywords if k and len(k) >= 2}

    # Sort by length descending to match longer phrases first
    sorted_keywords = sorted(keywords, key=len, reverse=True)

    # Escape for regex and join with alternation
    keywords_pattern = "|".join(re.escape(k) for k in sorted_keywords)

    # Build pattern that matches keyword as word boundary
    _CONFIGURABLE_ITEM_PATTERN_CACHE = re.compile(
        rf"\b({keywords_pattern})\b",
        re.IGNORECASE
    )
    return _CONFIGURABLE_ITEM_PATTERN_CACHE


def warmup_patterns() -> None:
    """
    Pre-compile lazy patterns at startup.

    This eliminates the first-request latency penalty for pattern compilation.
    Call this during application startup after menu_cache is loaded.
    """
    _get_configurable_item_pattern()
