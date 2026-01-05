"""
Deterministic Parsing Functions (no LLM).

This module contains all regex/string-based parsing functions that don't
require LLM calls. These are used for fast, consistent parsing of common
input patterns like greetings, simple bagel orders, coffee orders, etc.
"""

import re
import logging

from sandwich_bot.menu_data_cache import menu_cache

from ..schemas import (
    OpenInputResponse,
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
    CoffeeOrderDetails,
    MenuItemOrderDetails,
    BagelOrderDetails,
    # Helper types for coffee modifiers
    SweetenerItem,
    SyrupItem,
    # ParsedItem types for multi-item handling
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
    ParsedSpeedMenuBagelEntry,
    ParsedSideItemEntry,
    ParsedByPoundEntry,
    # By-the-pound orders
    ByPoundOrderItem,
)
from .constants import (
    WORD_TO_NUM,
    get_speed_menu_bagels,
    # Bagel modifiers (loaded from database via dynamic functions)
    get_proteins,
    get_cheeses,
    get_toppings,
    # Dynamic spread functions (loaded from database)
    get_spreads,
    get_spread_types,
    get_bagel_spreads,
    QUALIFIER_PATTERNS,
    GREETING_PATTERNS,
    GRATITUDE_PATTERNS,
    DONE_PATTERNS,
    HELP_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    get_known_menu_items,
    get_bagel_types,
    get_soda_types,
    get_coffee_types,
    resolve_coffee_alias,
    resolve_soda_alias,
    PRICE_INQUIRY_PATTERNS,
    MENU_CATEGORY_KEYWORDS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    NYC_NEIGHBORHOOD_ZIPS,
    RECOMMENDATION_PATTERNS,
    ITEM_DESCRIPTION_PATTERNS,
    MODIFIER_INQUIRY_PATTERNS,
    MODIFIER_CATEGORY_KEYWORDS,
    MODIFIER_ITEM_KEYWORDS,
    MORE_MENU_ITEMS_PATTERNS,
    get_by_pound_items,
    find_by_pound_item,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions for parsed_items Dual-Write
# =============================================================================

def _build_bagel_parsed_item(
    bagel_type: str | None = None,
    quantity: int = 1,
    toasted: bool | None = None,
    scooped: bool | None = None,
    spread: str | None = None,
    spread_type: str | None = None,
    proteins: list[str] | None = None,
    cheeses: list[str] | None = None,
    toppings: list[str] | None = None,
    needs_cheese_clarification: bool = False,
    modifiers: list[str] | None = None,
) -> ParsedBagelEntry:
    """Build a ParsedBagelEntry from boolean flag data."""
    return ParsedBagelEntry(
        bagel_type=bagel_type,
        quantity=quantity,
        toasted=toasted,
        scooped=scooped,
        spread=spread,
        spread_type=spread_type,
        proteins=proteins or [],
        cheeses=cheeses or [],
        toppings=toppings or [],
        needs_cheese_clarification=needs_cheese_clarification,
        modifiers=modifiers or [],
    )


def _build_coffee_parsed_item(
    drink_type: str,
    size: str | None = None,
    temperature: str | None = None,  # "iced" or "hot"
    quantity: int = 1,
    milk: str | None = None,
    decaf: bool | None = None,
    cream_level: str | None = None,  # dark, light, regular
    special_instructions: str | None = None,
    sweeteners: list | None = None,
    syrups: list | None = None,
    extra_shots: int = 0,
) -> ParsedCoffeeEntry:
    """Build a ParsedCoffeeEntry from boolean flag data."""
    return ParsedCoffeeEntry(
        drink_type=drink_type,
        size=size,
        temperature=temperature,
        quantity=quantity,
        milk=milk,
        decaf=decaf,
        cream_level=cream_level,
        special_instructions=special_instructions,
        sweeteners=sweeteners or [],
        syrups=syrups or [],
        extra_shots=extra_shots,
    )


def _build_speed_menu_parsed_item(
    speed_menu_name: str,
    bagel_type: str | None = None,
    toasted: bool | None = None,
    quantity: int = 1,
    modifiers: list[str] | None = None,
) -> ParsedSpeedMenuBagelEntry:
    """Build a ParsedSpeedMenuBagelEntry from boolean flag data."""
    return ParsedSpeedMenuBagelEntry(
        speed_menu_name=speed_menu_name,
        bagel_type=bagel_type,
        toasted=toasted,
        quantity=quantity,
        modifiers=modifiers or [],
    )


def _build_menu_item_parsed_item(
    menu_item_name: str,
    quantity: int = 1,
    bagel_type: str | None = None,
    toasted: bool | None = None,
    modifiers: list[str] | None = None,
) -> ParsedMenuItemEntry:
    """Build a ParsedMenuItemEntry from boolean flag data."""
    return ParsedMenuItemEntry(
        menu_item_name=menu_item_name,
        quantity=quantity,
        bagel_type=bagel_type,
        toasted=toasted,
        modifiers=modifiers or [],
    )


def _build_side_parsed_item(
    side_name: str,
    quantity: int = 1,
) -> ParsedSideItemEntry:
    """Build a ParsedSideItemEntry from boolean flag data."""
    return ParsedSideItemEntry(
        side_name=side_name,
        quantity=quantity,
    )


# =============================================================================
# Compiled Regex Patterns (internal use)
# =============================================================================

# Replace item patterns: "make it a X instead", "change it to X", "actually X instead", etc.
REPLACE_ITEM_PATTERN = re.compile(
    r"^(?:"
    # "make it X", "make it a X" - requires "make it"
    r"make\s+it\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
    r"|"
    # "can you make it X?", "could you make it X?" - requires "can/could you make it"
    r"(?:can|could)\s+you\s+make\s+it\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,?]*$"
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

# Filler words pattern - words that add no meaning and should be stripped before parsing
# e.g., "actually, make it two" -> "make it two"
# Note: "actually" is only stripped when followed by comma (filler), not when followed directly
# by an item name (e.g., "actually coke" means replacement, not filler + new order)
FILLER_WORDS_PATTERN = re.compile(
    r"^(?:"
    r"actually,\s*"  # "actually," with comma is filler
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
    r"|sorry[,\s]+"  # "sorry" is filler (e.g., "sorry, I meant plain bagel")
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

# "one more" / "another" pattern - adds 1 more of the last item
ONE_MORE_PATTERN = re.compile(
    r"^(?:"
    r"(?:and\s+)?one\s+more"  # "one more", "and one more"
    r"|"
    r"(?:and\s+)?another(?:\s+one)?"  # "another", "another one", "and another"
    r"|"
    r"add\s+(?:one\s+more|another)"  # "add one more", "add another"
    r"|"
    r"(?:one|1)\s+more\s+(?:of\s+)?(?:those|them|that)"  # "one more of those"
    r")"
    r"[\s!.,?]*$",
    re.IGNORECASE
)

# "another bagel" / "one more coffee" pattern - adds a new item of specified type (runs config flow)
# Item type keywords to match after "another" or "one more"
ANOTHER_ITEM_TYPE_KEYWORDS = {
    "bagel": "bagel",
    "bagels": "bagel",
    "coffee": "coffee",
    "coffees": "coffee",
    "latte": "coffee",
    "lattes": "coffee",
    "cappuccino": "coffee",
    "cappuccinos": "coffee",
    "espresso": "coffee",
    "espressos": "coffee",
    "americano": "coffee",
    "americanos": "coffee",
    "macchiato": "coffee",
    "macchiatos": "coffee",
    "mocha": "coffee",
    "mochas": "coffee",
    "tea": "coffee",  # Treat tea like coffee for ordering flow
    "teas": "coffee",
    "drink": "drink",
    "drinks": "drink",
    "sandwich": "sandwich",
    "sandwiches": "sandwich",
}

ANOTHER_ITEM_TYPE_PATTERN = re.compile(
    r"^(?:and\s+)?(?:one\s+more|another)\s+"
    r"(bagels?|coffees?|lattes?|cappuccinos?|espressos?|americanos?|macchiatos?|mochas?|teas?|drinks?|sandwich(?:es)?)"
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

# Egg + cheese sandwich abbreviations (SEC, HEC, etc.)
# These create bagels with protein modifiers, not speed menu items
# Format: (pattern, proteins_list)
EGG_CHEESE_SANDWICH_ABBREVS = {
    # Sausage egg and cheese
    "sec": ["sausage", "egg"],
    "s.e.c.": ["sausage", "egg"],
    "s.e.c": ["sausage", "egg"],
    "sausage egg and cheese": ["sausage", "egg"],
    "sausage egg cheese": ["sausage", "egg"],
    "sausage and egg and cheese": ["sausage", "egg"],
    "sausage eggs and cheese": ["sausage", "egg"],
    # Ham egg and cheese
    "hec": ["ham", "egg"],
    "h.e.c.": ["ham", "egg"],
    "h.e.c": ["ham", "egg"],
    "ham egg and cheese": ["ham", "egg"],
    "ham egg cheese": ["ham", "egg"],
    "ham and egg and cheese": ["ham", "egg"],
    "ham eggs and cheese": ["ham", "egg"],
    # Turkey egg and cheese
    "tec": ["turkey", "egg"],
    "t.e.c.": ["turkey", "egg"],
    "t.e.c": ["turkey", "egg"],
    "turkey egg and cheese": ["turkey", "egg"],
    "turkey egg cheese": ["turkey", "egg"],
}

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

# Bagel quantity pattern - note: compound expressions like "half dozen" must come before single words
BAGEL_QUANTITY_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(\d+|(?:a\s+)?half(?:\s+a)?\s+dozen|a\s+dozen|a\s+couple(?:\s+of)?|couple(?:\s+of)?|a\s+few|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen)\s+"
    r"(?:\w+\s+)*"
    r"bagels?",
    re.IGNORECASE
)

# Simple bagel mention without quantity
SIMPLE_BAGEL_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(?:a\s+)?bagel(?:\s|$|[.,!?])",
    re.IGNORECASE
)

# Coffee order pattern - lazily built to use database-driven coffee types
_COFFEE_ORDER_PATTERN_CACHE: re.Pattern | None = None


def _get_coffee_order_pattern() -> re.Pattern:
    """Get the coffee order regex pattern, building it lazily on first use.

    Uses get_coffee_types() to get coffee/tea types from the database cache,
    falling back to hardcoded defaults if cache isn't loaded.
    """
    global _COFFEE_ORDER_PATTERN_CACHE
    if _COFFEE_ORDER_PATTERN_CACHE is None:
        coffee_types = get_coffee_types()
        # Sort by length (longest first) to match longer names first
        sorted_types = sorted(coffee_types, key=len, reverse=True)
        types_pattern = "|".join(re.escape(t) for t in sorted_types)
        _COFFEE_ORDER_PATTERN_CACHE = re.compile(
            r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
            r"(?:can|could|may)\s+i\s+(?:get|have)|"
            r"give\s+me|"
            r"let\s*(?:me|'s)\s*(?:get|have)|"
            r")?\s*"
            r"(?:an?\s+)?"
            r"(?:(\d+|two|three|four|five)\s+)?"
            r"(?:(small|medium|large)\s+)?"
            r"(?:(iced|hot)\s+)?"
            r"(?:(decaf)\s+)?"
            rf"({types_pattern})"
            r"(?:\s|$|[.,!?])",
            re.IGNORECASE
        )
    return _COFFEE_ORDER_PATTERN_CACHE


# Keep COFFEE_ORDER_PATTERN as a property-like accessor for backwards compatibility
# Code should use _get_coffee_order_pattern() but this allows gradual migration
COFFEE_ORDER_PATTERN = None  # Will be set lazily; use _get_coffee_order_pattern()


# =============================================================================
# Modifier Extraction Functions
# =============================================================================

def extract_modifiers_from_input(user_input: str) -> ExtractedModifiers:
    """
    Extract bagel modifiers from user input using keyword matching.

    This is a deterministic, non-LLM approach that scans the input for
    known modifier keywords and extracts them by category.

    Args:
        user_input: The raw user input string

    Returns:
        ExtractedModifiers with lists of found proteins, cheeses, toppings, spreads
    """
    result = ExtractedModifiers()
    input_lower = user_input.lower()

    # Pre-mark "side of X" patterns to exclude them from modifier extraction
    side_of_spans: list[tuple[int, int]] = []
    side_of_pattern = re.compile(r'\bside\s+of\s+\w+(?:\s+\w+)?', re.IGNORECASE)
    for match in side_of_pattern.finditer(input_lower):
        side_of_spans.append((match.start(), match.end()))
        logger.debug(f"Excluding 'side of' pattern from modifiers: '{match.group()}'")

    # Pre-mark bagel type patterns to exclude them from topping extraction
    bagel_type_spans: list[tuple[int, int]] = []
    for bagel_type in sorted(get_bagel_types(), key=len, reverse=True):
        pattern = re.compile(rf'\b{re.escape(bagel_type)}\s+bagels?\b', re.IGNORECASE)
        for match in pattern.finditer(input_lower):
            type_end = match.start() + len(bagel_type)
            bagel_type_spans.append((match.start(), type_end))
            logger.debug(f"Excluding bagel type from modifiers: '{bagel_type}'")

    def is_word_boundary(text: str, start: int, end: int) -> bool:
        """Check if the match is at word boundaries."""
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end >= len(text) or not text[end].isalnum()
        return before_ok and after_ok

    matched_spans: list[tuple[int, int]] = side_of_spans.copy() + bagel_type_spans.copy()

    def find_and_add(modifier_set: set[str], target_list: list[str], category: str):
        """Find modifiers from a set and add to target list."""
        sorted_modifiers = sorted(modifier_set, key=len, reverse=True)

        for modifier in sorted_modifiers:
            start = 0
            while True:
                pos = input_lower.find(modifier, start)
                if pos == -1:
                    break

                end = pos + len(modifier)

                if is_word_boundary(input_lower, pos, end):
                    overlaps = any(
                        not (end <= s or pos >= e) for s, e in matched_spans
                    )
                    if not overlaps:
                        matched_spans.append((pos, end))
                        normalized = menu_cache.normalize_modifier(modifier)
                        if normalized not in target_list:
                            target_list.append(normalized)
                            logger.debug(f"Extracted {category}: '{modifier}' -> '{normalized}'")

                start = pos + 1

    # Extract in order of specificity
    find_and_add(get_bagel_spreads(), result.spreads, "spread")
    find_and_add(get_proteins(), result.proteins, "protein")
    find_and_add(get_cheeses(), result.cheeses, "cheese")
    find_and_add(get_toppings(), result.toppings, "topping")

    # Special case: if user just says "cheese" without a specific type, mark for clarification
    # Check if only generic "cheese" was extracted (not a specific type like "american")
    if "cheese" in result.cheeses and not any(
        c in result.cheeses for c in [
            "american", "swiss", "cheddar", "muenster", "provolone",
            "gouda", "mozzarella", "pepper jack"
        ]
    ):
        result.needs_cheese_clarification = True
        logger.debug("Generic 'cheese' detected - needs clarification")

    # Extract special instructions (filter to only bagel-related ones)
    instructions_list = extract_special_instructions_from_input(user_input)
    bagel_keywords = {
        'cream cheese', 'butter', 'cream', 'lox', 'spread',
        'bacon', 'ham', 'turkey', 'egg', 'sausage', 'meat',
        'cheese', 'american', 'cheddar', 'swiss', 'muenster',
        'tomato', 'onion', 'lettuce', 'cucumber', 'capers', 'avocado',
    }
    bagel_instructions = [n for n in instructions_list if any(kw in n.lower() for kw in bagel_keywords)]
    result.special_instructions = bagel_instructions

    return result


def extract_coffee_modifiers_from_input(user_input: str) -> ExtractedCoffeeModifiers:
    """
    Extract coffee modifiers from user input using keyword matching.

    Args:
        user_input: The raw user input string

    Returns:
        ExtractedCoffeeModifiers with sweetener, flavor_syrup, and milk if found
    """
    result = ExtractedCoffeeModifiers()
    input_lower = user_input.lower()

    sweeteners = ["splenda", "sugar", "stevia", "equal", "sweet n low", "sweet'n low", "honey"]
    syrups = ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice", "cinnamon", "lavender", "almond"]
    milk_types = [
        "oat", "almond", "coconut", "soy", "whole", "skim", "nonfat",
        "2%", "two percent", "half and half", "half & half", "cream"
    ]

    # Extract milk type
    for milk in milk_types:
        # Match patterns like "oat milk", "with oat", "almond milk"
        # For "almond", skip if it's followed by "syrup" (almond syrup is a flavor, not milk)
        if milk == "almond":
            if re.search(r'\balmond\s+syrup\b', input_lower):
                continue  # Skip, this is almond syrup not almond milk
        if re.search(rf'\b{re.escape(milk)}(?:\s+milk)?\b', input_lower):
            # Normalize milk type
            if milk in ("2%", "two percent"):
                result.milk = "2%"
            elif milk in ("half and half", "half & half"):
                result.milk = "half and half"
            else:
                result.milk = milk
            logger.debug(f"Extracted coffee milk: {result.milk}")
            break

    # Check for "black" (no milk)
    if not result.milk and re.search(r'\bblack\b', input_lower):
        result.milk = "none"
        logger.debug("Extracted coffee milk: none (black)")

    # Check for cream level (dark, light, regular)
    # "dark" = less cream/milk, "light" = more cream/milk
    # Note: "light" for cream level is different from "light roast" - context is cream preference
    if re.search(r'\bdark\b', input_lower):
        result.cream_level = "dark"
        logger.debug("Extracted coffee cream_level: dark")
    elif re.search(r'\blight\b', input_lower):
        # Only match "light" if it's not followed by "roast" (to avoid "light roast" confusion)
        if not re.search(r'\blight\s+roast\b', input_lower):
            result.cream_level = "light"
            logger.debug("Extracted coffee cream_level: light")
    elif re.search(r'\bregular\b', input_lower):
        result.cream_level = "regular"
        logger.debug("Extracted coffee cream_level: regular")

    # Check for just "milk" without a type - default to whole milk
    if not result.milk and re.search(r'\bmilk\b', input_lower):
        result.milk = "whole"
        logger.debug("Extracted coffee milk: whole (default from 'milk')")

    # Extract sweetener with quantity
    for sweetener in sweeteners:
        qty_pattern = re.compile(
            rf'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+{sweetener}s?',
            re.IGNORECASE
        )
        qty_match = qty_pattern.search(input_lower)
        if qty_match:
            qty_str = qty_match.group(1)
            if qty_str.isdigit():
                result.sweetener_quantity = int(qty_str)
            else:
                result.sweetener_quantity = WORD_TO_NUM.get(qty_str.lower(), 1)
            result.sweetener = sweetener
            logger.debug(f"Extracted coffee sweetener: {result.sweetener_quantity} {sweetener}")
            break
        elif re.search(rf'\b{sweetener}s?\b', input_lower):
            result.sweetener = sweetener
            result.sweetener_quantity = 1
            logger.debug(f"Extracted coffee sweetener: {sweetener}")
            break

    # Extract flavor syrup with quantity
    for syrup in syrups:
        # For "almond", require "almond syrup" to avoid matching "almond milk"
        if syrup == "almond":
            # Check for quantity + almond syrup (e.g., "2 almond syrups")
            qty_pattern = re.compile(
                r'(\d+|one|two|three|four|five|six|double|triple)\s+almond\s+syrups?',
                re.IGNORECASE
            )
            qty_match = qty_pattern.search(input_lower)
            if qty_match:
                qty_str = qty_match.group(1).lower()
                if qty_str.isdigit():
                    result.syrup_quantity = int(qty_str)
                elif qty_str == "double":
                    result.syrup_quantity = 2
                elif qty_str == "triple":
                    result.syrup_quantity = 3
                else:
                    result.syrup_quantity = WORD_TO_NUM.get(qty_str, 1)
                result.flavor_syrup = syrup
                logger.debug(f"Extracted coffee flavor syrup: {result.syrup_quantity} {syrup}")
                break
            elif re.search(r'\balmond\s+syrup\b', input_lower):
                result.flavor_syrup = syrup
                result.syrup_quantity = 1
                logger.debug(f"Extracted coffee flavor syrup: {syrup}")
                break
        else:
            # Check for quantity + syrup (e.g., "2 hazelnut syrups", "double vanilla")
            qty_pattern = re.compile(
                rf'(\d+|one|two|three|four|five|six|double|triple)\s+{re.escape(syrup)}(?:\s+syrups?)?',
                re.IGNORECASE
            )
            qty_match = qty_pattern.search(input_lower)
            if qty_match:
                qty_str = qty_match.group(1).lower()
                if qty_str.isdigit():
                    result.syrup_quantity = int(qty_str)
                elif qty_str == "double":
                    result.syrup_quantity = 2
                elif qty_str == "triple":
                    result.syrup_quantity = 3
                else:
                    result.syrup_quantity = WORD_TO_NUM.get(qty_str, 1)
                result.flavor_syrup = syrup
                logger.debug(f"Extracted coffee flavor syrup: {result.syrup_quantity} {syrup}")
                break
            elif re.search(rf'\b{syrup}\b', input_lower):
                result.flavor_syrup = syrup
                result.syrup_quantity = 1
                logger.debug(f"Extracted coffee flavor syrup: {syrup}")
                break

    # Check for generic "syrup" request without a specific flavor
    # e.g., "with syrup", "add syrup", "2 syrups"
    if not result.flavor_syrup and re.search(r'\bsyrups?\b', input_lower):
        result.wants_syrup = True
        # Extract quantity from "2 syrups", "two syrups", "double syrup", etc.
        qty_pattern = re.compile(
            r'(\d+|one|two|three|four|five|six|double|triple)\s+syrups?\b',
            re.IGNORECASE
        )
        qty_match = qty_pattern.search(input_lower)
        if qty_match:
            qty_str = qty_match.group(1).lower()
            if qty_str.isdigit():
                result.syrup_quantity = int(qty_str)
            elif qty_str == "double":
                result.syrup_quantity = 2
            elif qty_str == "triple":
                result.syrup_quantity = 3
            else:
                result.syrup_quantity = WORD_TO_NUM.get(qty_str, 1)
            logger.debug("User requested %d syrups without specifying flavor", result.syrup_quantity)
        else:
            logger.debug("User requested syrup without specifying flavor")

    result.special_instructions = extract_special_instructions_from_input(user_input)

    return result


def extract_special_instructions_from_input(user_input: str) -> list[str]:
    """
    Extract special instructions from user input.

    Args:
        user_input: The raw user input string

    Returns:
        List of instruction strings like ["light cream cheese", "extra bacon"]
    """
    instructions = []
    input_lower = user_input.lower()

    for pattern, qualifier in QUALIFIER_PATTERNS:
        for match in re.finditer(pattern, input_lower, re.IGNORECASE):
            item = match.group(1).strip()
            skip_words = {'the', 'a', 'an', 'and', 'or', 'on', 'with', 'please', 'thanks'}
            if item.lower() in skip_words:
                continue
            if qualifier == 'no':
                instruction = f"no {item}"
            else:
                instruction = f"{qualifier} {item}"
            if instruction not in instructions:
                instructions.append(instruction)
                logger.debug(f"Extracted special instruction: '{instruction}' from input")

    return instructions


# Backwards compatibility alias
extract_notes_from_input = extract_special_instructions_from_input


# =============================================================================
# Helper Extraction Functions
# =============================================================================

def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of', 'a dozen'."""
    text = text.lower().strip()
    text = re.sub(r"\s+of$", "", text)
    # Normalize whitespace for compound expressions like "a  dozen" -> "a dozen"
    text = re.sub(r"\s+", " ", text)

    if text.isdigit():
        return int(text)

    return WORD_TO_NUM.get(text)


def _extract_bagel_type(text: str) -> str | None:
    """Extract bagel type from text."""
    text_lower = text.lower()

    for bagel_type in sorted(get_bagel_types(), key=len, reverse=True):
        if bagel_type in text_lower:
            return bagel_type

    return None


def _extract_toasted(text: str) -> bool | None:
    """Extract toasted preference from text."""
    text_lower = text.lower()

    # Check for "not toasted" first (including typos)
    if re.search(r"\bnot\s+(?:toasted|tosted|tostd)\b", text_lower):
        return False
    # Check for "toasted" and common typos
    if re.search(r"\b(?:toasted|tosted|tostd)\b", text_lower):
        return True

    return None


def _extract_scooped(text: str) -> bool | None:
    """Extract scooped preference from text (bagel with inside bread removed)."""
    text_lower = text.lower()

    # Check for "not scooped" first
    if re.search(r"\bnot\s+scooped\b", text_lower):
        return False
    # Check for "scooped"
    if re.search(r"\bscooped\b", text_lower):
        return True

    return None


def _build_spread_types_from_menu(cheese_types: list[str]) -> set[str]:
    """Build spread type keywords from database cheese_types."""
    spread_types = set()
    for name in cheese_types:
        name_lower = name.lower()
        for suffix in ["cream cheese", "spread"]:
            if suffix in name_lower:
                prefix = name_lower.replace(suffix, "").strip()
                if prefix and prefix not in ("plain", "regular"):
                    spread_types.add(prefix)
                break
    return spread_types


def _extract_spread(text: str, extra_spread_types: set[str] | None = None) -> tuple[str | None, str | None]:
    """Extract spread and spread type from text. Returns (spread, spread_type).

    Note: The returned spread is normalized to its canonical name (e.g., "cc" -> "cream cheese").
    This ensures consistent display and correct pricing lookup.
    """
    text_lower = text.lower()

    spread = None
    spread_type = None

    for s in sorted(get_spreads(), key=len, reverse=True):
        if s in text_lower:
            # Normalize alias to canonical name (e.g., "cc" -> "Cream Cheese")
            normalized = menu_cache.normalize_modifier(s)
            spread = normalized.lower() if normalized != s else s
            break

    all_spread_types = get_spread_types()
    if extra_spread_types:
        all_spread_types = all_spread_types | extra_spread_types

    for st in sorted(all_spread_types, key=len, reverse=True):
        if st in text_lower:
            spread_type = st
            break

    if spread_type and not spread:
        spread = "cream cheese"

    return spread, spread_type


def extract_spread_with_disambiguation(
    text: str,
    extra_spread_types: set[str] | None = None
) -> tuple[str | None, str | None, list[str]]:
    """
    Extract spread and spread type from text with disambiguation support.

    This function extends _extract_spread by using partial matching to find
    potential spread type matches. When the user says something like "walnut
    cream cheese", it will find all spread types containing "walnut" and
    return them for disambiguation if there are multiple matches.

    Args:
        text: User input text
        extra_spread_types: Additional spread types to check (from DB)

    Returns:
        Tuple of (spread, spread_type, disambiguation_options):
        - spread: Base spread type (e.g., "cream cheese", "butter")
        - spread_type: Specific variety (e.g., "scallion", "honey walnut")
        - disambiguation_options: List of matching spread types if ambiguous,
          empty list if exact match or no partial matches found

    Examples:
        >>> extract_spread_with_disambiguation("scallion cream cheese")
        ("cream cheese", "scallion", [])

        >>> extract_spread_with_disambiguation("walnut cream cheese")
        ("cream cheese", None, ["honey walnut", "maple raisin walnut"])

        >>> extract_spread_with_disambiguation("butter")
        ("butter", None, [])
    """
    from .constants import find_spread_matches, get_spread_types, get_spreads

    text_lower = text.lower()
    spread = None
    spread_type = None
    disambiguation_options: list[str] = []

    # First, find the base spread (cream cheese, butter, etc.)
    spreads = get_spreads()
    for s in sorted(spreads, key=len, reverse=True):
        if s in text_lower:
            # Normalize alias to canonical name (e.g., "cc" -> "Cream Cheese")
            normalized = menu_cache.normalize_modifier(s)
            spread = normalized.lower() if normalized != s else s
            break

    # Get all available spread types
    all_spread_types = get_spread_types()
    if extra_spread_types:
        all_spread_types = all_spread_types | extra_spread_types

    # Try exact match first (longest match wins)
    for st in sorted(all_spread_types, key=len, reverse=True):
        if st in text_lower:
            spread_type = st
            break

    # If no exact match, try partial matching for disambiguation
    if not spread_type:
        # Extract potential spread type words from input
        # Remove common words and the base spread
        words_to_check = text_lower
        for remove in ["cream cheese", "butter", "spread", "please", "thanks", "with", "on", "the", "a"]:
            words_to_check = words_to_check.replace(remove, " ")

        # Look for words that could be partial spread types
        words = [w.strip() for w in words_to_check.split() if w.strip() and len(w.strip()) > 2]

        for word in words:
            matches = find_spread_matches(word)
            if matches:
                if len(matches) == 1:
                    # Single match - use it
                    spread_type = matches[0]
                    disambiguation_options = []
                    break
                else:
                    # Multiple matches - need disambiguation
                    disambiguation_options = matches
                    # Don't set spread_type - let caller handle disambiguation
                    break

    # If we found a spread type but no base spread, default to cream cheese
    if spread_type and not spread:
        spread = "cream cheese"

    # If we have disambiguation options but no spread, default to cream cheese
    if disambiguation_options and not spread:
        spread = "cream cheese"

    return spread, spread_type, disambiguation_options


def _extract_side_item(text: str) -> tuple[str | None, int]:
    """Extract side item from text. Returns (side_item_name, quantity).

    Uses database lookup via menu_cache.resolve_side_alias() to map user input
    to canonical menu item names. If no match is found, returns None to allow
    graceful failure handling by the caller.

    Note: This replaces the hardcoded SIDE_ITEM_MAP constant.
    """
    text_lower = text.lower()

    side_match = re.search(r'\bside\s+of\s+(\w+(?:\s+\w+){0,2})', text_lower)
    if not side_match:
        return None, 1

    side_text = side_match.group(1).strip()

    # Try to resolve via database lookup
    canonical = menu_cache.resolve_side_alias(side_text)
    if canonical:
        return canonical, 1

    # Not found in database - return None for graceful failure
    # The caller should handle this case (e.g., show "we don't have that")
    logger.debug("Side item not found in database: %s", side_text)
    return None, 1


def _extract_menu_item_modifications(text: str) -> list[str]:
    """Extract modifications like 'with mayo and mustard' or 'no onions' from text.

    Returns a list of modification strings (e.g., ['mayo', 'mustard'] or ['no onions']).
    """
    modifications = []
    text_lower = text.lower()

    # Known condiments/sauces that can be added
    known_additions = {
        "mayo", "mayonnaise", "mustard", "ketchup", "hot sauce",
        "salt", "pepper", "salt and pepper",
        "lettuce", "tomato", "tomatoes", "onion", "onions", "red onion", "red onions",
        "pickles", "pickle", "capers", "cucumber", "cucumbers",
        "avocado", "bacon", "extra cheese",
    }

    # Coffee-specific modifiers that should NOT be applied to menu items
    coffee_modifiers = {
        "oat milk", "almond milk", "soy milk", "coconut milk", "skim milk", "whole milk",
        "oat", "almond", "soy", "coconut", "skim", "nonfat", "2%",
        "vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice", "cinnamon", "lavender",
        "splenda", "stevia", "equal", "sweet n low", "honey",
        "iced", "hot", "decaf", "black",
        "small", "medium", "large",
    }

    # Pattern for "with X and Y" or "with X, Y, and Z"
    with_pattern = re.search(
        r'\bwith\s+(.+?)(?:\s*(?:please|thanks|toasted|on\s+\w+\s+bagel)|\s*$)',
        text_lower,
        re.IGNORECASE
    )

    if with_pattern:
        with_text = with_pattern.group(1).strip()
        # Remove trailing punctuation
        with_text = re.sub(r'[.!?,]+$', '', with_text).strip()

        # Skip if this is a bagel description like "with everything bagel"
        if re.search(r'\bbagel\b', with_text):
            pass
        # Skip if this is a side description like "with fruit salad"
        elif with_text in ('fruit salad', 'fruit'):
            pass
        else:
            # Split by "and" and commas
            parts = re.split(r'\s*(?:,\s*|\s+and\s+)\s*', with_text)
            for part in parts:
                part = part.strip()
                # Skip coffee-specific modifiers (oat milk, vanilla, etc.)
                if part in coffee_modifiers:
                    continue
                # Check if it's a known addition or starts with "extra"
                if part in known_additions or part.startswith('extra '):
                    modifications.append(part)
                # Also allow any reasonable single/double word modifiers
                elif part and len(part.split()) <= 2 and not re.search(r'\bbagel\b', part):
                    # Exclude common non-modifier words
                    skip_words = {'a', 'an', 'the', 'please', 'thanks', 'it', 'that'}
                    if part not in skip_words and part not in coffee_modifiers:
                        modifications.append(part)

    # Pattern for "no X" modifications
    no_pattern = re.findall(r'\bno\s+(\w+(?:\s+\w+)?)', text_lower)
    for item in no_pattern:
        item = item.strip()
        # Skip common false positives
        skip_items = {'thanks', 'problem', 'worries', 'that', 'more', 'need'}
        if item not in skip_items:
            modifications.append(f"no {item}")

    logger.debug("Extracted modifications from '%s': %s", text[:50], modifications)
    return modifications


def _parse_modify_existing_item(text: str, spread_types: set[str]) -> OpenInputResponse | None:
    """Detect requests to modify an existing cart item with a spread.

    Catches patterns like:
    - "can I have scallion cream cheese on the cinnamon raisin bagel"
    - "put butter on the plain bagel"
    - "add cream cheese to the everything bagel"
    - "make the bagel with scallion cream cheese"
    - "make it with butter"

    This must be called BEFORE menu item matching to prevent "scallion cream cheese"
    from being matched to "Scallion Cream Cheese Sandwich".

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    spread_part = None
    target_bagel = None

    # === Pattern Group 1: SPREAD preposition TARGET bagel ===
    # These patterns have spread BEFORE the target bagel
    # Group 1: spread, Group 2: bagel type
    spread_before_target_patterns = [
        # "can I have X on the Y bagel"
        r"(?:can\s+i\s+(?:have|get)|i(?:'d|\s+would)\s+like)\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*bagel",
        # "put X on the Y bagel"
        r"(?:put|add)\s+(.+?)\s+(?:on|to)\s+(?:the|my)\s+(.+?)\s*bagel",
        # "X on the Y bagel" (simple form)
        r"^(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*bagel$",
        # "i want X on the Y bagel"
        r"i\s+want\s+(.+?)\s+on\s+(?:the|my)\s+(.+?)\s*bagel",
    ]

    for pattern in spread_before_target_patterns:
        match = re.search(pattern, text_lower)
        if match:
            spread_part = match.group(1).strip()
            target_bagel = match.group(2).strip()
            break

    # === Pattern Group 2: TARGET bagel with SPREAD ===
    # These patterns have target BEFORE the spread (reversed order)
    # "make the plain bagel with X" - Group 1: bagel type, Group 2: spread
    if not spread_part:
        match = re.search(
            r"make\s+(?:the|my)\s+(.+?)\s+bagel\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
            text_lower
        )
        if match:
            target_bagel = match.group(1).strip()
            spread_part = match.group(2).strip()

    # === Pattern Group 3: Implicit target (IT or THE BAGEL) ===
    # "make it with X", "make the bagel with X", "put X on it"
    # target_bagel stays None to indicate "find any/last bagel"
    if not spread_part:
        implicit_target_patterns = [
            # "make the bagel with X" - no specific bagel type
            r"make\s+(?:the|my)\s+bagel\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
            # "make it with X"
            r"make\s+it\s+with\s+(.+?)(?:\s+(?:please|thanks))?$",
            # "put X on it"
            r"(?:put|add)\s+(.+?)\s+(?:on|to)\s+it\b",
            # "i want X on it"
            r"i\s+want\s+(.+?)\s+(?:on|to)\s+it\b",
            # "can I have X on it"
            r"(?:can\s+i\s+(?:have|get))\s+(.+?)\s+(?:on|to)\s+it\b",
        ]
        for pattern in implicit_target_patterns:
            match = re.search(pattern, text_lower)
            if match:
                spread_part = match.group(1).strip()
                target_bagel = None  # Implicit - find last/only bagel
                break

    # No pattern matched
    if not spread_part:
        return None

    # === Extract spread and spread_type from spread_part ===
    spread = None
    spread_type = None

    # Extract spread (cream cheese, butter, etc.)
    for s in sorted(get_spreads(), key=len, reverse=True):
        if s in spread_part:
            spread = s
            break

    # Extract spread type (scallion, veggie, etc.)
    all_spread_types = get_spread_types()
    if spread_types:
        all_spread_types = all_spread_types | spread_types

    for st in sorted(all_spread_types, key=len, reverse=True):
        if st in spread_part:
            spread_type = st
            break

    # If we found either a spread or spread_type, this is a modification
    if spread or spread_type:
        # Default spread to cream cheese if only type is mentioned
        if spread_type and not spread:
            spread = "cream cheese"

        logger.info(
            "MODIFY EXISTING ITEM: '%s' -> spread=%s, spread_type=%s, target=%s",
            text[:50], spread, spread_type, target_bagel
        )

        return OpenInputResponse(
            modify_existing_item=True,
            modify_target_description=target_bagel,
            modify_new_spread=spread,
            modify_new_spread_type=spread_type,
        )

    return None


def _extract_menu_item_from_text(text: str) -> tuple[str | None, int]:
    """Try to extract a known menu item from text."""
    text_lower = text.lower().strip()

    text_lower = re.sub(r'^(i\s+want\s+|i\'?d\s+like\s+|can\s+i\s+(get|have)\s+|give\s+me\s+|let\s+me\s+(get|have)\s+)', '', text_lower)
    text_lower = re.sub(r'^(a|an|the)\s+', '', text_lower)

    quantity = 1
    qty_match = re.match(r'^(\d+|one|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        text_lower = text_lower[qty_match.end():]
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    for item in sorted(get_known_menu_items(), key=len, reverse=True):
        # Use word boundary check to prevent partial matches (e.g., "ham" matching "hamburger")
        # The item should appear as complete words in the text
        pattern = rf'\b{re.escape(item)}\b'
        if re.search(pattern, text_lower):
            # Use database lookup to get canonical name
            canonical = menu_cache.resolve_menu_item_alias(item)
            if canonical is None:
                # Item not found in database - skip this match and try next
                continue
            return canonical, quantity

    return None, 0


# =============================================================================
# Bagel with Modifiers Parsing
# =============================================================================

def _parse_bagel_with_modifiers(text: str) -> OpenInputResponse | None:
    """
    Parse bagel orders with modifiers like 'everything bagel with bacon and egg'.

    This handles cases where a bagel type is specified along with protein/topping
    modifiers that should NOT be interpreted as standalone menu items.

    Examples:
        - "everything bagel with bacon and egg"
        - "plain bagel with egg and cheese"
        - "sesame bagel with lox and cream cheese"
    """
    text_lower = text.lower().strip()

    # Must have "bagel" in the text
    if not re.search(r"\bbagels?\b", text_lower):
        return None

    # Must have "with" followed by modifiers - this indicates a customized bagel
    # Pattern: [bagel type] bagel [0-2 optional words like "toasted"] with [modifiers]
    # Allow 0-2 words between "bagel" and "with" for patterns like:
    #   - "plain bagel with egg" (0 words)
    #   - "plain bagel toasted with egg" (1 word)
    #   - "plain bagel not toasted with egg" (2 words)
    with_match = re.search(r"\bbagels?(?:\s+\w+){0,2}\s+with\s+(.+)", text_lower)
    if not with_match:
        return None

    modifier_text = with_match.group(1).strip()

    # Check if the modifiers contain known proteins, cheeses, or toppings
    # If so, this is a bagel with modifiers, not a separate menu item order
    has_protein = any(protein in modifier_text for protein in [
        "bacon", "ham", "turkey", "sausage", "pastrami",
        "egg", "eggs", "egg white", "egg whites",
        "nova", "lox", "salmon",
    ])
    # Check for cheese - but exclude "cream cheese" which is a spread
    modifier_text_no_cream_cheese = modifier_text.replace("cream cheese", "")
    has_cheese = any(cheese in modifier_text_no_cream_cheese for cheese in [
        "cheese", "american", "swiss", "cheddar", "muenster", "provolone",
    ])
    has_topping = any(topping in modifier_text for topping in [
        "tomato", "onion", "lettuce", "capers", "cucumber", "avocado",
    ])
    has_spread = any(spread in modifier_text for spread in [
        "cream cheese", "butter", "hummus",
    ])

    # Only proceed if we found at least one protein, cheese, or topping
    # If ONLY a spread is specified, let it fall through to spread sandwich parsing
    # (e.g., "plain bagel with scallion cream cheese" -> Scallion Cream Cheese Sandwich)
    if not (has_protein or has_cheese or has_topping):
        return None

    logger.info("BAGEL WITH MODIFIERS: detected in '%s'", text[:50])

    # Extract quantity
    quantity = 1
    qty_match = re.match(
        r"^(\d+|one|two|three|four|five|six)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # Extract bagel type
    bagel_type = _extract_bagel_type(text)

    # Extract toasted preference
    toasted = _extract_toasted(text)

    # Extract scooped preference
    scooped = _extract_scooped(text)

    # Extract modifiers using the existing function
    modifiers = extract_modifiers_from_input(text)

    logger.info(
        "BAGEL WITH MODIFIERS PARSED: qty=%d, type=%s, toasted=%s, scooped=%s, proteins=%s, cheeses=%s, toppings=%s, spreads=%s",
        quantity, bagel_type, toasted, scooped,
        modifiers.proteins, modifiers.cheeses, modifiers.toppings, modifiers.spreads
    )

    # Set legacy spread field if a spread was specified
    spread = modifiers.spreads[0] if modifiers.spreads else None

    # Build parsed_items for unified handler (Phase 8 dual-write)
    parsed_items = [
        _build_bagel_parsed_item(
            bagel_type=bagel_type,
            quantity=1,
            toasted=toasted,
            scooped=scooped,
            spread=spread,
            proteins=modifiers.proteins,
            cheeses=modifiers.cheeses,
            toppings=modifiers.toppings,
            needs_cheese_clarification=modifiers.needs_cheese_clarification,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(
        new_bagel=True,
        new_bagel_quantity=quantity,
        new_bagel_type=bagel_type,
        new_bagel_toasted=toasted,
        new_bagel_scooped=scooped,
        new_bagel_spread=spread,  # Legacy field for backward compatibility
        new_bagel_proteins=modifiers.proteins,
        new_bagel_cheeses=modifiers.cheeses,
        new_bagel_toppings=modifiers.toppings,
        new_bagel_spreads=modifiers.spreads,
        new_bagel_special_instructions=modifiers.special_instructions,
        new_bagel_needs_cheese_clarification=modifiers.needs_cheese_clarification,
        parsed_items=parsed_items,  # Dual-write for Phase 8
    )


# =============================================================================
# Split-Quantity Bagel Parsing
# =============================================================================

def _parse_split_quantity_bagels(text: str) -> OpenInputResponse | None:
    """
    Parse orders with multiple bagels that have different configurations.

    Detects patterns like:
        - "two plain bagels one with scallion cream cheese one with lox"
        - "2 bagels, one with lox, one with cream cheese"
        - "three everything bagels one toasted one not toasted one with butter"

    Returns OpenInputResponse with parsed_items populated with ParsedBagelEntry objects.
    """
    text_lower = text.lower().strip()

    # Must have "bagel" in the text
    if not re.search(r"\bbagels?\b", text_lower):
        return None

    # Detect split-quantity patterns: "one with X" or "one X" repeated
    # Pattern: look for "one with", "1 with", "first with", "second with", etc.
    # Also match quantity words followed by bagel types or toasted/not toasted
    bagel_types_pattern = r"(?:plain|everything|sesame|poppy|onion|salt|garlic|pumpernickel|whole\s+wheat|cinnamon\s+raisin|bialy)"
    toasted_pattern = r"(?:not\s+)?toasted"
    split_indicators = [
        r"\bone\s+with\b",
        r"\b1\s+with\b",
        r"\bfirst\s+with\b",
        r"\bsecond\s+with\b",
        r"\bthe\s+other\s+with\b",
        r"\banother\s+with\b",
        rf"\bone\s+(?:{toasted_pattern}|{bagel_types_pattern})\b",
        rf"\btwo\s+(?:{toasted_pattern}|{bagel_types_pattern})\b",
        rf"\bthree\s+(?:{toasted_pattern}|{bagel_types_pattern})\b",
        rf"\b[123]\s+(?:{toasted_pattern}|{bagel_types_pattern})\b",
        r"\bfirst\s+one\b",
        r"\bsecond\s+one\b",
    ]

    # Count how many split indicators we find
    split_count = 0
    for pattern in split_indicators:
        matches = re.findall(pattern, text_lower)
        split_count += len(matches)

    # Need at least 2 split indicators to be a split-quantity order
    if split_count < 2:
        return None

    logger.info("SPLIT-QUANTITY BAGELS: detected %d split indicators in '%s'", split_count, text[:60])

    # Extract the total quantity
    total_quantity = 2  # Default
    qty_match = re.match(
        r"^(\d+|two|three|four|five|six)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            total_quantity = int(qty_str)
        else:
            total_quantity = WORD_TO_NUM.get(qty_str, 2)

    # Extract the base bagel type from the INITIAL part of the text only
    # (before the first "one with" or split indicator)
    # This prevents "one plain" from being used as the base bagel type
    first_split = re.split(r"\b(?:one|1|first)\s+(?:with\s+)?", text_lower, maxsplit=1)[0]
    base_bagel_type = _extract_bagel_type(first_split)

    # Extract base toasted preference from initial part only
    base_toasted = _extract_toasted(first_split)

    # Split the text into parts for each bagel
    # Look for patterns like "one with X", "two Y", "the other with Z"
    # Captures: (quantity_word, specification)
    split_pattern = re.compile(
        r"(?:,?\s*(?:and\s+)?)"  # Optional comma/and separator
        r"(one|two|three|1|2|3|first|second|third|the\s+other|another)\s+"  # Quantity/ordinal (group 1)
        r"(with\s+.+?|(?:not\s+)?toasted(?:\s+with\s+.+?)?|plain(?:\s+with\s+.+?)?|"  # Specification (group 2)
        r"(?:plain|everything|sesame|poppy|onion|salt|garlic|pumpernickel|whole\s+wheat|cinnamon\s+raisin|bialy)(?:\s+with\s+.+?)?)"  # Or bagel type
        r"(?=(?:,?\s*(?:and\s+)?(?:one|two|three|1|2|3|first|second|third|the\s+other|another)\s+)|$)",
        re.IGNORECASE
    )

    # Find all split parts with quantities
    raw_parts = split_pattern.findall(text_lower)
    logger.info("SPLIT-QUANTITY: found %d raw parts: %s", len(raw_parts), raw_parts)

    # Convert to (quantity, specification) tuples
    parts_with_qty: list[tuple[int, str]] = []
    for qty_word, spec in raw_parts:
        qty_word_lower = qty_word.lower().strip()
        # Map quantity words to numbers
        if qty_word_lower in ("one", "1", "first", "the other", "another"):
            qty = 1
        elif qty_word_lower in ("two", "2", "second"):
            qty = 2 if qty_word_lower in ("two", "2") else 1
        elif qty_word_lower in ("three", "3", "third"):
            qty = 3 if qty_word_lower in ("three", "3") else 1
        else:
            qty = 1
        parts_with_qty.append((qty, spec.strip()))

    # If we didn't find enough parts with the regex, try a simpler split
    if len(parts_with_qty) < 2:
        # Try splitting on "one with" or "one " (legacy fallback, assumes qty=1 each)
        simple_split = re.split(r",?\s*(?:and\s+)?(?:one|1)\s+(?:with\s+)?", text_lower)
        # Filter out empty parts and the initial bagel description
        parts_with_qty = [(1, p.strip()) for p in simple_split[1:] if p.strip()]
        logger.info("SPLIT-QUANTITY: simple split found %d parts: %s", len(parts_with_qty), parts_with_qty)

    if len(parts_with_qty) < 2:
        return None

    # Create ParsedBagelEntry for each part (new unified system)
    parsed_items: list[ParsedBagelEntry] = []
    item_count = 0

    for part_qty, part in parts_with_qty:
        # Stop if we've reached the total quantity
        if item_count >= total_quantity:
            break

        part_lower = part.lower().strip()

        # Normalize common spread aliases BEFORE processing
        # This allows "cc" to match "cream cheese" logic below
        spread_aliases = {
            r"\bcc\b": "cream cheese",
            r"\bpb\b": "peanut butter",
            r"\bsc\b": "scallion cream cheese",
            r"\bvcc\b": "vegetable cream cheese",
        }
        for alias_pattern, canonical in spread_aliases.items():
            part_lower = re.sub(alias_pattern, canonical, part_lower)

        # Check if this part specifies a different bagel type (e.g., "one plain, one everything")
        part_bagel_type = _extract_bagel_type(part_lower)
        if part_bagel_type:
            bagel_type = part_bagel_type
        else:
            bagel_type = base_bagel_type

        # Extract toasted for this specific bagel
        toasted = None
        if "not toasted" in part_lower or "untoasted" in part_lower:
            toasted = False
        elif "toasted" in part_lower:
            toasted = True
        elif base_toasted is not None:
            toasted = base_toasted

        # Extract spread/modifier for this bagel
        spread = None
        spread_type = None

        # Check for butter first (before cream cheese logic)
        # Use word boundary to avoid matching "peanut butter"
        if re.search(r"(?<!\w)butter(?!\s+cream cheese)\b", part_lower):
            if "peanut" not in part_lower:
                spread = "butter"

        # Check for proteins as the main item (lox, nova, etc.)
        if not spread:
            for protein in ["nova scotia salmon", "nova", "lox", "salmon", "whitefish", "tuna"]:
                if protein in part_lower:
                    # This is actually a spread/fish order
                    normalized = menu_cache.normalize_modifier(protein)
                    spread = normalized
                    break

        # Check for cream cheese with type (e.g., "scallion cream cheese")
        if not spread and "cream cheese" in part_lower:
            spread = "cream cheese"
            # Look for spread type before "cream cheese"
            for st in sorted(get_spread_types(), key=len, reverse=True):
                if st in part_lower:
                    spread_type = st
                    break

        # Check for peanut butter, nutella, hummus, etc.
        if not spread:
            for spread_name in ["peanut butter", "nutella", "hummus", "avocado", "jelly", "jam"]:
                if spread_name in part_lower:
                    spread = spread_name
                    break

        # "plain" in split context means no spread - just a plain bagel
        # Don't set spread for "plain"

        # Create entries for this part (may be >1 for uneven splits like "two not toasted")
        items_to_create = min(part_qty, total_quantity - item_count)
        for _ in range(items_to_create):
            parsed_items.append(ParsedBagelEntry(
                bagel_type=bagel_type,  # Use per-item bagel type (may differ from base)
                quantity=1,
                toasted=toasted,
                spread=spread,
                spread_type=spread_type,
            ))
            item_count += 1
            logger.info(
                "SPLIT-QUANTITY: bagel %d: type=%s, toasted=%s, spread=%s, spread_type=%s",
                item_count, bagel_type, toasted, spread, spread_type
            )

    # If we have fewer entries than total_quantity, fill with base bagels
    while len(parsed_items) < total_quantity:
        parsed_items.append(ParsedBagelEntry(
            bagel_type=base_bagel_type,
            quantity=1,
            toasted=base_toasted,
        ))

    return OpenInputResponse(
        new_bagel=True,
        new_bagel_quantity=total_quantity,
        new_bagel_type=base_bagel_type,
        new_bagel_toasted=base_toasted,
        parsed_items=parsed_items,  # Use new unified system
    )


def _parse_split_quantity_drinks(text: str) -> OpenInputResponse | None:
    """
    Parse orders with multiple drinks that have different configurations.

    Detects patterns like:
        - "two coffees one with milk one black"
        - "2 lattes, one iced, one hot"
        - "three teas one with sugar one with honey one plain"

    Returns OpenInputResponse with parsed_items populated with ParsedCoffeeEntry objects.
    """
    text_lower = text.lower().strip()

    # Build pattern for drink types (coffee, tea, latte, etc.)
    # get_coffee_types() includes both item names and aliases from database
    all_drink_types = list(get_coffee_types())
    drink_pattern = "|".join(re.escape(d) for d in sorted(all_drink_types, key=len, reverse=True))

    # Must have a drink type in the text (plural or singular)
    drink_match = re.search(rf'\b({drink_pattern})s?\b', text_lower)
    if not drink_match:
        return None

    base_drink_type = drink_match.group(1)
    # Resolve alias to canonical menu item name
    base_drink_type = resolve_coffee_alias(base_drink_type)

    # Detect split-quantity patterns: "one with X" or "one X" repeated
    # Split indicators for drinks - expanded to support uneven splits like "two hot"
    drink_spec_pattern = r"(?:with|iced|hot|black|decaf|plain)"
    split_indicators = [
        rf"\bone\s+{drink_spec_pattern}\b",
        rf"\b1\s+{drink_spec_pattern}\b",
        rf"\bfirst\s+{drink_spec_pattern}\b",
        rf"\bsecond\s+{drink_spec_pattern}\b",
        rf"\bthe\s+other\s+{drink_spec_pattern}\b",
        rf"\banother\s+{drink_spec_pattern}\b",
        rf"\btwo\s+{drink_spec_pattern}\b",
        rf"\bthree\s+{drink_spec_pattern}\b",
        rf"\b[123]\s+{drink_spec_pattern}\b",
        r"\bfirst\s+one\b",
        r"\bsecond\s+one\b",
    ]

    # Count how many split indicators we find
    split_count = 0
    for pattern in split_indicators:
        matches = re.findall(pattern, text_lower)
        split_count += len(matches)

    # Need at least 2 split indicators to be a split-quantity order
    if split_count < 2:
        return None

    logger.info("SPLIT-QUANTITY DRINKS: detected %d split indicators in '%s'", split_count, text[:60])

    # Extract the total quantity
    total_quantity = 2  # Default
    qty_match = re.match(
        r"^(\d+|two|three|four|five|six)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            total_quantity = int(qty_str)
        else:
            total_quantity = WORD_TO_NUM.get(qty_str, 2)

    # Extract base drink properties from the INITIAL part of the text
    # (before the first "one with" or split indicator)
    first_split = re.split(r"\b(?:one|1|first)\s+(?:with\s+|iced|hot|black|decaf)?", text_lower, maxsplit=1)[0]

    # Extract base size from initial part
    base_size = None
    size_match = re.search(r'\b(small|medium|large)\b', first_split)
    if size_match:
        base_size = size_match.group(1)

    # Extract base iced/hot from initial part (only if explicitly stated)
    base_iced = None
    if re.search(r'\biced\b', first_split):
        base_iced = True
    elif re.search(r'\bhot\b', first_split):
        base_iced = False

    # Extract base decaf from initial part
    base_decaf = None
    if re.search(r'\bdecaf\b', first_split):
        base_decaf = True

    # Split the text into parts for each drink
    # Captures: (quantity_word, specification)
    split_pattern = re.compile(
        r"(?:,?\s*(?:and\s+)?)"  # Optional comma/and separator
        r"(one|two|three|1|2|3|first|second|third|the\s+other|another)\s+"  # Quantity/ordinal (group 1)
        r"(with\s+.+?|iced(?:\s+with\s+.+?)?|hot(?:\s+with\s+.+?)?|black|decaf(?:\s+with\s+.+?)?|plain)"  # Specification (group 2)
        r"(?=(?:,?\s*(?:and\s+)?(?:one|two|three|1|2|3|first|second|third|the\s+other|another)\s+)|$)",
        re.IGNORECASE
    )

    # Find all split parts with quantities
    raw_parts = split_pattern.findall(text_lower)
    logger.info("SPLIT-QUANTITY DRINKS: found %d raw parts: %s", len(raw_parts), raw_parts)

    # Convert to (quantity, specification) tuples
    parts_with_qty: list[tuple[int, str]] = []
    for qty_word, spec in raw_parts:
        qty_word_lower = qty_word.lower().strip()
        # Map quantity words to numbers
        if qty_word_lower in ("one", "1", "first", "the other", "another"):
            qty = 1
        elif qty_word_lower in ("two", "2", "second"):
            qty = 2 if qty_word_lower in ("two", "2") else 1
        elif qty_word_lower in ("three", "3", "third"):
            qty = 3 if qty_word_lower in ("three", "3") else 1
        else:
            qty = 1
        parts_with_qty.append((qty, spec.strip()))

    # If we didn't find enough parts with the regex, try a simpler split
    if len(parts_with_qty) < 2:
        # Try splitting on "one with" or "one " (legacy fallback, assumes qty=1 each)
        simple_split = re.split(r",?\s*(?:and\s+)?(?:one|1)\s+(?:with\s+)?", text_lower)
        # Filter out empty parts and the initial drink description
        parts_with_qty = [(1, p.strip()) for p in simple_split[1:] if p.strip()]
        logger.info("SPLIT-QUANTITY DRINKS: simple split found %d parts: %s", len(parts_with_qty), parts_with_qty)

    if len(parts_with_qty) < 2:
        return None

    # Create ParsedCoffeeEntry for each part (new unified system)
    parsed_items: list[ParsedCoffeeEntry] = []
    item_count = 0

    for part_qty, part in parts_with_qty:
        # Stop if we've reached the total quantity
        if item_count >= total_quantity:
            break

        part_lower = part.lower().strip()

        # Extract iced/hot for this specific drink
        iced = None
        temperature = None
        if "iced" in part_lower:
            iced = True
            temperature = "iced"
        elif "hot" in part_lower:
            iced = False
            temperature = "hot"
        elif base_iced is not None:
            iced = base_iced
            temperature = "iced" if base_iced else "hot"

        # Extract decaf for this specific drink
        decaf = None
        if "decaf" in part_lower:
            decaf = True
        elif base_decaf is not None:
            decaf = base_decaf

        # Extract milk preference for this drink
        milk = None
        if "black" in part_lower or "plain" in part_lower:
            milk = "none"
        else:
            # Check for milk types
            milk_match = re.search(r'\b(oat|almond|soy|skim|whole|coconut)\s*milk\b', part_lower)
            if milk_match:
                milk = milk_match.group(1)
            elif re.search(r'\bwith\s+milk\b', part_lower):
                milk = "whole"

        # Create entries for this part (may be >1 for uneven splits like "two hot")
        items_to_create = min(part_qty, total_quantity - item_count)
        for _ in range(items_to_create):
            parsed_items.append(ParsedCoffeeEntry(
                drink_type=base_drink_type,
                size=base_size,
                temperature=temperature,
                quantity=1,
                milk=milk,
                decaf=decaf,
            ))
            item_count += 1
            logger.info(
                "SPLIT-QUANTITY DRINKS: drink %d: type=%s, size=%s, iced=%s, decaf=%s, milk=%s",
                item_count, base_drink_type, base_size, iced, decaf, milk
            )

    # If we have fewer entries than total_quantity, fill with base drinks
    while len(parsed_items) < total_quantity:
        parsed_items.append(ParsedCoffeeEntry(
            drink_type=base_drink_type,
            size=base_size,
            temperature="iced" if base_iced else ("hot" if base_iced is False else None),
            quantity=1,
            decaf=base_decaf,
        ))

    # Get first coffee for the primary new_coffee fields
    first_coffee = parsed_items[0] if parsed_items else None

    return OpenInputResponse(
        new_coffee=True,
        new_coffee_type=base_drink_type,
        new_coffee_quantity=total_quantity,
        new_coffee_size=base_size,
        new_coffee_iced=first_coffee.temperature == "iced" if first_coffee and first_coffee.temperature else base_iced,
        new_coffee_decaf=first_coffee.decaf if first_coffee else base_decaf,
        new_coffee_milk=first_coffee.milk if first_coffee else None,
        parsed_items=parsed_items,  # Use new unified system
    )


# =============================================================================
# Speed Menu Bagel Parsing
# =============================================================================

def _parse_egg_cheese_sandwich_abbrev(text: str) -> OpenInputResponse | None:
    """
    Parse egg+cheese sandwich abbreviations like SEC, HEC.

    These create bagel orders with protein modifiers and cheese clarification needed.
    Bagel type and toasted status are left as None so the system will ask.
    """
    text_lower = text.lower()

    # Check for matches (longest first to handle "sausage egg and cheese" before "sec")
    matched_abbrev = None
    matched_proteins = None

    for abbrev in sorted(EGG_CHEESE_SANDWICH_ABBREVS.keys(), key=len, reverse=True):
        if abbrev in text_lower:
            matched_abbrev = abbrev
            matched_proteins = EGG_CHEESE_SANDWICH_ABBREVS[abbrev]
            break

    if not matched_abbrev:
        return None

    logger.info("EGG CHEESE ABBREV: found '%s' -> proteins=%s in text '%s'",
                matched_abbrev, matched_proteins, text[:50])

    # Extract quantity
    quantity = 1
    qty_pattern = re.compile(
        r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+" + re.escape(matched_abbrev),
        re.IGNORECASE
    )
    qty_match = qty_pattern.search(text_lower)
    if qty_match:
        qty_str = qty_match.group(1).lower()
        if qty_str.isdigit():
            quantity = int(qty_str)
        elif qty_str in ("a", "an"):
            quantity = 1
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # Check for bagel type if specified (e.g., "SEC on an everything bagel")
    bagel_type = None
    bagel_pattern = re.compile(
        r"\b(?:on|with)\s+(?:(?:a|an)\s+)?(\w+(?:\s+\w+)?)\s+bagels?",
        re.IGNORECASE
    )
    bagel_match = bagel_pattern.search(text)
    if bagel_match:
        potential_type = bagel_match.group(1).lower().strip()
        if potential_type in get_bagel_types():
            bagel_type = potential_type

    # Check for toasted if specified
    toasted = _extract_toasted(text)
    scooped = _extract_scooped(text)

    # Build parsed_items for unified handler (Phase 8 dual-write)
    parsed_items = [
        _build_bagel_parsed_item(
            bagel_type=bagel_type,
            quantity=1,
            toasted=toasted,
            scooped=scooped,
            proteins=matched_proteins,
            needs_cheese_clarification=True,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(
        new_bagel=True,
        new_bagel_quantity=quantity,
        new_bagel_type=bagel_type,  # None = will ask
        new_bagel_toasted=toasted,  # None = will ask
        new_bagel_scooped=scooped,
        new_bagel_proteins=matched_proteins,
        new_bagel_needs_cheese_clarification=True,  # Always ask for cheese type
        parsed_items=parsed_items,  # Dual-write for Phase 8
    )


def _parse_speed_menu_bagel_deterministic(text: str) -> OpenInputResponse | None:
    """Parse speed menu bagel orders like 'The Classic BEC on a wheat bagel'."""
    text_lower = text.lower()

    # Get speed menu bagels mapping from database
    speed_menu_bagels = get_speed_menu_bagels()

    matched_item = None
    matched_key = None

    for key in sorted(speed_menu_bagels.keys(), key=len, reverse=True):
        if key in text_lower:
            matched_item = speed_menu_bagels[key]
            matched_key = key
            break

    if not matched_item:
        return None

    # If user says "omelette" but matched item isn't an omelette, skip this match
    # Let the menu item parser handle omelettes properly (e.g., "truffled egg omelette")
    if re.search(r'\bomelet(?:te)?s?\b', text_lower) and 'omelette' not in matched_item.lower():
        logger.info("SPEED MENU SKIP: text contains 'omelette' but matched '%s' is not an omelette", matched_item)
        return None

    logger.info("SPEED MENU MATCH: found '%s' -> %s in text '%s'", matched_key, matched_item, text[:50])

    # Extract quantity
    quantity = 1
    qty_pattern = re.compile(
        r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+" + re.escape(matched_key),
        re.IGNORECASE
    )
    qty_match = qty_pattern.search(text_lower)
    if qty_match:
        qty_str = qty_match.group(1).lower()
        if qty_str.isdigit():
            quantity = int(qty_str)
        elif qty_str in ("a", "an"):
            quantity = 1
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    toasted = _extract_toasted(text)

    # Extract bagel choice
    # IMPORTANT: Use word boundary \b before "on/with" to prevent matching "bacon" as "bac-ON"
    bagel_choice = None
    bagel_choice_pattern = re.compile(
        r"\b(?:on|with)\s+(?:(?:a|an)\s+)?(\w+(?:\s+\w+)?)\s+bagels?",
        re.IGNORECASE
    )
    bagel_match = bagel_choice_pattern.search(text)
    if bagel_match:
        potential_type = bagel_match.group(1).lower().strip()
        if potential_type in get_bagel_types():
            bagel_choice = potential_type
        else:
            for bagel_type in get_bagel_types():
                if potential_type == bagel_type or bagel_type.startswith(potential_type):
                    bagel_choice = bagel_type
                    break

    if not bagel_choice:
        for bagel_type in sorted(get_bagel_types(), key=len, reverse=True):
            pattern = re.compile(
                r"\b(?:on|with)\s+(?:(?:a|an)\s+)?" + re.escape(bagel_type) + r"(?:\s|$|[,.])",
                re.IGNORECASE
            )
            if pattern.search(text_lower):
                bagel_choice = bagel_type
                break

    # Extract modifications (e.g., "with mayo and mustard", "no onions")
    modifications = _extract_menu_item_modifications(text)

    logger.info(
        "SPEED MENU PARSED: item=%s, qty=%d, toasted=%s, bagel_choice=%s, mods=%s",
        matched_item, quantity, toasted, bagel_choice, modifications
    )

    # Check if there's also a coffee/drink mentioned in the input
    # Look for patterns like "and a coffee", "with a latte", "and large iced coffee"
    coffee_type = None
    coffee_size = None
    coffee_iced = None
    coffee_decaf = None
    coffee_milk = None

    # Check for coffee after "and" or "with" - this indicates a second item
    # "with" is included because beverages can't be modifiers for food items
    # e.g., "classic BEC with coffee" = BEC + coffee (separate items)
    and_coffee_match = re.search(
        r'\b(?:and|with)\s+(?:a\s+)?(?:(small|medium|large)\s+)?(?:(hot|iced)\s+)?(?:(decaf)\s+)?'
        r'(coffee|latte|cappuccino|espresso|americano|macchiato|mocha|tea|chai)',
        text_lower
    )
    if and_coffee_match:
        coffee_size = and_coffee_match.group(1)
        if and_coffee_match.group(2) == 'iced':
            coffee_iced = True
        elif and_coffee_match.group(2) == 'hot':
            coffee_iced = False
        if and_coffee_match.group(3) == 'decaf':
            coffee_decaf = True
        coffee_type = and_coffee_match.group(4)

        # Also check for milk
        milk_match = re.search(r'with\s+(oat|almond|soy|skim|whole|coconut)\s*milk', text_lower)
        if milk_match:
            coffee_milk = milk_match.group(1)

        logger.info(
            "SPEED MENU + COFFEE: also found coffee - type=%s, size=%s, iced=%s, decaf=%s",
            coffee_type, coffee_size, coffee_iced, coffee_decaf
        )

        # Remove coffee-related items from modifications since coffee is a separate item
        beverage_words = {
            'coffee', 'latte', 'cappuccino', 'espresso', 'americano',
            'macchiato', 'mocha', 'tea', 'chai',
        }
        modifications = [
            mod for mod in modifications
            if mod.lower() not in beverage_words
        ]

    # Build parsed_items for unified handler (Phase 8 dual-write)
    parsed_items = [
        _build_speed_menu_parsed_item(
            speed_menu_name=matched_item,
            bagel_type=bagel_choice,
            toasted=toasted,
            quantity=1,
            modifiers=modifications,
        )
        for _ in range(quantity)
    ]

    # Add coffee to parsed_items if found
    if coffee_type:
        parsed_items.append(_build_coffee_parsed_item(
            drink_type=coffee_type,
            size=coffee_size,
            temperature="iced" if coffee_iced else ("hot" if coffee_iced is False else None),
            quantity=1,
            milk=coffee_milk,
            decaf=coffee_decaf,
        ))

    response = OpenInputResponse(
        new_speed_menu_bagel=True,
        new_speed_menu_bagel_name=matched_item,
        new_speed_menu_bagel_quantity=quantity,
        new_speed_menu_bagel_toasted=toasted,
        new_speed_menu_bagel_bagel_choice=bagel_choice,
        new_speed_menu_bagel_modifications=modifications,
        parsed_items=parsed_items,  # Dual-write for Phase 8
    )

    # Add coffee to the response if found
    if coffee_type:
        response.new_coffee = True
        response.new_coffee_type = coffee_type
        response.new_coffee_size = coffee_size
        response.new_coffee_iced = coffee_iced
        response.new_coffee_decaf = coffee_decaf
        response.new_coffee_milk = coffee_milk

    return response


# =============================================================================
# Coffee/Soda Parsing
# =============================================================================

def _parse_coffee_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse coffee/beverage orders deterministically."""
    text_lower = text.lower()

    # Exclude "coffee cake" - it's a pastry, not a coffee order
    # This must be checked early before we match "coffee" as a beverage
    if re.search(r'\bcoffee\s+cake\b', text_lower):
        return None

    coffee_type = None

    # Check for beverage keywords from database (sorted by length for specificity)
    # This matches compound names like "chai tea" before simpler ones like "tea"
    for bev in sorted(get_coffee_types(), key=len, reverse=True):
        if re.search(rf'\b{re.escape(bev)}s?\b', text_lower):
            coffee_type = bev
            break

    if not coffee_type:
        return None

    # Resolve alias to canonical menu item name (e.g., "matcha" -> "Seasonal Latte Matcha")
    canonical_coffee_type = resolve_coffee_alias(coffee_type)
    logger.debug("Deterministic parse: detected coffee type '%s' -> canonical '%s'", coffee_type, canonical_coffee_type)
    coffee_type = canonical_coffee_type

    # Extract quantity - allow optional size/temperature words between qty and coffee type
    # e.g., "three medium coffees", "2 large iced lattes", "dozen hot coffees"
    quantity = 1
    # Compound expressions first, then single words
    qty_words = r'\d+|(?:a\s+)?couple(?:\s+of)?|(?:a\s+)?half(?:\s+a)?\s+dozen|a\s+dozen|a\s+few|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen'
    size_words = r'(?:(?:small|medium|large|iced|hot)\s+)*'

    # Build pattern that matches beverage types from database
    all_drink_types = list(get_coffee_types())
    # Escape special regex chars and sort by length (longest first)
    drink_pattern = "|".join(re.escape(d) for d in sorted(all_drink_types, key=len, reverse=True))

    qty_match = re.search(rf'({qty_words})\s+{size_words}(?:{drink_pattern})s?\b', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # Extract size
    size = None
    size_match = re.search(r'\b(small|medium|large)\b', text_lower)
    if size_match:
        size = size_match.group(1)

    # Extract iced/hot
    iced = None
    if re.search(r'\biced\b', text_lower):
        iced = True
    elif re.search(r'\bhot\b', text_lower):
        iced = False

    # Extract decaf
    decaf = None
    if re.search(r'\bdecaf\b', text_lower):
        decaf = True

    # Extract extra shots for espresso drinks (double = 1 extra, triple = 2 extra)
    extra_shots = 0
    if re.search(r'\btriple\s+(?:shot\s+)?espresso\b', text_lower):
        extra_shots = 2
    elif re.search(r'\bdouble\s+(?:shot\s+)?espresso\b', text_lower):
        extra_shots = 1

    # Extract milk preference
    milk = None
    milk_patterns = [
        (r'\bwith\s+(oat|almond|soy|skim|whole|coconut)\s*milk\b', 1),
        (r'\b(oat|almond|soy|skim|whole|coconut)\s*milk\b', 1),
        (r'\bblack\b', 'none'),
        (r'\bwith\s+milk\b', 'whole'),
        (r'\bwith\s+(?:a\s+)?(?:splash|little|bit)\s+(?:of\s+)?milk\b', 'whole'),
        (r'\bmilk\b(?!\s*(?:oat|almond|soy|skim|whole|coconut|chocolate))', 'whole'),
    ]
    for pattern, group in milk_patterns:
        milk_match = re.search(pattern, text_lower)
        if milk_match:
            milk = milk_match.group(group) if isinstance(group, int) else group
            break

    coffee_mods = extract_coffee_modifiers_from_input(text)

    instructions_list = extract_special_instructions_from_input(text)
    coffee_keywords = {'milk', 'cream', 'ice', 'hot', 'shot', 'espresso', 'foam', 'whip', 'sugar', 'syrup'}
    coffee_instructions = [n for n in instructions_list if any(kw in n.lower() for kw in coffee_keywords)]
    special_instructions = ", ".join(coffee_instructions) if coffee_instructions else None

    logger.debug(
        "Deterministic parse: coffee order - type=%s, qty=%d, size=%s, iced=%s, decaf=%s, milk=%s, sweetener=%s(%d), syrup=%s(%d), extra_shots=%d, special_instructions=%s",
        coffee_type, quantity, size, iced, decaf, milk,
        coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup, coffee_mods.syrup_quantity, extra_shots, special_instructions
    )

    # Build parsed_items for unified handler (Phase 8 dual-write)
    # Build sweeteners list from coffee_mods
    sweeteners = []
    if coffee_mods.sweetener:
        sweeteners.append(SweetenerItem(type=coffee_mods.sweetener, quantity=coffee_mods.sweetener_quantity))
    # Build syrups list from coffee_mods
    syrups = []
    if coffee_mods.flavor_syrup:
        syrups.append(SyrupItem(type=coffee_mods.flavor_syrup, quantity=coffee_mods.syrup_quantity))

    parsed_items = [
        _build_coffee_parsed_item(
            drink_type=coffee_type,
            size=size,
            temperature="iced" if iced else ("hot" if iced is False else None),
            quantity=1,
            milk=milk,
            decaf=decaf,
            cream_level=coffee_mods.cream_level,
            special_instructions=special_instructions,
            sweeteners=sweeteners,
            syrups=syrups,
            extra_shots=extra_shots,
        )
        for _ in range(quantity)
    ]

    response = OpenInputResponse(
        new_coffee=True,
        new_coffee_type=coffee_type,
        new_coffee_quantity=quantity,
        new_coffee_size=size,
        new_coffee_iced=iced,
        new_coffee_decaf=decaf,
        new_coffee_milk=milk,
        new_coffee_cream_level=coffee_mods.cream_level,
        new_coffee_sweetener=coffee_mods.sweetener,
        new_coffee_sweetener_quantity=coffee_mods.sweetener_quantity,
        new_coffee_flavor_syrup=coffee_mods.flavor_syrup,
        new_coffee_syrup_quantity=coffee_mods.syrup_quantity,
        new_coffee_special_instructions=special_instructions,
        parsed_items=parsed_items,  # Dual-write for Phase 8
    )

    # Check if there's also a speed menu bagel mentioned in the input
    # Look for patterns like "and a bec", "and a classic", "and the leo"
    speed_menu_bagels = get_speed_menu_bagels()
    for key in sorted(speed_menu_bagels.keys(), key=len, reverse=True):
        # Check for speed menu item after "and"
        and_pattern = rf'\band\s+(?:a\s+|an\s+|the\s+)?{re.escape(key)}\b'
        if re.search(and_pattern, text_lower):
            matched_item = speed_menu_bagels[key]
            logger.info(
                "COFFEE + SPEED MENU: also found speed menu item '%s' -> %s",
                key, matched_item
            )
            response.new_speed_menu_bagel = True
            response.new_speed_menu_bagel_name = matched_item
            response.new_speed_menu_bagel_quantity = 1
            speed_menu_toasted = None
            speed_menu_bagel_choice = None
            # Extract toasted/bagel choice from the remainder after "and"
            and_match = re.search(rf'\band\s+(.+)$', text_lower)
            if and_match:
                remainder = and_match.group(1)
                speed_menu_toasted = _extract_toasted(remainder)
                response.new_speed_menu_bagel_toasted = speed_menu_toasted
                # Check for bagel choice (use \b word boundary to prevent "bacon" matching "bac-ON")
                for bagel_type in sorted(get_bagel_types(), key=len, reverse=True):
                    bagel_pattern = rf'\b(?:on|with)\s+(?:a\s+|an\s+)?{re.escape(bagel_type)}'
                    if re.search(bagel_pattern, remainder):
                        speed_menu_bagel_choice = bagel_type
                        response.new_speed_menu_bagel_bagel_choice = speed_menu_bagel_choice
                        break
            # Add speed menu bagel to parsed_items
            response.parsed_items.append(_build_speed_menu_parsed_item(
                speed_menu_name=matched_item,
                bagel_type=speed_menu_bagel_choice,
                toasted=speed_menu_toasted,
                quantity=1,
            ))
            break

    return response


def _parse_soda_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse soda/bottled drink orders deterministically.

    Routes bottled beverages through new_menu_item for disambiguation,
    not new_coffee (which is reserved for sized beverages like coffee/tea).

    Uses database-loaded soda types (via get_soda_types()) which includes
    both item names and their aliases.
    """
    text_lower = text.lower()
    soda_types = get_soda_types()

    drink_type = None
    for soda in sorted(soda_types, key=len, reverse=True):
        if re.search(rf'\b{re.escape(soda)}\b', text_lower):
            drink_type = soda
            break

    if not drink_type:
        generic_soda_terms = {"soda", "pop", "soft drink", "fountain drink"}
        for term in generic_soda_terms:
            if re.search(rf'\b{re.escape(term)}\b', text_lower):
                logger.info("Deterministic parse: detected generic soda term '%s', needs clarification", term)
                return OpenInputResponse(needs_soda_clarification=True)

    if not drink_type:
        return None

    # Resolve alias to canonical menu item name from database (e.g., "coke" -> "Coca-Cola")
    # If not found, keep original name (will fail gracefully if item doesn't exist in menu)
    canonical_name = resolve_soda_alias(drink_type)
    logger.debug("Deterministic parse: detected soda type '%s' -> canonical '%s'", drink_type, canonical_name)

    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    logger.debug("Deterministic parse: soda order - type=%s, qty=%d", canonical_name, quantity)

    # Build parsed_items for unified handler (Phase 8 dual-write)
    parsed_items = [
        _build_menu_item_parsed_item(
            menu_item_name=canonical_name,
            quantity=1,
        )
        for _ in range(quantity)
    ]

    # Route through new_menu_item for disambiguation instead of new_coffee
    # This allows bottled drinks (juice, soda) to go through the same
    # disambiguation flow as other menu items
    return OpenInputResponse(
        new_menu_item=canonical_name,
        new_menu_item_quantity=quantity,
        parsed_items=parsed_items,  # Dual-write for Phase 8
    )


# =============================================================================
# By-the-Pound Order Parsing
# =============================================================================

# Pattern to match by-weight orders like "half a pound of whitefish salad"
# Captures: quantity phrase + item name
BY_POUND_PATTERN = re.compile(
    r"""
    (?:i(?:'ll|\ will)?\ (?:have|take|get)|give\ me|can\ i\ (?:have|get)|i(?:'d|\ would)?\ like|i\ need)?
    \s*
    (?:
        ((?:a\s+)?half\s+(?:a\s+)?(?:pound|lb))    # a half pound / half a pound / half pound / half lb
        |(\d+(?:\s*/\s*\d+)?)\s*(?:pound|lb)s?     # 1/4 pound, 2 pounds, 1 lb
        |(a\s+(?:pound|lb))                        # a pound / a lb
        |((?:a\s+)?quarter\s+(?:pound|lb))         # a quarter pound / quarter pound / quarter lb
    )
    \s+(?:of\s+)?
    (.+?)                                          # item name
    (?:\s+please)?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE
)


def _find_by_pound_item_category(item_name: str) -> tuple[str, str] | None:
    """
    Find the category for a by-pound item.

    Uses the menu cache to look up items by name or alias. The cache handles
    exact matches, partial matches, and aliases (e.g., "lox" -> "Nova Scotia Salmon").

    Args:
        item_name: The item name to look up (e.g., "whitefish salad", "muenster", "lox")

    Returns:
        Tuple of (canonical_name, category) or None if not found.
    """
    return find_by_pound_item(item_name)


def _parse_by_pound_order(text: str) -> OpenInputResponse | None:
    """
    Parse by-the-pound orders like "half a pound of whitefish salad".

    This MUST be called BEFORE menu item parsing to prevent items like
    "whitefish salad" from being matched to "Whitefish Salad Sandwich".

    Returns:
        OpenInputResponse with by_pound_items if matched, None otherwise.
    """
    text_lower = text.lower().strip()

    match = BY_POUND_PATTERN.match(text_lower)
    if not match:
        return None

    # Extract quantity
    half_lb = match.group(1)
    numeric_lb = match.group(2)
    a_lb = match.group(3)
    quarter_lb = match.group(4)
    item_name = match.group(5).strip()

    if half_lb:
        quantity = "half lb"
    elif numeric_lb:
        # Handle fractions like "1/4"
        if "/" in numeric_lb:
            num, denom = numeric_lb.replace(" ", "").split("/")
            fraction = float(num) / float(denom)
            if fraction == 0.25:
                quantity = "quarter lb"
            elif fraction == 0.5:
                quantity = "half lb"
            else:
                quantity = f"{numeric_lb} lb"
        else:
            num = int(numeric_lb)
            quantity = f"{num} lb" if num == 1 else f"{num} lbs"
    elif a_lb:
        quantity = "1 lb"
    elif quarter_lb:
        quantity = "quarter lb"
    else:
        quantity = "1 lb"

    # Look up the item in database via find_by_pound_item
    result = _find_by_pound_item_category(item_name)
    if not result:
        logger.debug("By-pound pattern matched but item not found: '%s'", item_name)
        return None

    canonical_name, category = result
    logger.info("BY-POUND ORDER: '%s' -> %s %s (category=%s)", text[:50], quantity, canonical_name, category)

    return OpenInputResponse(
        by_pound_items=[
            ByPoundOrderItem(
                item_name=canonical_name,
                quantity=quantity,
                category=category,
            )
        ]
    )


# =============================================================================
# Inquiry Parsing (Price, Recommendations, Store Info, Item Description)
# =============================================================================

def _parse_price_inquiry_deterministic(text: str) -> OpenInputResponse | None:
    """Parse price inquiry questions."""
    text_lower = text.lower().strip()

    for pattern in PRICE_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = match.group(1).strip()
            item_text = re.sub(r'[.!?,]+$', '', item_text).strip()

            logger.debug("Price inquiry detected: item_text='%s'", item_text)

            if item_text in MENU_CATEGORY_KEYWORDS:
                menu_type = MENU_CATEGORY_KEYWORDS[item_text]
                logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    asks_about_price=True,
                    menu_query=True,
                    menu_query_type=menu_type,
                )

            your_match = re.match(r"your\s+(.+)", item_text)
            if your_match:
                item_after_your = your_match.group(1).strip()
                if item_after_your in MENU_CATEGORY_KEYWORDS:
                    menu_type = MENU_CATEGORY_KEYWORDS[item_after_your]
                    logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", text[:50], menu_type)
                    return OpenInputResponse(
                        asks_about_price=True,
                        menu_query=True,
                        menu_query_type=menu_type,
                    )

            logger.info("PRICE INQUIRY (specific): '%s' -> price_query_item=%s", text[:50], item_text)
            return OpenInputResponse(
                asks_about_price=True,
                price_query_item=item_text,
            )

    return None


def _parse_menu_query_deterministic(text: str) -> OpenInputResponse | None:
    """Parse 'what X do you have?' type menu queries."""
    text_lower = text.lower().strip()

    # Generic terms that should trigger a GENERAL menu listing (all categories)
    # These are not specific category queries - they're asking about the whole menu
    general_menu_terms = {
        "food", "foods", "stuff", "things", "items", "menu items",
        "menu", "options", "choices", "eats", "grub",
    }

    # Patterns for GENERAL menu inquiries (should list all categories)
    general_menu_patterns = [
        # "what's on your/the menu?" / "whats on your menu?" / "what is on your/the menu?"
        re.compile(r"what(?:'?s|\s+is)\s+on\s+(?:your|the)\s+menu", re.IGNORECASE),
        # "what do you have?" / "what do you have on the menu?"
        re.compile(r"what\s+do\s+you\s+have(?:\s+on\s+(?:the|your)\s+menu)?(?:\?|$)", re.IGNORECASE),
        # "what do you serve?" / "what do you sell?"
        re.compile(r"what\s+do\s+you\s+(?:serve|sell|offer|make)", re.IGNORECASE),
        # "what can I order?" / "what can I get?"
        re.compile(r"what\s+can\s+i\s+(?:order|get|have)", re.IGNORECASE),
        # "show me the menu" / "let me see the menu"
        re.compile(r"(?:show|let\s+me\s+see|can\s+i\s+see)\s+(?:me\s+)?(?:the|your)\s+menu", re.IGNORECASE),
        # "menu please" / "the menu"
        re.compile(r"^(?:the\s+)?menu(?:\s+please)?(?:\?|!|\.)?$", re.IGNORECASE),
    ]

    # Check for general menu inquiry patterns first
    for pattern in general_menu_patterns:
        if pattern.search(text_lower):
            logger.info("GENERAL MENU QUERY: '%s'", text[:50])
            return OpenInputResponse(
                menu_query=True,
                menu_query_type=None,  # None means list all categories
            )

    # Patterns for menu category queries
    # "what desserts do you have?", "what sweets do you have?", "what pastries do you have?"
    # "what kind of muffins do you have?"
    menu_query_patterns = [
        # "what kind of X do you have" - capture X
        re.compile(r"what\s+(?:kind|type|types|kinds)\s+of\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        # "what X do you have" - capture X
        re.compile(r"what\s+(.+?)\s+do\s+you\s+have", re.IGNORECASE),
        re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|have\s+you)\s+got", re.IGNORECASE),
        re.compile(r"what\s+(?:are\s+)?(?:your|the)\s+(.+?)(?:\s+options)?(?:\?|$)", re.IGNORECASE),
        re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    ]

    for pattern in menu_query_patterns:
        match = pattern.search(text_lower)
        if match:
            category_text = match.group(1).strip()
            # Remove trailing punctuation
            category_text = re.sub(r'[.!?,]+$', '', category_text).strip()

            # Check if it's a generic term that should trigger general menu listing
            if category_text in general_menu_terms:
                logger.info("GENERAL MENU QUERY (generic term '%s'): '%s'", category_text, text[:50])
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=None,  # None means list all categories
                )

            # Check if it maps to a known category
            if category_text in MENU_CATEGORY_KEYWORDS:
                menu_type = MENU_CATEGORY_KEYWORDS[category_text]
                logger.info("MENU QUERY: '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    menu_query=True,
                    menu_query_type=menu_type,
                )

    return None


def _parse_recommendation_inquiry(text: str) -> OpenInputResponse | None:
    """Parse recommendation questions."""
    text_lower = text.lower().strip()

    for pattern, category in RECOMMENDATION_PATTERNS:
        if pattern.search(text_lower):
            logger.info("RECOMMENDATION INQUIRY: '%s' (category: %s)", text[:50], category)
            return OpenInputResponse(
                asks_recommendation=True,
                recommendation_category=category,
            )

    return None


def _parse_store_info_inquiry(text: str) -> OpenInputResponse | None:
    """Parse store info inquiries."""
    text_lower = text.lower().strip()

    for pattern in STORE_HOURS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (hours): '%s'", text[:50])
            return OpenInputResponse(asks_store_hours=True)

    for pattern in STORE_LOCATION_PATTERNS:
        if pattern.search(text_lower):
            logger.info("STORE INFO INQUIRY (location): '%s'", text[:50])
            return OpenInputResponse(asks_store_location=True)

    for pattern in DELIVERY_ZONE_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            location_query = match.group(1).strip()
            location_query = re.sub(r'[.!?,]+$', '', location_query).strip()
            logger.info("STORE INFO INQUIRY (delivery zone): '%s' -> '%s'", text[:50], location_query)
            return OpenInputResponse(
                asks_delivery_zone=True,
                delivery_zone_query=location_query,
            )

    return None


def _parse_item_description_inquiry(text: str) -> OpenInputResponse | None:
    """Parse item description questions."""
    text_lower = text.lower().strip()

    if any(word in text_lower for word in ["my cart", "my order", "the cart", "the order"]):
        return None

    for pattern in ITEM_DESCRIPTION_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_name = match.group(1).strip()
            item_name = re.sub(r'[.!?,]+$', '', item_name).strip()
            item_name = re.sub(r'\s+sandwich$', '', item_name).strip()
            if item_name:
                logger.info("ITEM DESCRIPTION INQUIRY: '%s' -> item='%s'", text[:50], item_name)
                return OpenInputResponse(
                    asks_item_description=True,
                    item_description_query=item_name,
                )

    return None


def _parse_modifier_inquiry(text: str) -> OpenInputResponse | None:
    """Parse modifier/add-on inquiry questions."""
    text_lower = text.lower().strip()

    for pattern, item_group, category_group in MODIFIER_INQUIRY_PATTERNS:
        match = pattern.search(text_lower)
        if match:
            item_text = None
            category_text = None

            # Extract item from match if present
            if item_group > 0:
                try:
                    item_text = match.group(item_group).strip()
                    item_text = re.sub(r'[.!?,]+$', '', item_text).strip()
                except (IndexError, AttributeError):
                    pass

            # Extract category from match if present
            if category_group > 0:
                try:
                    category_text = match.group(category_group).strip()
                    category_text = re.sub(r'[.!?,]+$', '', category_text).strip()
                except (IndexError, AttributeError):
                    pass

            # Normalize item type
            item_type = None
            if item_text:
                item_type = MODIFIER_ITEM_KEYWORDS.get(item_text.lower())
                # If item_text doesn't match known items, it might be a category
                if not item_type and item_text.lower() in MODIFIER_CATEGORY_KEYWORDS:
                    category_text = item_text
                    item_text = None

            # Normalize category
            category = None
            if category_text:
                category = MODIFIER_CATEGORY_KEYWORDS.get(category_text.lower())

            # Only return if we have a valid item or category
            if item_type or category:
                logger.info(
                    "MODIFIER INQUIRY: '%s' -> item=%s, category=%s",
                    text[:50], item_type, category
                )
                return OpenInputResponse(
                    asks_modifier_options=True,
                    modifier_query_item=item_type,
                    modifier_query_category=category,
                )

    return None


def _parse_more_menu_items(text: str) -> OpenInputResponse | None:
    """Parse 'show more' menu requests like 'what other drinks do you have?'"""
    text_lower = text.lower().strip()

    for pattern in MORE_MENU_ITEMS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("MORE MENU ITEMS: '%s'", text[:50])
            return OpenInputResponse(wants_more_menu_items=True)

    return None


# =============================================================================
# "Add More" Parsing (add a third, add another, etc.)
# =============================================================================

def _parse_add_more_request(text: str) -> OpenInputResponse | None:
    """
    Parse "add more" requests like "add a third orange juice", "add another coffee".

    These phrases mean "add 1 more" - ordinals like "third" mean "one more to make 3 total",
    NOT "add 3 items".

    Returns OpenInputResponse with quantity=1 for the item, or None if no match.
    """
    match = ADD_MORE_PATTERN.match(text.strip())
    if not match:
        return None

    item_text = match.group(1)
    if item_text:
        item_text = item_text.strip()
        # Clean up trailing punctuation
        item_text = re.sub(r'[.!?,]+$', '', item_text).strip()

    logger.info("ADD MORE REQUEST: detected in '%s', item_text='%s'", text[:50], item_text)

    # If no item specified, we can't parse deterministically - need context
    # The state machine will need to infer from the last item type
    if not item_text:
        # Return a special marker that indicates "add 1 more of whatever was last ordered"
        # For now, return None and let it fall through to LLM or state machine handling
        logger.debug("ADD MORE: no item specified, needs context")
        return None

    # Try to parse the item text as a specific item type
    # Soda/bottled drinks first (more specific names like "Snapple Iced Tea")
    # then coffee/sized beverages (more generic names like "iced tea")
    soda_result = _parse_soda_deterministic(item_text)
    if soda_result and soda_result.new_coffee:
        soda_result.new_coffee_quantity = 1  # Always 1 for "add another"
        logger.info("ADD MORE: parsed as soda '%s' (qty=1)", soda_result.new_coffee_type)
        return soda_result

    coffee_result = _parse_coffee_deterministic(item_text)
    if coffee_result and coffee_result.new_coffee:
        coffee_result.new_coffee_quantity = 1  # Always 1 for "add another"
        logger.info("ADD MORE: parsed as coffee '%s' (qty=1)", coffee_result.new_coffee_type)
        return coffee_result

    # Try speed menu bagel
    speed_result = _parse_speed_menu_bagel_deterministic(item_text)
    if speed_result and speed_result.new_speed_menu_bagel:
        speed_result.new_speed_menu_bagel_quantity = 1
        logger.info("ADD MORE: parsed as speed menu '%s' (qty=1)", speed_result.new_speed_menu_bagel_name)
        return speed_result

    # Try menu item
    menu_item, _ = _extract_menu_item_from_text(item_text)
    if menu_item:
        logger.info("ADD MORE: parsed as menu item '%s' (qty=1)", menu_item)
        return OpenInputResponse(
            new_menu_item=menu_item,
            new_menu_item_quantity=1,
            parsed_items=[_build_menu_item_parsed_item(menu_item_name=menu_item, quantity=1)],  # Dual-write for Phase 8
        )

    # Try bagel
    if re.search(r'\bbagels?\b', item_text, re.IGNORECASE):
        bagel_type = _extract_bagel_type(item_text)
        toasted = _extract_toasted(item_text)
        scooped = _extract_scooped(item_text)
        spread, spread_type = _extract_spread(item_text)
        logger.info("ADD MORE: parsed as bagel type='%s' (qty=1)", bagel_type)
        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=1,
            new_bagel_type=bagel_type,
            new_bagel_toasted=toasted,
            new_bagel_scooped=scooped,
            new_bagel_spread=spread,
            new_bagel_spread_type=spread_type,
            parsed_items=[_build_bagel_parsed_item(bagel_type=bagel_type, toasted=toasted, scooped=scooped, spread=spread, spread_type=spread_type)],  # Dual-write for Phase 8
        )

    # Check for common drink shorthand like "orange juice", "OJ", etc.
    # that might not match the full soda pattern
    drink_shorthands = {
        "orange juice": "Tropicana Orange Juice",
        "oj": "Tropicana Orange Juice",
        "apple juice": "Apple Juice",
        "cranberry juice": "Cranberry Juice",
        "lemonade": "Lemonade",
        "water": "Water",
        "bottled water": "Bottled Water",
    }
    item_lower = item_text.lower()
    for shorthand, canonical in drink_shorthands.items():
        if shorthand in item_lower:
            logger.info("ADD MORE: parsed shorthand '%s' as '%s' (qty=1)", shorthand, canonical)
            return OpenInputResponse(
                new_coffee=True,
                new_coffee_type=canonical,
                new_coffee_quantity=1,
                parsed_items=[_build_coffee_parsed_item(drink_type=canonical, quantity=1)],  # Dual-write for Phase 8
            )

    # Couldn't parse the item - fall back to LLM
    logger.debug("ADD MORE: couldn't parse item '%s', falling back", item_text)
    return None


# =============================================================================
# Multi-Item Order Parsing
# =============================================================================

def _parse_multi_item_order(user_input: str) -> OpenInputResponse | None:
    """Parse multi-item orders like 'The Lexington and an orange juice'."""
    text = user_input.strip()
    text_lower = text.lower()

    compound_phrases = [
        # Egg sandwich phrases (longer phrases first to match properly)
        ("bacon egg and cheese", "BACON_EGG_CHEESE_PLACEHOLDER"),
        ("ham egg and cheese", "HAM_EGG_CHEESE_PLACEHOLDER"),
        ("sausage egg and cheese", "SAUSAGE_EGG_CHEESE_PLACEHOLDER"),
        ("egg and cheese", "EGG_CHEESE_PLACEHOLDER"),
        ("bacon and egg and cheese", "BACON_AND_EGG_CHEESE_PLACEHOLDER"),
        ("ham and egg and cheese", "HAM_AND_EGG_CHEESE_PLACEHOLDER"),
        ("bacon eggs and cheese", "BACON_EGGS_CHEESE_PLACEHOLDER"),
        ("ham eggs and cheese", "HAM_EGGS_CHEESE_PLACEHOLDER"),
        # Other compound phrases
        ("ham and cheese", "HAM_CHEESE_PLACEHOLDER"),
        ("ham and egg", "HAM_EGG_PLACEHOLDER"),
        ("bacon and egg", "BACON_EGG_PLACEHOLDER"),
        ("lox and cream cheese", "LOX_CC_PLACEHOLDER"),
        ("cream cheese and lox", "CC_LOX_PLACEHOLDER"),
        ("salt and pepper", "SALT_PEPPER_PLACEHOLDER"),
        ("eggs and bacon", "EGGS_BACON_PLACEHOLDER"),
        ("black and white", "BLACK_WHITE_PLACEHOLDER"),
        ("spinach and feta", "SPINACH_FETA_PLACEHOLDER"),
        # Condiment pairs (prevent splitting "with mayo and mustard")
        ("mayo and mustard", "MAYO_MUSTARD_PLACEHOLDER"),
        ("mustard and mayo", "MUSTARD_MAYO_PLACEHOLDER"),
        ("ketchup and mustard", "KETCHUP_MUSTARD_PLACEHOLDER"),
        ("lettuce and tomato", "LETTUCE_TOMATO_PLACEHOLDER"),
        ("tomato and lettuce", "TOMATO_LETTUCE_PLACEHOLDER"),
        ("onions and peppers", "ONIONS_PEPPERS_PLACEHOLDER"),
        ("pickles and onions", "PICKLES_ONIONS_PLACEHOLDER"),
    ]

    preserved_text = text_lower
    for phrase, placeholder in compound_phrases:
        preserved_text = preserved_text.replace(phrase, placeholder)

    if " and " not in preserved_text and ", " not in preserved_text:
        return None

    preserved_text = preserved_text.replace(", and ", ", ")
    preserved_text = preserved_text.replace(" and ", ", ")

    parts = [p.strip() for p in preserved_text.split(",") if p.strip()]
    if len(parts) < 2:
        return None

    restored_parts = []
    for part in parts:
        restored = part.strip()
        for phrase, placeholder in compound_phrases:
            restored = restored.replace(placeholder, phrase)
        if restored:
            restored_parts.append(restored)

    logger.info("Multi-item order split into %d parts: %s", len(restored_parts), restored_parts)

    # Use a list to collect ALL menu items instead of overwriting
    menu_item_list: list[MenuItemOrderDetails] = []
    coffee_list: list[CoffeeOrderDetails] = []
    bagel = False
    bagel_qty = 1
    bagel_type = None
    bagel_toasted = None
    bagel_spread = None
    bagel_spread_type = None
    side_item = None
    side_item_qty = 1
    # Speed menu bagel tracking
    speed_menu_bagel = False
    speed_menu_bagel_name = None
    speed_menu_bagel_qty = 1
    speed_menu_bagel_toasted = None
    speed_menu_bagel_bagel_choice = None
    speed_menu_bagel_modifications = None
    # NEW: parsed_items list for generic multi-item handling
    parsed_items: list = []
    # By-the-pound items collection
    by_pound_items: list[ByPoundOrderItem] = []

    # First pass: count how many parts have menu items
    # If only ONE part has a menu item, we should extract modifications from the ORIGINAL text
    # (to handle cases like "the Lexington with mayo, mustard and ketchup" which gets split incorrectly)
    parts_with_menu_items = 0
    for part in restored_parts:
        item_name, _ = _extract_menu_item_from_text(part.strip())
        if item_name:
            parts_with_menu_items += 1

    # Extract modifications from original text if only one menu item detected
    # This captures "with mayo, mustard and ketchup" that gets split into separate parts
    use_original_text_for_mods = parts_with_menu_items == 1
    original_modifications = _extract_menu_item_modifications(text) if use_original_text_for_mods else []

    for part in restored_parts:
        part = part.strip()
        if not part:
            continue

        # Try speed menu bagel FIRST - important because "bacon egg and cheese"
        # would otherwise be matched as a menu item "Bacon"
        speed_result = _parse_speed_menu_bagel_deterministic(part)
        if speed_result and speed_result.new_speed_menu_bagel:
            speed_menu_bagel = True
            speed_menu_bagel_name = speed_result.new_speed_menu_bagel_name
            speed_menu_bagel_qty = speed_result.new_speed_menu_bagel_quantity or 1
            speed_menu_bagel_toasted = speed_result.new_speed_menu_bagel_toasted
            speed_menu_bagel_bagel_choice = speed_result.new_speed_menu_bagel_bagel_choice
            speed_menu_bagel_modifications = speed_result.new_speed_menu_bagel_modifications
            # Add to parsed_items for generic handling
            parsed_items.append(ParsedSpeedMenuBagelEntry(
                speed_menu_name=speed_result.new_speed_menu_bagel_name,
                bagel_type=speed_result.new_speed_menu_bagel_bagel_choice,
                toasted=speed_result.new_speed_menu_bagel_toasted,
                quantity=speed_result.new_speed_menu_bagel_quantity or 1,
                modifiers=speed_result.new_speed_menu_bagel_modifications or [],
            ))
            logger.info("Multi-item: detected speed menu bagel '%s' (qty=%d) via direct parse",
                        speed_menu_bagel_name, speed_menu_bagel_qty)
            continue

        # Try by-pound order BEFORE menu item extraction
        # This prevents "quarter pound of plain cream cheese" from matching "Plain Cream Cheese Sandwich"
        by_pound_result = _parse_by_pound_order(part)
        if by_pound_result and by_pound_result.by_pound_items:
            for bp_item in by_pound_result.by_pound_items:
                by_pound_items.append(bp_item)
                parsed_items.append(ParsedByPoundEntry(
                    item_name=bp_item.item_name,
                    quantity=bp_item.quantity,
                    category=bp_item.category,
                ))
            logger.info("Multi-item: detected by-pound items: %s", by_pound_result.by_pound_items)
            continue

        item_name, item_qty = _extract_menu_item_from_text(part)
        if item_name:
            bagel_choice = _extract_bagel_type(part)
            toasted = _extract_toasted(part)
            # Use original text mods if single menu item, otherwise extract from part
            modifications = original_modifications if use_original_text_for_mods else _extract_menu_item_modifications(part)
            menu_item_list.append(MenuItemOrderDetails(
                name=item_name,
                quantity=item_qty,
                bagel_choice=bagel_choice,
                toasted=toasted,
                modifications=modifications,
            ))
            # Add to parsed_items for generic handling
            parsed_items.append(ParsedMenuItemEntry(
                menu_item_name=item_name,
                quantity=item_qty,
                bagel_type=bagel_choice,
                toasted=toasted,
                modifiers=modifications,
            ))
            logger.info("Multi-item: detected menu item '%s' (qty=%d, bagel=%s, toasted=%s, mods=%s)",
                        item_name, item_qty, bagel_choice, toasted, modifications)
            continue

        parsed = parse_open_input_deterministic(part)
        if not parsed:
            logger.debug("Multi-item: could not parse part '%s' deterministically", part)
            continue

        if parsed.new_menu_item:
            menu_item_list.append(MenuItemOrderDetails(
                name=parsed.new_menu_item,
                quantity=parsed.new_menu_item_quantity or 1,
                bagel_choice=parsed.new_menu_item_bagel_choice,
                toasted=parsed.new_menu_item_toasted,
                modifications=parsed.new_menu_item_modifications or [],
            ))
            # Add to parsed_items for generic handling
            parsed_items.append(ParsedMenuItemEntry(
                menu_item_name=parsed.new_menu_item,
                quantity=parsed.new_menu_item_quantity or 1,
                bagel_type=parsed.new_menu_item_bagel_choice,
                toasted=parsed.new_menu_item_toasted,
                modifiers=parsed.new_menu_item_modifications or [],
            ))
            logger.info("Multi-item: detected menu item '%s' (qty=%d, mods=%s)",
                        parsed.new_menu_item, parsed.new_menu_item_quantity or 1, parsed.new_menu_item_modifications)

        if parsed.new_coffee:
            # Track coffee for new_coffee_* fields in return (backwards compat)
            if not coffee_list:
                # Only need first coffee for primary fields
                coffee_list.append(CoffeeOrderDetails(
                    drink_type=parsed.new_coffee_type or "coffee",
                    size=parsed.new_coffee_size,
                    iced=parsed.new_coffee_iced,
                    decaf=parsed.new_coffee_decaf,
                    quantity=parsed.new_coffee_quantity or 1,
                    milk=parsed.new_coffee_milk,
                    special_instructions=parsed.new_coffee_special_instructions,
                ))
            # Build sweeteners list from parsed values
            sweeteners = []
            if parsed.new_coffee_sweetener:
                sweeteners.append(SweetenerItem(
                    type=parsed.new_coffee_sweetener,
                    quantity=parsed.new_coffee_sweetener_quantity or 1,
                ))

            # Build syrups list from parsed values
            syrups = []
            if parsed.new_coffee_flavor_syrup:
                syrups.append(SyrupItem(
                    type=parsed.new_coffee_flavor_syrup,
                    quantity=getattr(parsed, 'new_coffee_syrup_quantity', 1) or 1,
                ))

            # Add to parsed_items for generic handling
            parsed_items.append(ParsedCoffeeEntry(
                drink_type=parsed.new_coffee_type or "coffee",
                size=parsed.new_coffee_size,
                temperature="iced" if parsed.new_coffee_iced else ("hot" if parsed.new_coffee_iced is False else None),
                milk=parsed.new_coffee_milk,
                quantity=parsed.new_coffee_quantity or 1,
                special_instructions=parsed.new_coffee_special_instructions,
                decaf=parsed.new_coffee_decaf,
                sweeteners=sweeteners,
                syrups=syrups,
            ))
            logger.info("Multi-item: detected coffee '%s' (qty=%d, decaf=%s, milk=%s, instructions=%s)",
                        parsed.new_coffee_type, parsed.new_coffee_quantity or 1,
                        parsed.new_coffee_decaf, parsed.new_coffee_milk, parsed.new_coffee_special_instructions)

        if parsed.new_bagel:
            bagel = True
            bagel_qty = parsed.new_bagel_quantity or 1
            bagel_type = parsed.new_bagel_type
            bagel_toasted = parsed.new_bagel_toasted
            bagel_scooped = parsed.new_bagel_scooped
            bagel_spread = parsed.new_bagel_spread
            bagel_spread_type = parsed.new_bagel_spread_type

            # Build special instructions string from list
            special_instructions = None
            if parsed.new_bagel_special_instructions:
                special_instructions = ", ".join(parsed.new_bagel_special_instructions)

            # Add to parsed_items for generic handling (always add, even without bagel_type)
            # Keep modifiers for backwards compatibility
            modifiers = []
            if bagel_spread:
                modifiers.append(bagel_spread)
            if bagel_spread_type:
                modifiers.append(bagel_spread_type)

            parsed_items.append(ParsedBagelEntry(
                bagel_type=bagel_type,  # May be None - will need config
                quantity=bagel_qty,
                toasted=bagel_toasted,
                scooped=bagel_scooped,
                spread=bagel_spread,
                spread_type=bagel_spread_type,
                proteins=parsed.new_bagel_proteins or [],
                cheeses=parsed.new_bagel_cheeses or [],
                toppings=parsed.new_bagel_toppings or [],
                special_instructions=special_instructions,
                needs_cheese_clarification=parsed.new_bagel_needs_cheese_clarification,
                modifiers=modifiers,
            ))
            logger.info("Multi-item: detected bagel (type=%s, qty=%d, toasted=%s, spread=%s, proteins=%s)",
                        bagel_type, bagel_qty, bagel_toasted, bagel_spread, parsed.new_bagel_proteins)

        if parsed.new_side_item:
            side_item = parsed.new_side_item
            side_item_qty = parsed.new_side_item_quantity or 1
            # Add to parsed_items for generic handling
            parsed_items.append(ParsedSideItemEntry(
                side_name=parsed.new_side_item,
                quantity=side_item_qty,
            ))
            logger.info("Multi-item: detected side item '%s' (qty=%d)", side_item, side_item_qty)

        if parsed.new_speed_menu_bagel:
            speed_menu_bagel = True
            speed_menu_bagel_name = parsed.new_speed_menu_bagel_name
            speed_menu_bagel_qty = parsed.new_speed_menu_bagel_quantity or 1
            speed_menu_bagel_toasted = parsed.new_speed_menu_bagel_toasted
            speed_menu_bagel_bagel_choice = parsed.new_speed_menu_bagel_bagel_choice
            speed_menu_bagel_modifications = parsed.new_speed_menu_bagel_modifications
            # Add to parsed_items for generic handling
            parsed_items.append(ParsedSpeedMenuBagelEntry(
                speed_menu_name=parsed.new_speed_menu_bagel_name,
                bagel_type=parsed.new_speed_menu_bagel_bagel_choice,
                toasted=parsed.new_speed_menu_bagel_toasted,
                quantity=speed_menu_bagel_qty,
                modifiers=parsed.new_speed_menu_bagel_modifications or [],
            ))
            logger.info("Multi-item: detected speed menu bagel '%s' (qty=%d, toasted=%s, bagel=%s)",
                        speed_menu_bagel_name, speed_menu_bagel_qty, speed_menu_bagel_toasted, speed_menu_bagel_bagel_choice)

    # Get first menu item for primary fields, rest go to additional_menu_items
    first_menu_item = menu_item_list[0] if menu_item_list else None
    additional_menu_items = menu_item_list[1:] if len(menu_item_list) > 1 else []

    items_found = sum([
        len(menu_item_list) > 0,
        len(coffee_list) > 0,
        bagel,
        side_item is not None,
        speed_menu_bagel,
        len(by_pound_items) > 0,
    ])
    total_items = len(menu_item_list) + len(coffee_list) + (1 if bagel else 0) + (1 if side_item else 0) + (1 if speed_menu_bagel else 0) + len(by_pound_items)

    # Use parsed_items count as source of truth - it correctly tracks all items including
    # multiple bagels of different types (e.g., "plain bagel and sesame bagel")
    if items_found >= 2 or total_items >= 2 or len(parsed_items) >= 2:
        first_coffee = coffee_list[0] if coffee_list else None
        logger.info("Multi-item order parsed: menu_items=%d, coffees=%d, bagel=%s, side=%s, speed_menu=%s, parsed_items=%d",
                    len(menu_item_list), len(coffee_list), bagel, side_item, speed_menu_bagel_name, len(parsed_items))
        return OpenInputResponse(
            new_menu_item=first_menu_item.name if first_menu_item else None,
            new_menu_item_quantity=first_menu_item.quantity if first_menu_item else 1,
            new_menu_item_bagel_choice=first_menu_item.bagel_choice if first_menu_item else None,
            new_menu_item_toasted=first_menu_item.toasted if first_menu_item else None,
            new_menu_item_modifications=first_menu_item.modifications if first_menu_item else [],
            additional_menu_items=additional_menu_items,
            new_coffee=first_coffee is not None,
            new_coffee_type=first_coffee.drink_type if first_coffee else None,
            new_coffee_quantity=first_coffee.quantity if first_coffee else 1,
            new_coffee_size=first_coffee.size if first_coffee else None,
            new_coffee_iced=first_coffee.iced if first_coffee else None,
            new_coffee_decaf=first_coffee.decaf if first_coffee else None,
            new_coffee_milk=first_coffee.milk if first_coffee else None,
            new_coffee_special_instructions=first_coffee.special_instructions if first_coffee else None,
            # coffee_details removed - use parsed_items instead
            new_bagel=bagel,
            new_bagel_quantity=bagel_qty,
            new_bagel_type=bagel_type,
            new_bagel_toasted=bagel_toasted,
            new_bagel_spread=bagel_spread,
            new_bagel_spread_type=bagel_spread_type,
            new_side_item=side_item,
            new_side_item_quantity=side_item_qty,
            new_speed_menu_bagel=speed_menu_bagel,
            new_speed_menu_bagel_name=speed_menu_bagel_name,
            new_speed_menu_bagel_quantity=speed_menu_bagel_qty,
            new_speed_menu_bagel_toasted=speed_menu_bagel_toasted,
            new_speed_menu_bagel_bagel_choice=speed_menu_bagel_bagel_choice,
            new_speed_menu_bagel_modifications=speed_menu_bagel_modifications or [],
            parsed_items=parsed_items,
            by_pound_items=by_pound_items,
        )

    if menu_item_list:
        # Build parsed_items for unified handler (Phase 8 dual-write)
        menu_parsed_items = [
            _build_menu_item_parsed_item(
                menu_item_name=item.name,
                quantity=item.quantity,
                bagel_type=item.bagel_choice,
                toasted=item.toasted,
                modifiers=item.modifications,
            )
            for item in menu_item_list
        ]
        return OpenInputResponse(
            new_menu_item=first_menu_item.name,
            new_menu_item_quantity=first_menu_item.quantity,
            new_menu_item_bagel_choice=first_menu_item.bagel_choice,
            new_menu_item_toasted=first_menu_item.toasted,
            new_menu_item_modifications=first_menu_item.modifications,
            additional_menu_items=additional_menu_items,
            parsed_items=menu_parsed_items,  # Dual-write for Phase 8
        )
    if coffee_list:
        first_coffee = coffee_list[0]
        return OpenInputResponse(
            new_coffee=True,
            new_coffee_type=first_coffee.drink_type,
            new_coffee_quantity=first_coffee.quantity,
            new_coffee_size=first_coffee.size,
            new_coffee_iced=first_coffee.iced,
            new_coffee_decaf=first_coffee.decaf,
            new_coffee_milk=first_coffee.milk,
            new_coffee_special_instructions=first_coffee.special_instructions,
            parsed_items=parsed_items,  # Use parsed_items instead of coffee_details
        )
    if bagel:
        # Build parsed_items for unified handler (Phase 8 dual-write)
        bagel_parsed_items = [
            _build_bagel_parsed_item(
                bagel_type=bagel_type,
                quantity=1,
                toasted=bagel_toasted,
                scooped=bagel_scooped,
                spread=bagel_spread,
                spread_type=bagel_spread_type,
            )
            for _ in range(bagel_qty)
        ]
        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=bagel_qty,
            new_bagel_type=bagel_type,
            new_bagel_toasted=bagel_toasted,
            new_bagel_scooped=bagel_scooped,
            new_bagel_spread=bagel_spread,
            new_bagel_spread_type=bagel_spread_type,
            parsed_items=bagel_parsed_items,  # Dual-write for Phase 8
        )
    if side_item:
        # Build parsed_items for unified handler (Phase 8 dual-write)
        side_parsed_items = [_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_item_qty)]
        return OpenInputResponse(
            new_side_item=side_item,
            new_side_item_quantity=side_item_qty,
            parsed_items=side_parsed_items,  # Dual-write for Phase 8
        )

    return None


# =============================================================================
# Main Deterministic Parser
# =============================================================================

def parse_open_input_deterministic(user_input: str, spread_types: set[str] | None = None) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.
    """
    text = user_input.strip()

    # Check for greetings
    if GREETING_PATTERNS.match(text):
        logger.debug("Deterministic parse: greeting detected")
        return OpenInputResponse(is_greeting=True)

    # Check for gratitude ("thank you", "thanks", etc.)
    if GRATITUDE_PATTERNS.match(text):
        logger.debug("Deterministic parse: gratitude detected")
        return OpenInputResponse(is_gratitude=True)

    # Check for help requests ("help", "I'm confused", "what can you do")
    if HELP_PATTERNS.match(text):
        logger.debug("Deterministic parse: help request detected")
        return OpenInputResponse(is_help_request=True)

    # Check for done ordering
    if DONE_PATTERNS.match(text):
        logger.debug("Deterministic parse: done ordering detected")
        return OpenInputResponse(done_ordering=True)

    # Check for repeat order
    if REPEAT_ORDER_PATTERNS.match(text):
        logger.debug("Deterministic parse: repeat order detected")
        return OpenInputResponse(wants_repeat_order=True)

    # Strip filler words (after greeting/done checks, before order parsing)
    # e.g., "actually, make it two" -> "make it two"
    text = strip_filler_words(text)

    # Check for price inquiries
    price_result = _parse_price_inquiry_deterministic(text)
    if price_result:
        return price_result

    # Check for "show more" menu requests BEFORE menu queries
    # "what other pastries do you have?" should be pagination, not a new query
    more_items_result = _parse_more_menu_items(text)
    if more_items_result:
        return more_items_result

    # Check for menu category queries ("what sweets do you have?", "what desserts do you have?")
    menu_query_result = _parse_menu_query_deterministic(text)
    if menu_query_result:
        return menu_query_result

    # Check for recommendation questions
    recommendation_result = _parse_recommendation_inquiry(text)
    if recommendation_result:
        return recommendation_result

    # Check for store info inquiries
    store_info_result = _parse_store_info_inquiry(text)
    if store_info_result:
        return store_info_result

    # Check for item description inquiries
    item_desc_result = _parse_item_description_inquiry(text)
    if item_desc_result:
        return item_desc_result

    # Check for modifier/add-on inquiries
    modifier_inquiry_result = _parse_modifier_inquiry(text)
    if modifier_inquiry_result:
        return modifier_inquiry_result

    # Check for by-the-pound orders EARLY
    # Must be checked BEFORE spread/salad sandwich matching to prevent
    # "half a pound of whitefish salad" from matching "Whitefish Salad Sandwich"
    by_pound_result = _parse_by_pound_order(text)
    if by_pound_result:
        return by_pound_result

    # Check for speed menu bagels
    speed_menu_result = _parse_speed_menu_bagel_deterministic(text)
    if speed_menu_result:
        return speed_menu_result

    # Check for "make it 2" patterns BEFORE replacement (since "make it X" could match both)
    make_it_n_match = MAKE_IT_N_PATTERN.match(text)
    if make_it_n_match:
        # Find which group matched
        num_str = None
        for i in range(1, 9):
            if make_it_n_match.group(i):
                num_str = make_it_n_match.group(i).lower()
                break
        if num_str:
            # Convert to number
            word_to_num = {
                "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
            }
            if num_str.isdigit():
                target_qty = int(num_str)
            else:
                target_qty = word_to_num.get(num_str, 0)

            if target_qty >= 2:
                # User says "make it 2" means they want 2 total, so add (target - 1) more
                additional = target_qty - 1
                logger.info("Deterministic parse: 'make it N' detected, target=%d, adding %d more", target_qty, additional)
                return OpenInputResponse(duplicate_last_item=additional)

    # Check for "another bagel" / "one more coffee" patterns (with item type specified)
    # This must be checked BEFORE ONE_MORE_PATTERN since it's more specific
    another_item_match = ANOTHER_ITEM_TYPE_PATTERN.match(text)
    if another_item_match:
        item_keyword = another_item_match.group(1).lower()
        item_type = ANOTHER_ITEM_TYPE_KEYWORDS.get(item_keyword, item_keyword)
        logger.info("Deterministic parse: 'another %s' detected, treating as new %s", item_keyword, item_type)
        return OpenInputResponse(duplicate_new_item_type=item_type)

    # Check for "one more" / "another" patterns (without item type - needs clarification if multiple items)
    if ONE_MORE_PATTERN.match(text):
        logger.info("Deterministic parse: 'one more' / 'another' detected, adding 1 more")
        return OpenInputResponse(duplicate_last_item=1)

    # Check for modification to existing item BEFORE replacement patterns
    # This catches patterns like "make the bagel with scallion cream cheese"
    # which should modify an existing bagel, not trigger replace_last_item
    modify_existing_result = _parse_modify_existing_item(text, spread_types)
    if modify_existing_result:
        return modify_existing_result

    # Check for replacement phrases
    replace_match = REPLACE_ITEM_PATTERN.match(text)
    if replace_match:
        replacement_item = None
        for i in range(1, 11):  # 10 capture groups in REPLACE_ITEM_PATTERN
            if replace_match.group(i):
                replacement_item = replace_match.group(i)
                break
        if replacement_item:
            replacement_item = replacement_item.strip()
            replacement_item = re.sub(r"^(?:a|an)\s+", "", replacement_item, flags=re.IGNORECASE)
            logger.info("Deterministic parse: replacement detected, item='%s'", replacement_item)

            parsed_replacement = parse_open_input_deterministic(replacement_item, spread_types)
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    # Check for cancellation phrases
    cancel_match = CANCEL_ITEM_PATTERN.match(text)
    if cancel_match:
        cancel_item = None
        for i in range(1, 9):
            if cancel_match.group(i):
                cancel_item = cancel_match.group(i)
                break
        if cancel_item:
            cancel_item = cancel_item.strip()
            logger.info("Deterministic parse: cancellation detected, item='%s'", cancel_item)
            return OpenInputResponse(cancel_item=cancel_item)

    # Check for "add more" requests (add a third, add another, etc.)
    add_more_result = _parse_add_more_request(text)
    if add_more_result:
        return add_more_result

    # Check for split-quantity bagels FIRST (e.g., "two bagels one with lox one with cream cheese")
    # This MUST run BEFORE bagel_with_modifiers to handle multi-bagel orders with different configs
    split_qty_result = _parse_split_quantity_bagels(text)
    if split_qty_result:
        return split_qty_result

    # Check for bagel with modifiers FIRST (e.g., "everything bagel with bacon and egg")
    # This MUST run BEFORE multi-item parsing to prevent "with bacon and egg" from being
    # interpreted as multiple items. Also prevents "bacon" from matching as a side item.
    bagel_with_mods_result = _parse_bagel_with_modifiers(text)
    if bagel_with_mods_result:
        return bagel_with_mods_result

    # Check for multi-item orders (e.g., "one coffee and one latte", "bagel and a coffee")
    # Must be checked before single-item parsers to handle "X and Y" patterns
    multi_item_result = _parse_multi_item_order(text)
    if multi_item_result:
        return multi_item_result

    # Early check for spread/salad sandwiches
    text_lower = text.lower()
    has_bagel_mention = re.search(r"\bbagels?\b", text_lower)
    has_sandwich_mention = "sandwich" in text_lower

    if (has_sandwich_mention or not has_bagel_mention) and any(term in text_lower for term in [
        "cream cheese sandwich", "cream cheese",
        "salad sandwich", "tuna salad", "whitefish salad", "egg salad",
        "chicken salad", "salmon salad",
        "butter sandwich", "peanut butter", "nutella", "hummus",
        "avocado spread", "tofu"
    ]):
        menu_item, qty = _extract_menu_item_from_text(text)
        if menu_item:
            toasted = _extract_toasted(text)
            bagel_choice = _extract_bagel_type(text)
            modifications = _extract_menu_item_modifications(text)
            logger.info("EARLY MENU ITEM: matched '%s' -> %s (qty=%d, toasted=%s, bagel=%s, mods=%s)", text[:50], menu_item, qty, toasted, bagel_choice, modifications)
            # Build parsed_items for unified handler (Phase 8 dual-write)
            early_parsed_items = [_build_menu_item_parsed_item(menu_item_name=menu_item, quantity=1, bagel_type=bagel_choice, toasted=toasted, modifiers=modifications) for _ in range(qty)]
            return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty, new_menu_item_toasted=toasted, new_menu_item_bagel_choice=bagel_choice, new_menu_item_modifications=modifications, parsed_items=early_parsed_items)

    # Early check for standalone side items
    # NOTE: "bagel chips" goes through menu lookup for disambiguation (multiple flavors exist)
    standalone_side_items = {
        "latkes": "Latkes",
        "latke": "Latkes",
        "fruit cup": "Fruit Cup",
        "home fries": "Home Fries",
    }
    for keyword, canonical_name in standalone_side_items.items():
        if keyword in text_lower:
            qty = 1
            qty_match = re.match(r'^(\d+|one|two|three|four|five)\s+', text_lower)
            if qty_match:
                qty_str = qty_match.group(1)
                if qty_str.isdigit():
                    qty = int(qty_str)
                else:
                    qty = WORD_TO_NUM.get(qty_str, 1)
            logger.info("STANDALONE SIDE ITEM: matched '%s' -> %s (qty=%d)", text[:50], canonical_name, qty)
            # Build parsed_items for unified handler (Phase 8 dual-write)
            standalone_side_parsed_items = [_build_side_parsed_item(side_name=canonical_name, quantity=1) for _ in range(qty)]
            return OpenInputResponse(new_side_item=canonical_name, new_side_item_quantity=qty, parsed_items=standalone_side_parsed_items)

    # Early check for dessert/pastry items (cookies, brownies, muffins)
    # These get passed through to menu lookup for disambiguation
    # BUT skip if this looks like a menu query ("what X do you have?")
    is_menu_query = any(pattern in text_lower for pattern in [
        "what kind of", "what types of", "what do you have",
        "what's available", "what options", "do you have any",
        "what muffins", "what cookies", "what brownies", "what pastries", "what donuts",
    ])
    if not is_menu_query:
        # Keywords that should trigger menu lookup for disambiguation
        # Includes desserts, snacks, and other generic item categories
        dessert_keywords = [
            "cookie", "cookies",
            "brownie", "brownies",
            "muffin", "muffins",
            "pastry", "pastries",
            "donut", "donuts", "doughnut", "doughnuts",
            "chips",  # For disambiguation among bagel chips, potato chips, kettle chips, etc.
            "omelette", "omelettes", "omelet", "omelets",  # For disambiguation among omelette types
            "egg omelette", "egg omelet",  # Generic omelette requests
            "juice",  # For disambiguation among juice types (orange, apple, cranberry, etc.)
        ]
        for keyword in dessert_keywords:
            if keyword in text_lower:
                qty = 1
                qty_match = re.match(r'^(\d+|one|two|three|four|five|six)\s+', text_lower)
                if qty_match:
                    qty_str = qty_match.group(1)
                    if qty_str.isdigit():
                        qty = int(qty_str)
                    else:
                        qty = WORD_TO_NUM.get(qty_str, 1)

                # Extract the full item name including any qualifier (e.g., "blueberry muffin")
                # Look for pattern like "[qualifier] [qualifier] keyword" before the keyword
                # Common qualifiers: blueberry, chocolate chip, corn, banana walnut, etc.
                item_match = re.search(
                    rf'((?:[a-z]+\s+){{0,3}}){re.escape(keyword)}',
                    text_lower
                )
                if item_match:
                    full_item = item_match.group(0).strip()
                    # Remove common non-qualifier prefixes (articles, verbs, numbers)
                    full_item = re.sub(r'^(a|an|the|please|add|get|have|want|some|\d+|one|two|three|four|five|six)\s+', '', full_item)
                    # Clean up again in case of double articles like "a the blueberry"
                    full_item = re.sub(r'^(a|an|the)\s+', '', full_item)
                else:
                    full_item = keyword

                logger.info("DESSERT ITEM: matched '%s' -> %s (qty=%d)", text[:50], full_item, qty)
                # Return as menu_item so it goes through disambiguation
                # Build parsed_items for unified handler (Phase 8 dual-write)
                dessert_parsed_items = [_build_menu_item_parsed_item(menu_item_name=full_item, quantity=1) for _ in range(qty)]
                return OpenInputResponse(new_menu_item=full_item, new_menu_item_quantity=qty, parsed_items=dessert_parsed_items)

    # Check for known menu items FIRST - BEFORE any bagel patterns
    # This ensures specific items like "whitefish salad on everything bagel" are recognized
    # as menu items rather than just "everything bagel"
    menu_item, qty = _extract_menu_item_from_text(text)
    if menu_item:
        toasted = _extract_toasted(text)
        bagel_choice = _extract_bagel_type(text)
        modifications = _extract_menu_item_modifications(text)
        logger.info("DETERMINISTIC MENU ITEM (early): matched '%s' -> %s (qty=%d, toasted=%s, bagel=%s, mods=%s)", text[:50], menu_item, qty, toasted, bagel_choice, modifications)
        # Build parsed_items for unified handler (Phase 8 dual-write)
        menu_item_parsed_items = [_build_menu_item_parsed_item(menu_item_name=menu_item, quantity=1, bagel_type=bagel_choice, toasted=toasted, modifiers=modifications) for _ in range(qty)]
        return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty, new_menu_item_toasted=toasted, new_menu_item_bagel_choice=bagel_choice, new_menu_item_modifications=modifications, parsed_items=menu_item_parsed_items)

    # Check for bagel order with quantity
    quantity_match = BAGEL_QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity_str = quantity_match.group(1)
        quantity = _extract_quantity(quantity_str)

        if quantity:
            bagel_type = _extract_bagel_type(text)
            toasted = _extract_toasted(text)
            scooped = _extract_scooped(text)
            spread, spread_type = _extract_spread(text, spread_types)
            side_item, side_qty = _extract_side_item(text)

            logger.debug(
                "Deterministic parse: bagel order - qty=%d, type=%s, toasted=%s, scooped=%s, spread=%s/%s, side=%s",
                quantity, bagel_type, toasted, scooped, spread, spread_type, side_item
            )

            # Build parsed_items for unified handler (Phase 8 dual-write)
            bagel_qty_parsed_items = [
                _build_bagel_parsed_item(bagel_type=bagel_type, toasted=toasted, scooped=scooped, spread=spread, spread_type=spread_type)
                for _ in range(quantity)
            ]
            if side_item:
                bagel_qty_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=quantity,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_scooped=scooped,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
                parsed_items=bagel_qty_parsed_items,  # Dual-write for Phase 8
            )

    # Check for simple "a bagel" / "bagel please"
    if SIMPLE_BAGEL_PATTERN.search(text):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        scooped = _extract_scooped(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        logger.debug(
            "Deterministic parse: single bagel - type=%s, toasted=%s, scooped=%s, spread=%s/%s, side=%s",
            bagel_type, toasted, scooped, spread, spread_type, side_item
        )

        # Build parsed_items for unified handler (Phase 8 dual-write)
        simple_bagel_parsed_items = [_build_bagel_parsed_item(bagel_type=bagel_type, toasted=toasted, scooped=scooped, spread=spread, spread_type=spread_type)]
        if side_item:
            simple_bagel_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=1,
            new_bagel_type=bagel_type,
            new_bagel_toasted=toasted,
            new_bagel_scooped=scooped,
            new_bagel_spread=spread,
            new_bagel_spread_type=spread_type,
            new_side_item=side_item,
            new_side_item_quantity=side_qty,
            parsed_items=simple_bagel_parsed_items,  # Dual-write for Phase 8
        )

    # Check if text contains "bagel" anywhere (but only if no menu item was matched earlier)
    if re.search(r"\bbagels?\b", text, re.IGNORECASE):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        scooped = _extract_scooped(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        if bagel_type or toasted is not None or scooped is not None or spread or side_item:
            logger.debug(
                "Deterministic parse: bagel mention - type=%s, toasted=%s, scooped=%s, spread=%s/%s, side=%s",
                bagel_type, toasted, scooped, spread, spread_type, side_item
            )
            # Build parsed_items for unified handler (Phase 8 dual-write)
            bagel_mention_parsed_items = [_build_bagel_parsed_item(bagel_type=bagel_type, toasted=toasted, scooped=scooped, spread=spread, spread_type=spread_type)]
            if side_item:
                bagel_mention_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=1,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_scooped=scooped,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
                parsed_items=bagel_mention_parsed_items,  # Dual-write for Phase 8
            )

    # Check for split-quantity drinks FIRST (e.g., "two coffees one with milk one black")
    # This MUST run BEFORE regular coffee parsing to handle multi-drink orders with different configs
    split_qty_drinks_result = _parse_split_quantity_drinks(text)
    if split_qty_drinks_result:
        logger.info(
            "DETERMINISTIC SPLIT-QTY DRINKS: matched '%s' -> %d drinks",
            text[:50], len(split_qty_drinks_result.coffee_details)
        )
        return split_qty_drinks_result

    # Check for soda/bottled drink order FIRST (more specific names like "Snapple Iced Tea")
    soda_result = _parse_soda_deterministic(text)
    if soda_result:
        logger.info("DETERMINISTIC SODA: matched '%s'", text[:50])
        return soda_result

    # Check for coffee/sized beverage order (more generic names like "iced tea")
    coffee_result = _parse_coffee_deterministic(text)
    if coffee_result:
        logger.info("DETERMINISTIC COFFEE: matched '%s' -> type=%s", text[:50], coffee_result.new_coffee_type)
        return coffee_result

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None
