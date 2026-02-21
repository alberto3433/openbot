"""
Quantity Patterns.

Regex patterns for detecting quantity-related intents:
- Make it N (change quantity)
- Reduce to one
- One more / another
- Duplicate all / more of same
- Add more / add N more
"""

import re

from orderbot.tasks.parsers.quantity_utils import QTY_WORDS_RE


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
    r"^(?:and\s+)?(?:(?:also\s+)?add\s+)?(?:one\s+more|another)\s+"
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
