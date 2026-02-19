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

from orderbot.tasks.parsers.parser_utils import _get_menu_cache
from orderbot.tasks.parsers.quantity_utils import QTY_WORDS_RE

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
    # "no, make it X" / "no make it X" - requires "make it" to indicate replacement
    # Plain "no X" is handled by CANCEL_ITEM_PATTERN as removal
    r"no[,]?\s+make\s+(?:it\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
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
    r"skip\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"delete\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"clear\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"empty\s+(?:the\s+)?(?:my\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"take\s+(?:(?:off|out)(?:\s+of)?\s+)?(?:the\s+)?(.+?)(?:\s+off)?[\s!.,]*$"
    r"|"
    r"never\s*mind\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"forget\s+(?:about\s+)?(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"scratch\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"hold\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    r"without\s+(?:the\s+)?(.+?)[\s!.,]*$"
    r"|"
    # Handle "I don't want X", "don't want X", and "no I don't want X" (decline + remove)
    r"(?:no[,]?\s+)?(?:i\s+)?don'?t\s+want\s+(?:the\s+)?(.+?)(?:\s+anymore)?[\s!.,]*$"
    r"|"
    r"no\s+more\s+(?!changes?\b)(.+?)[\s!.,]*$"
    r"|"
    # "no X" / "no X please" - treat as removal (e.g., "no whole milk", "no sugar please")
    # Exclude common false positives: "no thanks", "no that's it", "no I'm good"
    # Also exclude "no make it X" which is a replacement pattern handled by REPLACE_ITEM_PATTERN
    # Also exclude "no I don't want..." which should be handled by the "I don't want X" pattern
    # Use negative lookahead to avoid matching these phrases
    r"no\s+(?!thanks\b|thank\s+you|more\b|but\b|changes?\b|nothing\b|none\b|that'?s?\s+(?:it|all|fine|good|ok|okay)|i'?m\s+(?:good|fine|ok|okay|done|all\s+set)|problem|worries|way|make\s+(?:it\s+)?|i\s+don|(?:can|could|may)\s+i\s+(?:have|get|do))(?:the\s+)?(.+?)(?:\s+please)?[\s!.,]*$"
    r"|"
    # "can you remove X?", "could you remove X?", "would you remove X?"
    r"(?:can|could|would)\s+you\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "can I remove X?", "could we cancel X?"
    r"(?:can|could)\s+(?:i|we)\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r"|"
    # "please remove X", "please cancel X"
    r"please\s+(?:remove|delete|cancel|skip|take\s+(?:off|out))\s+(?:the\s+)?(.+?)[\s!.,?]*$"
    r")",
    re.IGNORECASE
)


# =============================================================================
# Filler Words Pattern
# =============================================================================

# Import consolidated hesitation fillers from constants
from .constants import HESITATION_FILLERS, MID_SENTENCE_HESITATION_FILLERS


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
        r"actually\s+(?=cancel|remove|forget|nevermind|never\s+mind|scratch|take\s+off|no\s)",
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

# Mid-sentence hesitation pattern - pure noise sounds safe to strip from anywhere
_mid_fillers = "|".join(
    re.escape(f) for f in sorted(MID_SENTENCE_HESITATION_FILLERS, key=len, reverse=True)
)
MID_SENTENCE_FILLER_PATTERN = re.compile(rf'\b(?:{_mid_fillers})\b', re.IGNORECASE)


def strip_leading_fillers(text: str) -> str:
    """Remove only leading conversational fillers (greetings, hesitations).

    Unlike strip_conversational_fillers(), this does NOT strip mid-sentence
    words like "also" or "so". Use this when you need to preserve meaningful
    mid-sentence words after removing greetings like "hi there".

    Args:
        text: User input text

    Returns:
        Text with leading conversational fillers removed
    """
    result = text
    while True:
        match = FILLER_WORDS_PATTERN.match(result)
        if match:
            result = result[match.end():].strip()
        else:
            break
    return result


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

    # Strip mid-sentence hesitation sounds (uh, um, er, etc.) from ANYWHERE in text.
    # These are pure noise sounds that never appear in food/menu item names.
    # Word boundaries protect against false matches in longer words (e.g., "butter").
    # e.g., "Can uh you add skim" -> "Can you add skim"
    # e.g., "I want um a bagel" -> "I want a bagel"
    result = MID_SENTENCE_FILLER_PATTERN.sub(' ', result)

    # Strip mid-sentence "so"/"also" - common fillers that never appear
    # in food names as standalone words (word boundary protects "miso", "espresso", etc.)
    # e.g., "no raisin so bagel please" -> "no raisin bagel please"
    # e.g., "also add veggie" -> "add veggie"
    result = re.sub(r'\b(?:so|also)\b', ' ', result, flags=re.IGNORECASE)
    result = re.sub(r'\s+', ' ', result).strip()

    return result


# =============================================================================
# Quantity Change Patterns
# =============================================================================

# "Make it 2" pattern - user wants to change quantity of last item to N
MAKE_IT_N_PATTERN = re.compile(
    r"^(?:"
    rf"actually[,]?\s+make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    # "change it to 3", "change that to three", "switch it to two"
    rf"(?:change|switch)\s+(?:it|that|this)\s+to\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"i'?ll\s+(?:take|have|want|get)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i'?d\s+like\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i\s+would\s+like\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i\s+(?:want|need)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"(?:can|could|may)\s+i\s+(?:get|have)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"actually[,]?\s+(?:let'?s?\s+(?:do|get|have)\s+)?(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"(?:give|get)\s+me\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"let'?s?\s+(?:do|have|get|make\s+it)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"(\d+|{QTY_WORDS_RE})\s+of\s+(?:those|them|that)"
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
    rf"actually[,]?\s+make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    # "change it to 3", "change that to three", "switch it to two"
    rf"(?:change|switch)\s+(?:it|that|this)\s+to\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    # "can you make it two" / "could you make that three"
    rf"(?:can|could|would)\s+you\s+make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"i'?ll\s+(?:take|have|want|get)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i'?d\s+like\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i\s+would\s+like\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"i\s+(?:want|need)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"(?:can|could|may)\s+i\s+(?:get|have)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"actually[,]?\s+(?:let'?s?\s+(?:do|get|have)\s+)?(\d+|{QTY_WORDS_RE})"
    r"|"
    rf"(?:give|get)\s+me\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"let'?s?\s+(?:do|have|get|make\s+it)\s+(\d+|{QTY_WORDS_RE})(?:\s+of\s+(?:those|them|that))?"
    r"|"
    rf"(\d+|{QTY_WORDS_RE})\s+of\s+(?:those|them|that)"
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
    rf"^make\s+(?:it|that)\s+(\d+|{QTY_WORDS_RE})"
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

# Pattern for "give me 2 more <thing>" / "add 3 more <thing>"
# Captures: group(1) = quantity (digit or word), group(2) = item text
ADD_N_MORE_PATTERN = re.compile(
    r"(?:can\s+you\s+|could\s+you\s+|please\s+)?"
    r"(?:add|throw\s+in|get\s+me|give\s+me|i(?:'?d|\s+would)?\s+(?:like|want))"
    r"\s+"
    rf"(\d+|{QTY_WORDS_RE})"
    r"\s+more"
    r"(?:\s+(.+?))?$",
    re.IGNORECASE
)


# =============================================================================
# Ordering Language Pattern
# =============================================================================

ORDERING_LANGUAGE_PATTERN = re.compile(
    r"(?:"
    r"i(?:'?d|\s*would)?\s*(?:also\s+)?(?:like|want|need|take|have|get)"
    r"|(?:can|could|may)\s+i\s+(?:also\s+)?(?:get|have)"
    r"|give\s+me"
    r"|let\s*(?:me|'s)\s*(?:also\s+)?(?:get|have)"
    r")",
    re.IGNORECASE
)


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
