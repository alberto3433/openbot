"""
Deterministic Parsing Functions (no LLM).

This module contains all regex/string-based parsing functions that don't
require LLM calls. These are used for fast, consistent parsing of common
input patterns like greetings, simple bagel orders, coffee orders, etc.
"""

import re
import logging

from orderbot.menu_data_cache import menu_cache

from ..schemas import (
    OpenInputResponse,
    ExtractedModifiers,
    # Generic type for modifiers with quantity (sweeteners, syrups, etc.)
    QuantifiedModifier,
    # Qualifier conflict model
    QualifierConflict,
    # ParsedItem types for multi-item handling
    ParsedItemEntry,  # Unified type for all items
)
from .constants import (
    WORD_TO_NUM,
    get_signature_item_aliases,
    # Dynamic spread functions (loaded from database)
    get_spreads,
    QUALIFIER_PATTERNS,
    STANDALONE_INSTRUCTION_PATTERNS,
    # GREETING_PATTERNS and DONE_PATTERNS are now loaded from database via menu_cache.get_response_regex()
    GRATITUDE_PATTERNS,
    HELP_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    get_known_menu_items,
    get_soda_types,
    get_coffee_types,
    resolve_coffee_alias,
    resolve_soda_alias,
    PRICE_INQUIRY_PATTERNS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    # Note: NYC_NEIGHBORHOOD_ZIPS moved to database - use menu_data["neighborhood_zip_codes"]
    RECOMMENDATION_PATTERNS,
    ITEM_DESCRIPTION_PATTERNS,
    MODIFIER_INQUIRY_PATTERNS,
    MORE_MENU_ITEMS_PATTERNS,
    CUSTOMER_SERVICE_PATTERNS,
    find_by_pound_item,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Generic Parsed Item Builder (Data-Driven)
# =============================================================================

def build_parsed_item(
    item_type: str,
    *,
    item_name: str | None = None,
    quantity: int = 1,
    attribute_values: dict | None = None,
    modifiers: list[QuantifiedModifier] | None = None,
    special_instructions: str | None = None,
    original_text: str | None = None,
    is_signature: bool = False,
    weight_unit: str | None = None,
) -> ParsedItemEntry:
    """
    Build a ParsedItemEntry from provided data.

    This is a pure data assembly function with no domain knowledge.
    It accepts any item_type, any attribute names, any modifier categories.

    Args:
        item_type: The item type slug (e.g., "bagel", "sized_beverage", "menu_item")
        item_name: Specific menu item name if known
        quantity: Number of items
        attribute_values: Dict of attribute slug -> value
        modifiers: List of QuantifiedModifier with category set
        special_instructions: Free-form instructions text
        original_text: Original user input (for disambiguation context)
        is_signature: Whether this is a signature/speed menu item
        weight_unit: For by-pound items (e.g., "1/4 lb")

    Returns:
        ParsedItemEntry with all fields populated
    """
    return ParsedItemEntry(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attribute_values=attribute_values or {},
        modifiers=modifiers or [],
        special_instructions=special_instructions,
        original_text=original_text,
        is_signature=is_signature,
        weight_unit=weight_unit,
    )


def extracted_modifiers_to_list(mods: ExtractedModifiers) -> list[QuantifiedModifier]:
    """Convert ExtractedModifiers to unified modifier list with categories."""
    result: list[QuantifiedModifier] = []
    for p in mods.proteins or []:
        result.append(QuantifiedModifier(slug=p, category="protein"))
    for c in mods.cheeses or []:
        result.append(QuantifiedModifier(slug=c, category="cheese"))
    for t in mods.toppings or []:
        result.append(QuantifiedModifier(slug=t, category="topping"))
    for s in mods.spreads or []:
        result.append(QuantifiedModifier(slug=s, category="spread"))
    if mods.sweetener:
        result.append(QuantifiedModifier(
            slug=mods.sweetener, category="sweetener", quantity=mods.sweetener_quantity
        ))
    if mods.flavor_syrup:
        result.append(QuantifiedModifier(
            slug=mods.flavor_syrup, category="syrup", quantity=mods.syrup_quantity
        ))
    return result


# =============================================================================
# Legacy Builder Functions (TO BE DELETED after migration)
# =============================================================================

def _build_bagel_parsed_item(
    bread: str | None = None,
    quantity: int = 1,
    toasted: bool | None = None,
    scooped: bool | None = None,
    spread: str | None = None,
    proteins: list[str] | None = None,
    cheeses: list[str] | None = None,
    toppings: list[str] | None = None,
    modifiers: list[str] | None = None,
    special_instructions: str | None = None,
) -> ParsedItemEntry:
    """Build a ParsedItemEntry for a bagel from boolean flag data.

    Returns the unified ParsedItemEntry type with item_type="bagel" and
    all bagel-specific data stored in attribute_values dict.

    Args:
        bread: The bread/bagel type (e.g., "everything", "plain")
        spread: Atomic spread slug (e.g., "scallion_cream_cheese", "butter")
    """
    from orderbot.tasks.schemas.parser_responses import QuantifiedModifier

    # Build attribute_values dict
    attr_values: dict = {}
    if bread is not None:
        attr_values["bread"] = bread
    if toasted is not None:
        attr_values["toasted"] = toasted
    if scooped is not None:
        attr_values["scooped"] = scooped
    if spread is not None:
        attr_values["spread"] = spread

    # Build unified modifiers list with category
    quantified_mods: list[QuantifiedModifier] = []
    for p in proteins or []:
        quantified_mods.append(QuantifiedModifier(slug=p, category="protein"))
    for c in cheeses or []:
        quantified_mods.append(QuantifiedModifier(slug=c, category="cheese"))
    for t in toppings or []:
        quantified_mods.append(QuantifiedModifier(slug=t, category="topping"))
    for m in modifiers or []:
        # Generic modifiers - category will be looked up later
        quantified_mods.append(QuantifiedModifier(slug=m, category=None))

    return ParsedItemEntry(
        item_type="bagel",
        quantity=quantity,
        attribute_values=attr_values,
        modifiers=quantified_mods,
        special_instructions=special_instructions,
    )


def _build_coffee_parsed_item(
    item_name: str,
    size: str | None = None,
    temperature: str | None = None,  # "iced" or "hot" - used for menu item name matching
    quantity: int = 1,
    milk: str | None = None,
    decaf: bool | None = None,
    cream_level: str | None = None,  # dark, light, regular
    special_instructions: str | None = None,
    sweeteners: list | None = None,
    syrups: list | None = None,
    extra_shots: int = 0,
    original_text: str | None = None,
) -> ParsedItemEntry:
    """Build a ParsedItemEntry for a coffee/beverage from boolean flag data.

    Returns the unified ParsedItemEntry type with item_type="sized_beverage" and
    all coffee-specific data stored in attribute_values dict.

    Args:
        item_name: The beverage name (e.g., "Hot Latte", "Iced Coffee")

    Note: temperature is used to help match menu item names (e.g., "Iced Latte" vs
    "Hot Latte") but is NOT stored as a separate attribute since temperature is now
    part of the menu item name itself.
    """
    # Incorporate temperature into item_name for menu item name matching
    # e.g., "latte" + "iced" -> "iced latte" to match "Iced Latte" menu item
    final_item_name = item_name
    if temperature and item_name and temperature.lower() not in item_name.lower():
        final_item_name = f"{temperature} {item_name}"

    # Build attribute_values dict
    # Note: temperature IS stored here for parsing context (what the user said),
    # but when creating MenuItemTask, temperature becomes part of the menu_item_name.
    attr_values: dict = {}
    if size is not None:
        attr_values["size"] = size
    if temperature is not None:
        attr_values["temperature"] = temperature
    if milk is not None:
        attr_values["milk"] = milk
    if decaf is not None:
        attr_values["decaf"] = decaf
    if cream_level is not None:
        attr_values["cream_level"] = cream_level
    if extra_shots:
        attr_values["extra_shots"] = extra_shots

    # Build unified modifiers list with category and quantity
    from orderbot.tasks.schemas.parser_responses import QuantifiedModifier
    quantified_mods: list[QuantifiedModifier] = []
    for sw in sweeteners or []:
        if isinstance(sw, QuantifiedModifier):
            quantified_mods.append(QuantifiedModifier(
                slug=sw.slug, category="sweetener", quantity=sw.quantity
            ))
        else:
            # Handle dict or other formats
            slug = sw.get("slug", sw) if isinstance(sw, dict) else str(sw)
            qty = sw.get("quantity", 1) if isinstance(sw, dict) else 1
            quantified_mods.append(QuantifiedModifier(
                slug=slug, category="sweetener", quantity=qty
            ))
    for sy in syrups or []:
        if isinstance(sy, QuantifiedModifier):
            quantified_mods.append(QuantifiedModifier(
                slug=sy.slug, category="syrup", quantity=sy.quantity
            ))
        else:
            slug = sy.get("slug", sy) if isinstance(sy, dict) else str(sy)
            qty = sy.get("quantity", 1) if isinstance(sy, dict) else 1
            quantified_mods.append(QuantifiedModifier(
                slug=slug, category="syrup", quantity=qty
            ))

    return ParsedItemEntry(
        item_type="sized_beverage",
        item_name=final_item_name,
        quantity=quantity,
        attribute_values=attr_values,
        modifiers=quantified_mods,
        special_instructions=special_instructions,
        original_text=original_text,
    )


def _build_signature_item_parsed_item(
    signature_item_name: str,
    bread: str | None = None,
    toasted: bool | None = None,
    quantity: int = 1,
    modifiers: list[str] | None = None,
) -> ParsedItemEntry:
    """Build a ParsedItemEntry for a signature item (is_signature=True)."""
    from orderbot.tasks.schemas.parser_responses import QuantifiedModifier

    attr_values: dict = {}
    if bread is not None:
        attr_values["bread"] = bread
    if toasted is not None:
        attr_values["toasted"] = toasted

    # Convert string modifiers to QuantifiedModifier (category looked up later)
    quantified_mods = [QuantifiedModifier(slug=m, category=None) for m in (modifiers or [])]

    return ParsedItemEntry(
        item_type="menu_item",
        item_name=signature_item_name,
        quantity=quantity,
        attribute_values=attr_values,
        modifiers=quantified_mods,
        is_signature=True,
    )


def _build_menu_item_parsed_item(
    item_name: str,
    quantity: int = 1,
    bread: str | None = None,
    toasted: bool | None = None,
    modifiers: list[str] | None = None,
) -> ParsedItemEntry:
    """Build a ParsedItemEntry for a menu item from boolean flag data."""
    from orderbot.tasks.schemas.parser_responses import QuantifiedModifier

    attr_values: dict = {}
    if bread is not None:
        attr_values["bread"] = bread
    if toasted is not None:
        attr_values["toasted"] = toasted

    # Convert string modifiers to QuantifiedModifier (category looked up later)
    quantified_mods = [QuantifiedModifier(slug=m, category=None) for m in (modifiers or [])]

    return ParsedItemEntry(
        item_type="menu_item",
        item_name=item_name,
        quantity=quantity,
        attribute_values=attr_values,
        modifiers=quantified_mods,
    )


def _build_side_parsed_item(
    side_name: str,
    quantity: int = 1,
) -> ParsedItemEntry:
    """Build a ParsedItemEntry for a side item (data-driven)."""
    return ParsedItemEntry(
        item_type="side",
        item_name=side_name,
        quantity=quantity,
    )


# =============================================================================
# Compiled Regex Patterns (internal use)
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

# "just one" / "only one" pattern - reduces quantity to 1 (removes extras)
# e.g., "actually just one bagel", "only one", "just one", "make it just one"
REDUCE_TO_ONE_PATTERN = re.compile(
    r"^(?:"
    # "actually just one bagel", "actually only one coffee"
    r"actually\s+(?:just|only)\s+(?:one|1)(?:\s+(bagel|bagels|coffee|coffees|drink|drinks|sandwich|sandwiches))?"
    r"|"
    # "just one bagel", "only one coffee", "just one", "only one"
    r"(?:just|only)\s+(?:one|1)(?:\s+(bagel|bagels|coffee|coffees|drink|drinks|sandwich|sandwiches))?"
    r"|"
    # "make it just one", "make it only one"
    r"make\s+(?:it|that)\s+(?:just|only)\s+(?:one|1)(?:\s+(bagel|bagels|coffee|coffees|drink|drinks|sandwich|sandwiches))?"
    r"|"
    # "i only want one", "i just want one bagel", "i only need one"
    r"i\s+(?:only|just)\s+(?:want|need|wanted)\s+(?:one|1)(?:\s+(bagel|bagels|coffee|coffees|drink|drinks|sandwich|sandwiches))?"
    r"|"
    # "one is enough", "one bagel is enough"
    r"(?:one|1)(?:\s+(bagel|bagels|coffee|coffees|drink|drinks|sandwich|sandwiches))?\s+is\s+(?:enough|fine|good)"
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
    "espresso": "espresso",  # Espresso uses MenuItemTask
    "espressos": "espresso",
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
# Modifier Qualifier Extraction Functions
# =============================================================================

def extract_modifiers_with_qualifiers(
    text: str,
    known_modifiers: set[str]
) -> tuple[list[str], list[tuple[str, str, str]] | None]:
    """
    Extract modifiers and their associated qualifiers from text.

    Scans the text for qualifier patterns (extra, light, on the side, etc.)
    from the database and associates them with adjacent modifiers.

    Args:
        text: The text to parse (e.g., "extra mayo and bacon on the side")
        known_modifiers: Set of valid modifiers to look for

    Returns:
        Tuple of:
        - List of formatted modifiers with qualifiers (e.g., ["Mayo (extra)", "Bacon (on the side)"])
        - List of conflicts if any (modifier, qualifier1, qualifier2 tuples), or None if no conflicts

    Examples:
        >>> extract_modifiers_with_qualifiers("extra mayo", {"mayo", "bacon"})
        (["Mayo (extra)"], None)

        >>> extract_modifiers_with_qualifiers("mayo on the side, crispy bacon", {"mayo", "bacon"})
        (["Mayo (on the side)", "Bacon (crispy)"], None)

        >>> extract_modifiers_with_qualifiers("light extra mayo", {"mayo"})
        ([], [("mayo", "light", "extra")])  # Conflict detected
    """
    text_lower = text.lower().strip()

    # Get qualifier patterns from database (sorted by length for longest match first)
    qualifier_patterns = menu_cache.get_qualifier_patterns()

    if not qualifier_patterns:
        # No qualifiers in database, fall back to simple modifier extraction
        formatted = []
        for modifier in sorted(known_modifiers, key=len, reverse=True):
            if re.search(rf'\b{re.escape(modifier)}\b', text_lower):
                normalized = menu_cache.normalize_modifier(modifier)
                if normalized not in formatted:
                    formatted.append(normalized)
        return (formatted, None)

    # Track found qualifiers with their positions
    # Format: [(start, end, pattern, normalized_form, category), ...]
    found_qualifiers: list[tuple[int, int, str, str, str]] = []

    for pattern in qualifier_patterns:
        # Find all occurrences of this qualifier pattern
        pattern_re = re.compile(rf'\b{re.escape(pattern)}\b', re.IGNORECASE)
        for match in pattern_re.finditer(text_lower):
            info = menu_cache.get_qualifier_info(pattern)
            if info:
                found_qualifiers.append((
                    match.start(),
                    match.end(),
                    pattern,
                    info["normalized_form"],
                    info["category"],
                ))

    # Track found modifiers with their positions
    # Format: [(start, end, modifier, normalized), ...]
    found_modifiers: list[tuple[int, int, str, str]] = []
    matched_spans: list[tuple[int, int]] = []

    # Mark qualifier spans to avoid matching modifiers inside them
    for start, end, _, _, _ in found_qualifiers:
        matched_spans.append((start, end))

    for modifier in sorted(known_modifiers, key=len, reverse=True):
        pattern_re = re.compile(rf'\b{re.escape(modifier)}\b', re.IGNORECASE)
        for match in pattern_re.finditer(text_lower):
            start, end = match.start(), match.end()
            # Check for overlap with existing spans
            overlaps = any(not (end <= s or start >= e) for s, e in matched_spans)
            if not overlaps:
                normalized = menu_cache.normalize_modifier(modifier)
                found_modifiers.append((start, end, modifier, normalized))
                matched_spans.append((start, end))

    # Associate qualifiers with modifiers
    # A qualifier applies to a modifier if it's adjacent (before or after)
    modifier_qualifiers: dict[str, list[tuple[str, str]]] = {}  # normalized_modifier -> [(normalized_qual, category), ...]
    conflicts: list[tuple[str, str, str]] = []

    for mod_start, mod_end, _, normalized_mod in found_modifiers:
        if normalized_mod not in modifier_qualifiers:
            modifier_qualifiers[normalized_mod] = []

        # Find qualifiers adjacent to this modifier
        for qual_start, qual_end, _, qual_normalized, qual_category in found_qualifiers:
            # Check if qualifier is adjacent (within 20 chars, accounting for spaces)
            # Qualifier before modifier: "extra mayo" -> qual_end near mod_start
            # Qualifier after modifier: "mayo on the side" -> mod_end near qual_start
            is_before = qual_end <= mod_start and mod_start - qual_end <= 15
            is_after = qual_start >= mod_end and qual_start - mod_end <= 15

            if is_before or is_after:
                # Check for conflicts in same category
                existing_categories = [cat for _, cat in modifier_qualifiers[normalized_mod]]
                if qual_category == "amount" and "amount" in existing_categories:
                    # Conflict: multiple amount qualifiers for same modifier
                    existing_amount = next(q for q, c in modifier_qualifiers[normalized_mod] if c == "amount")
                    conflicts.append((normalized_mod, existing_amount, qual_normalized))
                else:
                    modifier_qualifiers[normalized_mod].append((qual_normalized, qual_category))

    # Build formatted output
    formatted: list[str] = []

    for mod_start, mod_end, _, normalized_mod in found_modifiers:
        qualifiers = modifier_qualifiers.get(normalized_mod, [])
        if qualifiers:
            # Sort qualifiers for consistent output
            qual_strs = sorted(set(q for q, _ in qualifiers))
            formatted.append(f"{normalized_mod} ({', '.join(qual_strs)})")
        else:
            formatted.append(normalized_mod)

    return (formatted, conflicts if conflicts else None)


# =============================================================================
# Special Instructions Extraction
# =============================================================================

def extract_special_instructions_from_input(user_input: str) -> list[str]:
    """
    Extract special instructions from user input.

    Args:
        user_input: The raw user input string

    Returns:
        List of instruction strings like ["light cream cheese", "extra bacon", "leave room"]
    """
    instructions = []
    input_lower = user_input.lower()

    # Check qualifier patterns (e.g., "light X", "extra X", "no X")
    for pattern, qualifier in QUALIFIER_PATTERNS:
        for match in re.finditer(pattern, input_lower, re.IGNORECASE):
            item = match.group(1).strip()
            skip_words = {'the', 'a', 'an', 'and', 'or', 'on', 'with', 'please', 'thanks'}
            if item.lower() in skip_words:
                continue
            if qualifier == 'no':
                instruction = f"no {item}"
            elif qualifier == 'on the side':
                instruction = f"{item} on the side"
            else:
                instruction = f"{qualifier} {item}"
            if instruction not in instructions:
                instructions.append(instruction)
                logger.debug(f"Extracted special instruction: '{instruction}' from input")

    # Check standalone patterns (e.g., "leave room", "cut in half", "melted")
    for pattern in STANDALONE_INSTRUCTION_PATTERNS:
        match = re.search(pattern, input_lower, re.IGNORECASE)
        if match:
            instruction = match.group(0).strip()
            if instruction and instruction not in instructions:
                instructions.append(instruction)
                logger.debug(f"Extracted standalone instruction: '{instruction}' from input")

    return instructions


# Backwards compatibility alias
extract_notes_from_input = extract_special_instructions_from_input


# =============================================================================
# Generic Attribute Value Extraction (Data-Driven)
# =============================================================================

def extract_attribute_values(
    user_input: str,
    item_type: str,
) -> dict[str, any]:
    """
    Extract attribute values from user input for a specific item type.

    This is the generic, data-driven replacement for extract_modifiers_from_input()
    and extract_coffee_modifiers_from_input(). It queries the database for what
    attributes the item type has and matches input against those options.

    The same function works for any item type - coffee, bagel, steak, etc.
    What gets extracted depends entirely on what the database says the item type accepts.

    Args:
        user_input: The raw user input string
        item_type: The item type slug (e.g., "sized_beverage", "bagel", "steak")

    Returns:
        Dict mapping attribute slugs to extracted values:
        - For single_select: {attr_slug: option_slug}
        - For multi_select: {attr_slug: [{slug, quantity, display_name}, ...]}
        - For boolean: {attr_slug: True/False}

    Examples:
        >>> extract_attribute_values("large iced with oat milk", "sized_beverage")
        {"size": "large", "temperature": "iced", "milk": "oat"}

        >>> extract_attribute_values("medium rare with a side salad", "steak")
        {"doneness": "medium_rare", "side": "side_salad"}

        >>> extract_attribute_values("toasted with cream cheese", "bagel")
        {"toasted": True, "spread": [{"slug": "cream_cheese", "quantity": 1, ...}]}
    """
    result: dict[str, any] = {}
    input_lower = user_input.lower()

    # Get all attributes for this item type from database
    attributes = menu_cache.get_item_type_attributes(item_type)
    if not attributes:
        logger.debug("No attributes found for item type '%s'", item_type)
        return result

    # Track matched spans to avoid overlapping matches
    matched_spans: list[tuple[int, int]] = []

    def is_word_boundary(text: str, start: int, end: int) -> bool:
        """Check if the match is at word boundaries."""
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end >= len(text) or not text[end].isalnum()
        return before_ok and after_ok

    def spans_overlap(start: int, end: int) -> bool:
        """Check if position overlaps with any matched span."""
        return any(not (end <= s or start >= e) for s, e in matched_spans)

    def extract_quantity_before(pos: int) -> int:
        """Extract quantity prefix before a match position."""
        before_text = input_lower[:pos].strip()
        if not before_text:
            return 1

        qty_pattern = re.compile(
            r'(\d+|one|two|three|four|five|six|double|triple|extra)\s*$',
            re.IGNORECASE
        )
        qty_match = qty_pattern.search(before_text)
        if qty_match:
            qty_str = qty_match.group(1).lower()
            if qty_str.isdigit():
                return int(qty_str)
            elif qty_str == "double":
                return 2
            elif qty_str == "triple":
                return 3
            elif qty_str == "extra":
                return 2
            else:
                return WORD_TO_NUM.get(qty_str, 1)
        return 1

    def check_must_match(option: dict, text: str) -> bool:
        """Check if all must_match patterns are present in text."""
        must_match = option.get("must_match", [])
        if not must_match:
            return True  # No must_match requirement
        return all(pattern.lower() in text for pattern in must_match)

    def find_option_match(
        options: list[dict], text: str, is_multi_select: bool
    ) -> list[dict]:
        """Find all matching options in text, longest match first."""
        matches = []

        # Build list of (pattern, option, pattern_length) tuples
        # Sorted by pattern length descending for longest-match-first
        all_patterns: list[tuple[str, dict, int]] = []
        for opt in options:
            # Add display_name as a pattern
            display_name = opt.get("display_name", "").lower()
            if display_name:
                all_patterns.append((display_name, opt, len(display_name)))

            # Add slug as a pattern (convert underscores to spaces)
            slug = opt.get("slug", "")
            if slug:
                slug_as_words = slug.replace("_", " ").lower()
                all_patterns.append((slug_as_words, opt, len(slug_as_words)))
                # Also try slug as-is (with underscores)
                all_patterns.append((slug.lower(), opt, len(slug)))

            # Add aliases as patterns
            for alias in opt.get("aliases", []):
                alias_lower = alias.lower()
                all_patterns.append((alias_lower, opt, len(alias_lower)))

        # Sort by pattern length descending
        all_patterns.sort(key=lambda x: x[2], reverse=True)

        # Track which options we've already matched (by slug)
        matched_slugs: set[str] = set()

        for pattern, opt, _ in all_patterns:
            slug = opt.get("slug", "")
            if slug in matched_slugs:
                continue  # Already matched this option

            # Find all occurrences of pattern in text
            start = 0
            while True:
                pos = text.find(pattern, start)
                if pos == -1:
                    break

                end = pos + len(pattern)

                if is_word_boundary(text, pos, end) and not spans_overlap(pos, end):
                    # Check must_match patterns
                    if check_must_match(opt, text):
                        matched_spans.append((pos, end))
                        matched_slugs.add(slug)

                        quantity = extract_quantity_before(pos)
                        matches.append({
                            "slug": slug,
                            "display_name": opt.get("display_name", slug),
                            "quantity": quantity,
                            "price": opt.get("price", 0),
                            "category": opt.get("category"),
                        })
                        logger.debug(
                            "Extracted attribute value: '%s' -> '%s' (qty=%d)",
                            pattern, slug, quantity
                        )

                        if not is_multi_select:
                            return matches  # Single select - stop after first match
                        break  # Move to next option

                start = pos + 1

        return matches

    # Process each attribute
    for attr_slug, attr_config in attributes.items():
        options = attr_config.get("options", [])
        input_type = attr_config.get("input_type", "single_select")
        is_multi_select = input_type == "multi_select"

        if input_type == "boolean":
            # Handle boolean attributes (e.g., "toasted", "decaf")
            # Check for positive patterns
            display_name = attr_config.get("display_name", attr_slug).lower()
            if re.search(rf'\b{re.escape(display_name)}\b', input_lower):
                result[attr_slug] = True
                logger.debug("Extracted boolean attribute: %s = True", attr_slug)
            # Check for "not X" or "no X" patterns
            elif re.search(rf'\b(not?|no)\s+{re.escape(display_name)}\b', input_lower):
                result[attr_slug] = False
                logger.debug("Extracted boolean attribute: %s = False", attr_slug)
            continue

        if not options:
            continue  # Skip attributes without options

        matches = find_option_match(options, input_lower, is_multi_select)

        if matches:
            if is_multi_select:
                # Store list of matched values with quantities
                result[attr_slug] = matches
            else:
                # Store single value (just the slug)
                result[attr_slug] = matches[0]["slug"]

    # Extract special instructions (applicable to all item types)
    instructions = extract_special_instructions_from_input(user_input)
    if instructions:
        result["special_instructions"] = instructions

    logger.debug(
        "Extracted attribute values for %s: %s",
        item_type, result
    )
    return result


def extract_modifiers_for_item_type(
    user_input: str,
    item_type: str,
) -> ExtractedModifiers:
    """
    Extract modifiers from user input for a specific item type.

    This is the data-driven replacement for the legacy extract_modifiers_from_input()
    and extract_coffee_modifiers_from_input() functions. It wraps extract_attribute_values()
    and converts the result to ExtractedModifiers for backward compatibility.

    Args:
        user_input: The raw user input string
        item_type: The item type slug (e.g., "bagel", "sized_beverage", "deli_sandwich")

    Returns:
        ExtractedModifiers with categorized modifiers
    """
    attr_values = extract_attribute_values(user_input, item_type)

    if not attr_values:
        return ExtractedModifiers()

    # Convert flat dict to ExtractedModifiers
    modifiers = ExtractedModifiers()

    for attr_slug, value in attr_values.items():
        if attr_slug == "special_instructions":
            # Special instructions are a list of strings
            if isinstance(value, list):
                modifiers.special_instructions = value
            continue

        if isinstance(value, list):
            # Multi-select attribute: list of {slug, quantity, display_name, category, ...}
            for item in value:
                if isinstance(item, dict):
                    slug = item.get("slug", "")
                    quantity = item.get("quantity", 1)
                    # Use explicit category from item, or fall back to attr_slug
                    category = item.get("category") or attr_slug
                    if slug:
                        modifiers.add(category, slug, quantity)
        elif isinstance(value, bool):
            # Boolean attribute - store as single-value category with "yes"/"no"
            if value:
                modifiers.add(attr_slug, "yes", 1)
        elif isinstance(value, str):
            # Single-select attribute: just the slug
            modifiers.add(attr_slug, value, 1)

    return modifiers


# =============================================================================
# Helper Extraction Functions
# =============================================================================


# =============================================================================
# Generic Data-Driven Extraction Functions
# =============================================================================

def _slug_to_display(slug: str | None) -> str | None:
    """Convert slug to display format (underscores to spaces).

    Args:
        slug: Database slug (e.g., 'cinnamon_raisin', 'sun_dried_tomato')

    Returns:
        Display format (e.g., 'cinnamon raisin', 'sun dried tomato')
    """
    return slug.replace("_", " ") if slug else slug


def _extract_attribute_value(
    text: str,
    item_type: str,
    attr_slug: str
) -> str | bool | None:
    """Extract attribute value by looking up valid options from database.

    This is a generic replacement for item-specific extractors like
    _extract_size, _extract_iced, etc.

    Args:
        text: User input text (will be lowercased)
        item_type: Item type slug (e.g., "bagel", "sized_beverage")
        attr_slug: Attribute slug (e.g., "size", "toasted", "bread")

    Returns:
        Matched option value (slug or boolean), or None if no match

    Example:
        >>> _extract_attribute_value("large iced coffee", "sized_beverage", "size")
        "large"
        >>> _extract_attribute_value("everything bagel toasted", "bagel", "toasted")
        True
    """
    text_lower = text.lower()

    # Get attribute config for this item type
    attrs = menu_cache.get_item_type_attributes(item_type)
    attr_config = attrs.get(attr_slug)

    if not attr_config:
        return None

    input_type = attr_config.get("input_type", "single_select")

    # Boolean attributes (toasted, decaf, scooped, etc.)
    if input_type == "boolean":
        # Check for negative patterns first ("not toasted", "untoasted")
        slug_lower = attr_slug.lower()
        if re.search(rf"\b(?:not\s+{slug_lower}|un{slug_lower})\b", text_lower):
            return False
        # Check for positive pattern
        if re.search(rf"\b{slug_lower}(?:ed)?\b", text_lower):
            return True
        return None

    # Single/multi select attributes - check options
    options = attr_config.get("options", [])

    # Sort by length descending to match longer options first
    # (e.g., "cinnamon raisin" before "plain")
    options_sorted = sorted(options, key=lambda o: len(o.get("slug", "")), reverse=True)

    for option in options_sorted:
        slug = option.get("slug", "").lower()
        display = option.get("display_name", "").lower()

        # Check canonical slug
        if slug and slug in text_lower:
            return slug

        # Check display name
        if display and display in text_lower:
            return slug

        # Check aliases
        for alias in option.get("aliases", []):
            alias_lower = alias.lower()
            if alias_lower in text_lower:
                return slug

    return None


def _extract_all_attributes(
    text: str,
    item_type: str
) -> dict[str, any]:
    """Extract all attribute values for an item type from text.

    Args:
        text: User input text
        item_type: Item type slug

    Returns:
        Dict mapping attribute slugs to extracted values
    """
    text_lower = text.lower()
    attrs = menu_cache.get_item_type_attributes(item_type)
    extracted = {}

    for attr_slug in attrs.keys():
        value = _extract_attribute_value(text_lower, item_type, attr_slug)
        if value is not None:
            extracted[attr_slug] = value

    return extracted


def _extract_modifiers_generic(
    text: str,
    item_type: str
) -> list[str]:
    """Extract all modifiers for an item type from text.

    Uses the modifier category for the item type (food or beverage)
    to determine which modifier groups to search.

    Args:
        text: User input text (lowercase)
        item_type: Item type slug

    Returns:
        List of matched modifier names (normalized/canonical)
    """
    text_lower = text.lower()
    found_modifiers = []

    # Get modifier category for this item type (food or beverage)
    modifier_type = menu_cache.get_modifier_category(item_type)

    if modifier_type == "food":
        # Food modifiers: extracted in database-defined order (proteins, cheeses, toppings, spreads)
        for category in menu_cache.get_ordered_ingredient_categories("food"):
            # Get ingredients for this category
            ingredients = menu_cache.get_ingredients(category)
            for ingredient in ingredients:
                if ingredient.lower() in text_lower:
                    found_modifiers.append(ingredient.lower())

    elif modifier_type == "beverage":
        # Beverage modifiers are handled differently (syrups, sweeteners, milk)
        # These have quantities so they're extracted separately
        pass

    return found_modifiers


def _detect_item_type(text: str) -> tuple[str | None, str | None]:
    """Detect item type and matched menu item from text.

    Uses database-driven trigger keywords for each item type.

    Args:
        text: User input text

    Returns:
        (item_type_slug, menu_item_name) or (None, None)

    Example:
        >>> _detect_item_type("large iced latte")
        ("sized_beverage", "latte")
        >>> _detect_item_type("everything bagel toasted")
        ("bagel", "bagel")
    """
    text_lower = text.lower()

    # Get all item type triggers from cache
    all_triggers = menu_cache.get_item_type_triggers()

    # Sort item types by trigger length (longer matches first)
    # This ensures "bacon egg and cheese" matches before just "egg"
    best_match = None
    best_match_length = 0
    best_item_type = None

    for item_type_slug, triggers in all_triggers.items():
        # Check each trigger keyword
        for keyword in triggers:
            keyword_lower = keyword.lower()
            if keyword_lower in text_lower:
                # Prefer longer matches
                if len(keyword_lower) > best_match_length:
                    best_match_length = len(keyword_lower)
                    best_match = keyword
                    best_item_type = item_type_slug

    if best_item_type:
        return best_item_type, best_match

    return None, None


def _extract_by_pound_info(text: str) -> tuple[str | None, str | None]:
    """Extract by-pound weight unit and product name from text.

    Detects patterns like "quarter pound of cream cheese", "half lb salmon".

    Args:
        text: User input text

    Returns:
        (weight_unit, product_name) or (None, None) if not a by-pound pattern

    Example:
        >>> _extract_by_pound_info("quarter pound of plain cream cheese")
        ("1/4 lb", "plain cream cheese")
        >>> _extract_by_pound_info("half a pound of whitefish salad")
        ("1/2 lb", "whitefish salad")
    """
    text_lower = text.lower().strip()

    # Weight patterns to detect (pattern, normalized weight_unit)
    weight_patterns = [
        (r"(?:a\s+)?quarter\s+(?:pound|lb)", "1/4 lb"),
        (r"1/4\s*(?:pound|lb)", "1/4 lb"),
        (r"(?:a\s+)?half\s+(?:a\s+)?(?:pound|lb)", "1/2 lb"),
        (r"1/2\s*(?:pound|lb)", "1/2 lb"),
        (r"(?:one|1)\s+(?:pound|lb)", "1 lb"),
        (r"a\s+(?:pound|lb)", "1 lb"),
    ]

    for pattern, weight_unit in weight_patterns:
        match = re.search(pattern, text_lower)
        if match:
            # Extract product name (part after "of" or after weight)
            after_match = text_lower[match.end():].strip()
            # Remove "of" prefix if present
            if after_match.startswith("of "):
                after_match = after_match[3:].strip()
            # Remove trailing "please"
            after_match = re.sub(r"\s+please\s*$", "", after_match).strip()

            if after_match:
                return weight_unit, after_match

    return None, None


def _is_modifier_chain(text: str) -> bool:
    """Check if text is a single item with modifier chain.

    Detects patterns like "large iced coffee with sugar and 2 vanilla syrups"
    which should NOT be split on "and".

    Returns:
        True if text appears to be a single item with chained modifiers
    """
    if " with " not in text or " and " not in text:
        return False

    text_lower = text.lower()

    # Get the part after "with"
    parts = text_lower.split(" with ", 1)
    if len(parts) < 2:
        return False

    after_with = parts[1]

    if " and " not in after_with:
        return False

    # Get what's after "and"
    and_parts = after_with.split(" and ", 1)
    if len(and_parts) < 2:
        return False

    after_and = and_parts[1].strip()

    # Check if after_and contains an item keyword (would indicate multi-item)
    item_type, _ = _detect_item_type(after_and)
    if item_type:
        # Contains an item keyword - it's multi-item, not modifier chain
        return False

    # If no item keyword found, it's likely a modifier chain
    return True


def _protect_compound_phrases(
    text: str,
    compound_phrases: set[str]
) -> tuple[str, dict[str, str]]:
    """Replace compound phrases with placeholders to prevent splitting.

    Args:
        text: Input text (lowercase)
        compound_phrases: Set of phrases containing " and " that shouldn't be split

    Returns:
        (modified_text, {placeholder: original_phrase})
    """
    placeholder_map = {}
    result = text

    # Sort by length descending to match longer phrases first
    for phrase in sorted(compound_phrases, key=len, reverse=True):
        if phrase in result:
            placeholder = f"__COMPOUND_{len(placeholder_map)}__"
            placeholder_map[placeholder] = phrase
            result = result.replace(phrase, placeholder)

    return result, placeholder_map


def _restore_compound_phrases(
    parts: list[str],
    placeholder_map: dict[str, str]
) -> list[str]:
    """Restore compound phrases from placeholders.

    Args:
        parts: List of text parts (may contain placeholders)
        placeholder_map: {placeholder: original_phrase}

    Returns:
        List of parts with placeholders replaced by original phrases
    """
    restored = []
    for part in parts:
        for placeholder, phrase in placeholder_map.items():
            part = part.replace(placeholder, phrase)
        restored.append(part)
    return restored


def _parse_item_generic(
    text: str,
    item_type: str | None = None,
    item_name: str | None = None
) -> ParsedItemEntry | None:
    """Parse any item type using database configuration.

    This is a generic parser that uses database-driven attribute and modifier
    extraction instead of item-type-specific logic. It works for all item types
    that have proper configuration in the database.

    Also handles by-pound items (e.g., "quarter pound of cream cheese").

    Args:
        text: User input text
        item_type: Detected item type slug (e.g., "bagel", "sized_beverage").
                   If None, will attempt to detect from text.
        item_name: Matched menu item name (if any)

    Returns:
        ParsedItemEntry with extracted attributes and modifiers, or None if
        unable to parse

    Example:
        >>> _parse_item_generic("large iced latte", "sized_beverage", "latte")
        ParsedItemEntry(item_type="sized_beverage", item_name="latte",
                       attribute_values={"size": "large", "temperature": "iced"})
        >>> _parse_item_generic("quarter pound of plain cream cheese")
        ParsedItemEntry(item_type="by_pound", item_name="plain cream cheese",
                       weight_unit="1/4 lb")
    """
    text_lower = text.lower()

    # Check for by-pound pattern first
    weight_unit, product_name = _extract_by_pound_info(text_lower)
    if weight_unit:
        # This is a by-pound order - find matching menu item
        by_weight_items = menu_cache.get_menu_items_by_unit_type("by_weight")
        matched_item = None
        for item_name in by_weight_items:
            # Check if product name matches (fuzzy match)
            item_lower = item_name.lower()
            if product_name in item_lower or any(
                word in item_lower for word in product_name.split() if len(word) > 3
            ):
                # Check if weight matches too
                if weight_unit.replace(" ", "") in item_lower.replace(" ", ""):
                    matched_item = item_name
                    break

        return ParsedItemEntry(
            item_type="by_pound",
            item_name=matched_item or product_name,
            quantity=1,
            weight_unit=weight_unit,
            original_text=text,
        )

    # Auto-detect item type if not provided
    if not item_type:
        item_type, detected_name = _detect_item_type(text_lower)
        if not item_type:
            return None
        if not item_name:
            item_name = detected_name

    # Extract quantity from text
    # Match patterns like "2 bagels", "three coffees", "a dozen bagels"
    quantity = 1
    qty_match = re.match(r'^(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+dozen|half\s+a\s+dozen|a\s+couple(?:\s+of)?)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1).strip()
        extracted_qty = _extract_quantity(qty_str)
        if extracted_qty is not None:
            quantity = extracted_qty

    # Extract all attributes for this item type using database config
    attribute_values = _extract_all_attributes(text_lower, item_type)

    # Extract modifiers (proteins, spreads, toppings, etc.)
    modifiers = _extract_modifiers_generic(text_lower, item_type)

    # Extract sweeteners, syrups, milk using generic data-driven extraction
    # This works for ANY item type that has these attributes defined in the database
    sweeteners = []
    syrups = []
    if item_type:
        attrs = menu_cache.get_item_type_attributes(item_type)
        generic_extracted = extract_attribute_values(text, item_type)

        # Helper to filter extracted values by type using slug/display_name patterns
        # This handles combined attributes (like milk_sweetener_syrup) where options
        # may not have category set consistently
        def is_milk_option(opt: dict) -> bool:
            """Check if option is a milk type based on slug/display_name."""
            slug = opt.get("slug", "").lower()
            display = opt.get("display_name", "").lower()
            # Check for milk patterns (but not "syrup" to avoid false positives)
            return ("milk" in slug or "milk" in display or
                    slug == "half_n_half" or "half n half" in display.lower() or
                    "half and half" in display.lower())

        def is_syrup_option(opt: dict) -> bool:
            """Check if option is a syrup type based on slug/display_name."""
            slug = opt.get("slug", "").lower()
            display = opt.get("display_name", "").lower()
            return "syrup" in slug or "syrup" in display

        def is_sweetener_option(opt: dict) -> bool:
            """Check if option is a sweetener type based on slug/display_name/category."""
            slug = opt.get("slug", "").lower()
            category = opt.get("category", "")
            if category == "sweeteners":
                return True
            # Common sweetener slugs
            sweetener_slugs = {"sugar", "splenda", "equal", "sweet_n_low",
                              "sugar_in_the_raw", "stevia", "honey"}
            return slug in sweetener_slugs

        def extract_from_combined_attr(attr_slug: str, filter_fn) -> list[dict]:
            """Extract values from a combined attribute, filtering by type."""
            values = generic_extracted.get(attr_slug)
            if not values:
                return []
            if isinstance(values, list):
                return [v for v in values if isinstance(v, dict) and filter_fn(v)]
            if isinstance(values, str):
                # Single value - check if it matches the filter
                options = attrs.get(attr_slug, {}).get("options", [])
                for opt in options:
                    if opt.get("slug") == values and filter_fn(opt):
                        return [{"slug": values, "quantity": 1, "display_name": opt.get("display_name", values)}]
            return []

        # Check for combined milk_sweetener_syrup attribute
        combined_attr = "milk_sweetener_syrup"
        has_combined = combined_attr in attrs

        # Extract sweeteners
        if has_combined:
            sweetener_items = extract_from_combined_attr(combined_attr, is_sweetener_option)
        else:
            sweetener_attr_slug = menu_cache.resolve_field_to_slug(item_type, "sweetener")
            if sweetener_attr_slug in attrs:
                values = generic_extracted.get(sweetener_attr_slug)
                sweetener_items = values if isinstance(values, list) else ([{"slug": values, "quantity": 1}] if values else [])
            else:
                sweetener_items = []

        for item in sweetener_items:
            if isinstance(item, dict):
                sweeteners.append(QuantifiedModifier(
                    slug=item.get("slug", ""),
                    quantity=item.get("quantity", 1)
                ))

        # Extract syrups
        if has_combined:
            syrup_items = extract_from_combined_attr(combined_attr, is_syrup_option)
        else:
            syrup_attr_slug = menu_cache.resolve_field_to_slug(item_type, "syrup")
            if syrup_attr_slug not in attrs:
                syrup_attr_slug = menu_cache.resolve_field_to_slug(item_type, "flavor_syrup")
            if syrup_attr_slug in attrs:
                values = generic_extracted.get(syrup_attr_slug)
                syrup_items = values if isinstance(values, list) else ([{"slug": values, "quantity": 1}] if values else [])
            else:
                syrup_items = []

        for item in syrup_items:
            if isinstance(item, dict):
                syrups.append(QuantifiedModifier(
                    slug=item.get("slug", ""),
                    quantity=item.get("quantity", 1)
                ))

        # Extract milk
        if "milk" not in attribute_values:
            if has_combined:
                milk_items = extract_from_combined_attr(combined_attr, is_milk_option)
            else:
                milk_attr_slug = menu_cache.resolve_field_to_slug(item_type, "milk")
                if milk_attr_slug in attrs:
                    values = generic_extracted.get(milk_attr_slug)
                    milk_items = values if isinstance(values, list) else ([{"slug": values, "quantity": 1}] if values else [])
                else:
                    milk_items = []

            if milk_items:
                # Store just the slug without "_milk" suffix for backwards compatibility
                milk_slug = milk_items[0].get("slug", "")
                # Normalize: remove "_milk" suffix if present (e.g., "oat_milk" -> "oat")
                if milk_slug.endswith("_milk") and milk_slug != "whole_milk":
                    milk_slug = milk_slug[:-5]
                attribute_values["milk"] = milk_slug
            elif has_combined:
                # No specific milk type extracted, but check for generic "milk" patterns
                # e.g., "with milk", "splash of milk" should default to whole milk
                milk_patterns = [
                    r'\bwith\s+(?:a\s+)?(?:splash\s+of\s+)?milk\b',
                    r'\bwith\s+milk\b',
                    r'\bsplash\s+of\s+milk\b',
                    r'\bmilk\s+(?:on\s+the\s+side|please)\b',
                    r'\badd\s+(?:some\s+)?milk\b',
                ]
                for pattern in milk_patterns:
                    if re.search(pattern, text_lower):
                        attribute_values["milk"] = "whole"
                        break

        # Extract cream_level if item type has that attribute
        if "cream_level" in attrs and "cream_level" not in attribute_values:
            cream_value = generic_extracted.get("cream_level")
            if cream_value:
                attribute_values["cream_level"] = cream_value

    # Check if this is a signature/speed menu item
    is_signature = False
    if item_name:
        signature_items = get_signature_item_aliases()
        # Check if the menu item name matches any signature item
        name_lower = item_name.lower()
        if name_lower in signature_items or item_name in signature_items.values():
            is_signature = True

    # Extract special instructions (e.g., "splash of milk", "extra cream cheese")
    instructions_list = extract_special_instructions_from_input(text)
    special_instructions = ", ".join(instructions_list) if instructions_list else None

    # Build unified modifiers list with category
    # modifiers is list[str] from _extract_modifiers_generic
    # sweeteners/syrups are already list[QuantifiedModifier]
    unified_modifiers: list[QuantifiedModifier] = []

    # Add food modifiers (proteins, cheeses, toppings)
    for mod in modifiers:
        category = menu_cache.get_ingredient_category(mod)
        unified_modifiers.append(QuantifiedModifier(
            slug=mod, category=category, quantity=1
        ))

    # Add sweeteners with category
    for sw in sweeteners:
        unified_modifiers.append(QuantifiedModifier(
            slug=sw.slug, category="sweetener", quantity=sw.quantity
        ))

    # Add syrups with category
    for sy in syrups:
        unified_modifiers.append(QuantifiedModifier(
            slug=sy.slug, category="syrup", quantity=sy.quantity
        ))

    return ParsedItemEntry(
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        attribute_values=attribute_values,
        modifiers=unified_modifiers,
        special_instructions=special_instructions,
        is_signature=is_signature,
        original_text=text,
    )


def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of', 'a dozen'."""
    text = text.lower().strip()
    text = re.sub(r"\s+of$", "", text)
    # Normalize whitespace for compound expressions like "a  dozen" -> "a dozen"
    text = re.sub(r"\s+", " ", text)

    if text.isdigit():
        return int(text)

    return WORD_TO_NUM.get(text)


def _extract_toasted(text: str) -> bool | None:
    """Extract toasted preference from text."""
    text_lower = text.lower()

    # Check for "not toasted" or "untoasted" first (including typos)
    if re.search(r"\b(?:not\s+(?:toasted|tosted|tostd)|untoasted)\b", text_lower):
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


def _extract_spread(text: str) -> str | None:
    """Extract spread from text. Returns atomic spread slug.

    Matches user input against spread options from the database.
    Returns a single atomic slug (e.g., "scallion_cream_cheese", "butter").

    The slug can be looked up in GlobalAttributeOption for display_name and pricing.
    """
    text_lower = text.lower()

    # Get all spread options from database
    try:
        spread_options = menu_cache.get_global_attribute_options("spread")
    except Exception:
        # Fallback if spread attribute not found
        return None

    # Build list of (match_text, slug) tuples for matching
    # Include both display_name and aliases
    match_candidates: list[tuple[str, str]] = []
    for opt in spread_options:
        slug = opt.get("slug", "")
        display_name = opt.get("display_name", "").lower()
        if display_name:
            match_candidates.append((display_name, slug))
        # Also check aliases
        aliases = opt.get("aliases", [])
        if aliases:
            for alias in aliases:
                match_candidates.append((alias.lower(), slug))

    # Sort by match text length (longest first) to prefer specific matches
    match_candidates.sort(key=lambda x: len(x[0]), reverse=True)

    # Find the first (longest) match in the text
    for match_text, slug in match_candidates:
        if match_text in text_lower:
            return slug

    return None


def extract_spread_with_disambiguation(
    text: str,
) -> tuple[str | None, list[str]]:
    """
    Extract spread from text with disambiguation support.

    This function extends _extract_spread by using partial matching to find
    potential spread matches. When the user says something like "walnut
    cream cheese", it will find all spreads containing "walnut" and
    return them for disambiguation if there are multiple matches.

    Args:
        text: User input text

    Returns:
        Tuple of (spread_slug, disambiguation_options):
        - spread_slug: Atomic spread slug (e.g., "scallion_cream_cheese", "butter")
        - disambiguation_options: List of matching spread display names if ambiguous,
          empty list if exact match or no partial matches found

    Examples:
        >>> extract_spread_with_disambiguation("scallion cream cheese")
        ("scallion_cream_cheese", [])

        >>> extract_spread_with_disambiguation("walnut cream cheese")
        (None, ["Honey Walnut Cream Cheese", "Maple Raisin Walnut Cream Cheese"])

        >>> extract_spread_with_disambiguation("butter")
        ("butter", [])
    """
    text_lower = text.lower()
    disambiguation_options: list[str] = []

    # Get all spread options from database
    try:
        spread_options = menu_cache.get_global_attribute_options("spread")
    except Exception:
        return None, []

    # Build list of (match_text, slug, display_name) tuples for matching
    match_candidates: list[tuple[str, str, str]] = []
    for opt in spread_options:
        slug = opt.get("slug", "")
        display_name = opt.get("display_name", "")
        display_lower = display_name.lower()
        if display_lower:
            match_candidates.append((display_lower, slug, display_name))
        # Also check aliases
        aliases = opt.get("aliases", [])
        if aliases:
            for alias in aliases:
                match_candidates.append((alias.lower(), slug, display_name))

    # Sort by match text length (longest first) to prefer specific matches
    match_candidates.sort(key=lambda x: len(x[0]), reverse=True)

    # Try exact match first
    for match_text, slug, _ in match_candidates:
        if match_text in text_lower:
            return slug, []

    # No exact match - try partial matching for disambiguation
    words_to_check = text_lower
    for remove in ["cream cheese", "butter", "spread", "please", "thanks", "with", "on", "the", "a"]:
        words_to_check = words_to_check.replace(remove, " ")

    words = [w.strip() for w in words_to_check.split() if w.strip() and len(w.strip()) > 2]

    for word in words:
        matches = []
        for match_text, slug, display_name in match_candidates:
            if word in match_text:
                matches.append((slug, display_name))

        # Deduplicate by slug
        seen_slugs = set()
        unique_matches = []
        for slug, display_name in matches:
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                unique_matches.append((slug, display_name))

        if unique_matches:
            if len(unique_matches) == 1:
                return unique_matches[0][0], []
            else:
                # Multiple matches - return display names for disambiguation
                disambiguation_options = [m[1] for m in unique_matches]
                return None, disambiguation_options

    return None, []


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
    # Build dynamically from database (fail-fast if not loaded)
    coffee_modifiers: set[str] = set()
    # Add milk types and short forms
    for milk in menu_cache.get_ingredients("milk"):
        milk_lower = milk.lower()
        coffee_modifiers.add(milk_lower)
        if milk_lower.endswith(" milk"):
            coffee_modifiers.add(milk_lower[:-5])  # Short form like "oat"
    # Add syrup types and short forms
    for syrup in menu_cache.get_ingredients("syrup"):
        syrup_lower = syrup.lower()
        coffee_modifiers.add(syrup_lower)
        if syrup_lower.endswith(" syrup"):
            coffee_modifiers.add(syrup_lower[:-6])  # Short form like "vanilla"
    # Add sweetener types
    for sweetener in menu_cache.get_ingredients("sweetener"):
        coffee_modifiers.add(sweetener.lower())
    # Add standard coffee modifiers (temperature, size, etc.)
    coffee_modifiers.update({"iced", "hot", "decaf", "black", "small", "medium", "large", "nonfat", "2%"})

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


def _parse_modify_existing_item(text: str) -> OpenInputResponse | None:
    """Detect requests to modify an existing cart item with a spread.

    Catches patterns like:
    - "can I have scallion cream cheese on the cinnamon raisin bagel"
    - "put butter on the plain bagel"
    - "add cream cheese to the everything bagel"
    - "make the bagel with scallion cream cheese"
    - "make it with butter"

    This must be called BEFORE menu item matching to prevent "scallion cream cheese"
    from being matched to "Scallion Cream Cheese Sandwich".

    Spread options are loaded from the database cache (GlobalAttributeOption for "spread").

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

    # === Extract spread from spread_part (atomic slug) ===
    spread = _extract_spread(spread_part)

    # If we found a spread, this is a modification
    if spread:
        logger.info(
            "MODIFY EXISTING ITEM: '%s' -> spread=%s, target=%s",
            text[:50], spread, target_bagel
        )

        return OpenInputResponse(
            modify_existing_item=True,
            modify_target_description=target_bagel,
            modify_new_spread=spread,
        )

    return None


def _parse_add_modifier_to_item(text: str) -> OpenInputResponse | None:
    """Detect requests to add modifiers to an existing item.

    Catches patterns like:
    - "add X" - add single modifier to current/last item
    - "add X and Y" - add multiple modifiers
    - "add X to the Y" - add modifier to specific item
    - "extra X" / "more X" - alternative action words
    - "put X on it" - implicit target

    Does NOT catch patterns where the modifier text matches a known menu item
    (e.g., if "bacon egg and cheese" is a menu item alias, "add bacon egg and cheese"
    will be treated as a menu item order, not a modifier-add request).

    Returns OpenInputResponse with modify_existing_item=True if detected, None otherwise.
    """
    text_lower = text.lower().strip()

    # Get known modifiers from all food categories (database-driven)
    all_modifiers: set[str] = set()
    for category in menu_cache.get_ordered_ingredient_categories("food"):
        ingredients = menu_cache.get_ingredients(category)
        all_modifiers.update(ingredients)

    # === Pattern Group 1: "add/put/extra/more MODIFIER to the TARGET" ===
    # Captures: modifier(s) and target item
    target_patterns = [
        # "add bacon to the bagel" / "add bacon to the plain bagel"
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the|my)\s+(.+?)$",
        # "add bacon to the omelette" / "add bacon to my omelette"
        r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the|my)\s+(.+?)$",
    ]

    modifier_text = None
    target_item = None

    for pattern in target_patterns:
        match = re.match(pattern, text_lower)
        if match:
            modifier_text = match.group(1).strip()
            target_item = match.group(2).strip()
            break

    # === Pattern Group 2: "add/extra/more/put MODIFIER" (no explicit target) ===
    if not modifier_text:
        no_target_patterns = [
            # "add bacon" / "add bacon and cheese"
            r"^(?:add|put)\s+(.+?)(?:\s+please)?$",
            # "extra bacon" / "extra cheese"
            r"^extra\s+(.+?)(?:\s+please)?$",
            # "more bacon" / "more cheese"
            r"^more\s+(.+?)(?:\s+please)?$",
        ]

        for pattern in no_target_patterns:
            match = re.match(pattern, text_lower)
            if match:
                modifier_text = match.group(1).strip()
                target_item = None  # Implicit - apply to last/current item
                break

    # === Pattern Group 3: "put MODIFIER on it" ===
    if not modifier_text:
        match = re.match(r"^put\s+(.+?)\s+on\s+it(?:\s+please)?$", text_lower)
        if match:
            modifier_text = match.group(1).strip()
            target_item = None  # "it" means last/current item

    # No pattern matched
    if not modifier_text:
        return None

    # Check if modifier_text matches a known menu item (e.g., "bacon egg and cheese")
    # If so, this is likely a menu item order, not a modifier-add request.
    # Only skip if the menu item match covers most of the modifier_text - we don't want
    # to skip "add bacon and cheese" just because "bacon" is also a menu item.
    if len(modifier_text.split()) > 1:
        menu_item, _ = _extract_menu_item_from_text(modifier_text)
        if menu_item:
            # Only skip if the menu item name covers most of the modifier text
            # This prevents "bacon and cheese" from being skipped because "bacon" matches
            menu_item_lower = menu_item.lower()
            modifier_text_lower = modifier_text.lower()
            # Check if menu item name is a significant portion of the modifier text
            if len(menu_item_lower) >= len(modifier_text_lower) * 0.7:
                logger.debug("ADD MODIFIER: '%s' matches menu item '%s', skipping", modifier_text, menu_item)
                return None

    # === Parse modifier_text to extract individual modifiers with qualifiers ===
    # Handle "extra bacon and cheese on the side", "bacon, cheese, and tomato", etc.

    # Extract modifiers with qualifiers (e.g., "extra mayo" -> "mayo (extra)")
    modifiers_found, conflicts = extract_modifiers_with_qualifiers(
        modifier_text.lower(),
        all_modifiers
    )

    # Also check for category names (e.g., "cheese" in "add bacon and cheese")
    # This handles cases where "cheese" is a category name, not a specific ingredient
    all_food_categories = menu_cache.get_ordered_ingredient_categories("food")
    modifier_words = modifier_text.lower().split()
    for word in modifier_words:
        word_clean = word.strip(",;").strip()
        if word_clean in all_food_categories:
            # Found a category name - add it to modifiers if not already there
            category_title = word_clean.title()
            if category_title not in modifiers_found:
                modifiers_found.append(category_title)
                logger.debug("ADD MODIFIER: added category '%s' to modifiers", category_title)

    # If no known modifiers found (including categories), this isn't a modify request
    if not modifiers_found:
        return None

    # Clean up target_item if present (remove trailing "please", "thanks", etc.)
    if target_item:
        target_item = re.sub(r"\s*(please|thanks|thank you)$", "", target_item).strip()

    logger.info(
        "ADD MODIFIER TO ITEM: '%s' -> modifiers=%s, target=%s, conflicts=%s",
        text[:50], modifiers_found, target_item, conflicts
    )

    # Convert conflict tuples to QualifierConflict objects
    conflict_objects = None
    if conflicts:
        conflict_objects = [
            QualifierConflict(modifier=mod, qualifier1=q1, qualifier2=q2)
            for mod, q1, q2 in conflicts
        ]

    return OpenInputResponse(
        modify_existing_item=True,
        modify_target_description=target_item,
        modify_add_modifiers=modifiers_found,
        modify_qualifier_conflicts=conflict_objects,
    )


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
# Generic Configurable Item Parsing (Data-Driven)
# =============================================================================

def _parse_configurable_item(text: str) -> OpenInputResponse | None:
    """
    Parse orders for any configurable item type using data-driven patterns.

    This is the generic replacement for _parse_bagel_with_modifiers() and
    _parse_coffee_deterministic(). It uses database configuration to detect
    which item type is being ordered and extract the appropriate attributes.

    Algorithm:
    1. Check for exclusion phrases (e.g., "coffee cake" should not match "coffee")
    2. Detect item type from text by matching against configurable item type triggers
    3. If no configurable item type detected, return None
    4. Extract quantity
    5. Match specific menu item name within that type
    6. Extract attributes using extract_attribute_values()
    7. Extract modifiers using extract_modifiers_for_item_type()
    8. Build and return ParsedItemEntry

    Returns:
        OpenInputResponse with parsed_items if a configurable item was detected,
        None otherwise.
    """
    text_lower = text.lower().strip()

    # 1. Check for exclusion phrases (e.g., "coffee cake" -> not a coffee beverage)
    if menu_cache.text_matches_exclusion_phrase(text):
        logger.debug("CONFIGURABLE_ITEM: excluded by required_match_phrases: '%s'", text[:50])
        return None

    # 2. Detect which configurable item type this text matches
    configurable_slugs = menu_cache.get_configurable_item_type_slugs()
    detected_item_type: str | None = None
    best_match_length = 0

    for item_type_slug in configurable_slugs:
        triggers = menu_cache.get_item_type_triggers(item_type_slug)
        for trigger in triggers:
            # Check for word boundary match
            pattern = rf'\b{re.escape(trigger)}s?\b'
            if re.search(pattern, text_lower):
                # Prefer longer matches (more specific)
                if len(trigger) > best_match_length:
                    best_match_length = len(trigger)
                    detected_item_type = item_type_slug

    if not detected_item_type:
        return None

    logger.info("CONFIGURABLE_ITEM: detected type '%s' in '%s'", detected_item_type, text[:50])

    # 3. Extract quantity
    quantity = 1
    qty_match = re.match(
        r"^(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a\s+couple|half\s+(?:a\s+)?dozen|a?\s*dozen)\s+",
        text_lower
    )
    if qty_match:
        qty_str = qty_match.group(1).strip()
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # 4. Extract attribute values using data-driven extraction
    attr_values = extract_attribute_values(text, detected_item_type)

    # 5. Extract modifiers using data-driven extraction
    modifiers = extract_modifiers_for_item_type(text, detected_item_type)

    # 6. Try to match a specific menu item name within this type
    item_name = _match_menu_item_name_for_type(text, detected_item_type)

    # 7. Build ParsedItemEntry
    from orderbot.tasks.schemas.parser_responses import QuantifiedModifier

    # Build unified modifiers list from ExtractedModifiers
    quantified_mods: list[QuantifiedModifier] = []
    for p in modifiers.proteins:
        quantified_mods.append(QuantifiedModifier(slug=p, category="protein"))
    for c in modifiers.cheeses:
        quantified_mods.append(QuantifiedModifier(slug=c, category="cheese"))
    for t in modifiers.toppings:
        quantified_mods.append(QuantifiedModifier(slug=t, category="topping"))
    for s in modifiers.spreads:
        quantified_mods.append(QuantifiedModifier(slug=s, category="spread"))
    # Add sweeteners and syrups for beverages
    if modifiers.sweetener:
        quantified_mods.append(QuantifiedModifier(
            slug=modifiers.sweetener,
            category="sweetener",
            quantity=modifiers.sweetener_quantity
        ))
    if modifiers.flavor_syrup:
        quantified_mods.append(QuantifiedModifier(
            slug=modifiers.flavor_syrup,
            category="syrup",
            quantity=modifiers.syrup_quantity
        ))
    # Add milk as attribute value rather than modifier
    if modifiers.milk and "milk" not in attr_values:
        attr_values["milk"] = modifiers.milk
    if modifiers.cream_level and "cream_level" not in attr_values:
        attr_values["cream_level"] = modifiers.cream_level

    logger.info(
        "CONFIGURABLE_ITEM PARSED: type=%s, qty=%d, item_name=%s, attrs=%s, mods=%d",
        detected_item_type, quantity, item_name, list(attr_values.keys()), len(quantified_mods)
    )

    parsed_items = [
        ParsedItemEntry(
            item_type=detected_item_type,
            item_name=item_name,
            quantity=1,
            attribute_values=attr_values.copy(),
            modifiers=quantified_mods.copy(),
            original_text=text,
        )
        for _ in range(quantity)
    ]

    return OpenInputResponse(parsed_items=parsed_items)


def _match_menu_item_name_for_type(text: str, item_type_slug: str) -> str | None:
    """
    Try to match a specific menu item name within an item type.

    For example, for sized_beverage, this would try to match "Iced Latte",
    "Hot Coffee", "Chai Tea", etc.

    Args:
        text: User input text
        item_type_slug: The item type slug to search within

    Returns:
        The canonical menu item name if found, None otherwise
    """
    text_lower = text.lower()

    # Get all item names for this type
    item_names = menu_cache.get_item_names_by_type(item_type_slug)
    alias_to_canonical = menu_cache.get_item_alias_to_canonical_by_type(item_type_slug)

    # Try to match longest name first for specificity
    all_names_and_aliases = list(item_names) + list(alias_to_canonical.keys())
    all_names_and_aliases.sort(key=len, reverse=True)

    for name in all_names_and_aliases:
        pattern = rf'\b{re.escape(name)}s?\b'
        if re.search(pattern, text_lower):
            # Return canonical name
            return alias_to_canonical.get(name, name.title())

    return None


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

    Returns OpenInputResponse with parsed_items populated with ParsedItemEntry objects.
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
    base_bagel_type = _slug_to_display(_extract_attribute_value(first_split, "bagel", "bread"))

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

    # Create ParsedItemEntry for each part (unified system)
    parsed_items: list[ParsedItemEntry] = []
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
        part_bagel_type = _slug_to_display(_extract_attribute_value(part_lower, "bagel", "bread"))
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

        # Extract spread for this bagel (atomic slug from database)
        spread = _extract_spread(part_lower)

        # "plain" in split context means no spread - just a plain bagel
        # _extract_spread returns None if no spread found

        # Create entries for this part (may be >1 for uneven splits like "two not toasted")
        items_to_create = min(part_qty, total_quantity - item_count)
        for _ in range(items_to_create):
            parsed_items.append(build_parsed_item(
                item_type="bagel",
                quantity=1,
                attribute_values={
                    k: v for k, v in [
                        ("bread", bagel_type),
                        ("toasted", toasted),
                        ("spread", spread),
                    ] if v is not None
                },
            ))
            item_count += 1
            logger.info(
                "SPLIT-QUANTITY: bagel %d: type=%s, toasted=%s, spread=%s",
                item_count, bagel_type, toasted, spread
            )

    # If we have fewer entries than total_quantity, fill with base bagels
    while len(parsed_items) < total_quantity:
        parsed_items.append(build_parsed_item(
            item_type="bagel",
            quantity=1,
            attribute_values={
                k: v for k, v in [
                    ("bread", base_bagel_type),
                    ("toasted", base_toasted),
                ] if v is not None
            },
        ))

    # Phase 4: Only use parsed_items (deprecated fields removed)
    return OpenInputResponse(parsed_items=parsed_items)


def _parse_split_quantity_drinks(text: str) -> OpenInputResponse | None:
    """
    Parse orders with multiple drinks that have different configurations.

    Detects patterns like:
        - "two coffees one with milk one black"
        - "2 lattes, one iced, one hot"
        - "three teas one with sugar one with honey one plain"

    Returns OpenInputResponse with parsed_items populated with ParsedItemEntry objects.
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

    # Create ParsedItemEntry for each part (unified system)
    parsed_items: list[ParsedItemEntry] = []
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
            parsed_items.append(_build_coffee_parsed_item(
                item_name=base_drink_type,
                size=base_size,
                temperature=temperature,
                quantity=1,
                milk=milk,
                decaf=decaf,
                original_text=text,
            ))
            item_count += 1
            logger.info(
                "SPLIT-QUANTITY DRINKS: drink %d: type=%s, size=%s, iced=%s, decaf=%s, milk=%s",
                item_count, base_drink_type, base_size, iced, decaf, milk
            )

    # If we have fewer entries than total_quantity, fill with base drinks
    while len(parsed_items) < total_quantity:
        parsed_items.append(_build_coffee_parsed_item(
            item_name=base_drink_type,
            size=base_size,
            temperature="iced" if base_iced else ("hot" if base_iced is False else None),
            quantity=1,
            decaf=base_decaf,
            original_text=text,
        ))

    # Phase 4: Only use parsed_items (deprecated fields removed)
    return OpenInputResponse(parsed_items=parsed_items)


# =============================================================================
# Speed Menu Bagel Parsing
# =============================================================================

def _parse_signature_item_deterministic(text: str) -> OpenInputResponse | None:
    """Parse signature item orders like 'The Classic BEC on a wheat bagel'."""
    text_lower = text.lower()

    # Get signature items mapping from database
    signature_items = get_signature_item_aliases()

    matched_item = None
    matched_key = None

    for key in sorted(signature_items.keys(), key=len, reverse=True):
        if key in text_lower:
            matched_item = signature_items[key]
            matched_key = key
            break

    if not matched_item:
        return None

    # If user says "omelette" but matched item isn't an omelette, skip this match
    # Let the menu item parser handle omelettes properly (e.g., "truffled egg omelette")
    if re.search(r'\bomelet(?:te)?s?\b', text_lower) and 'omelette' not in matched_item.lower():
        logger.info("SIGNATURE ITEM SKIP: text contains 'omelette' but matched '%s' is not an omelette", matched_item)
        return None

    logger.info("SIGNATURE ITEM MATCH: found '%s' -> %s in text '%s'", matched_key, matched_item, text[:50])

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

    # Extract bagel/bread choice using data-driven attribute extraction
    bagel_choice = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))

    # Extract modifications (e.g., "with mayo and mustard", "no onions")
    modifications = _extract_menu_item_modifications(text)

    logger.info(
        "SIGNATURE ITEM PARSED: item=%s, qty=%d, toasted=%s, bagel_choice=%s, mods=%s",
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
            "SIGNATURE ITEM + COFFEE: also found coffee - type=%s, size=%s, iced=%s, decaf=%s",
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
        _build_signature_item_parsed_item(
            signature_item_name=matched_item,
            bread=bagel_choice,
            toasted=toasted,
            quantity=1,
            modifiers=modifications,
        )
        for _ in range(quantity)
    ]

    # Add coffee to parsed_items if found
    if coffee_type:
        parsed_items.append(_build_coffee_parsed_item(
            item_name=coffee_type,
            size=coffee_size,
            temperature="iced" if coffee_iced else ("hot" if coffee_iced is False else None),
            quantity=1,
            milk=coffee_milk,
            decaf=coffee_decaf,
        ))

    # Phase 4: Only use parsed_items (deprecated fields removed)
    return OpenInputResponse(parsed_items=parsed_items)


# =============================================================================
# Soda Parsing
# =============================================================================

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
        # Check for generic category terms that need clarification (data-driven)
        category_slug = menu_cache.get_category_needing_clarification(text_lower)
        if category_slug:
            logger.info("Deterministic parse: detected generic category term '%s', needs clarification", category_slug)
            return OpenInputResponse(needs_category_clarification=category_slug)

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
            item_name=canonical_name,
            quantity=1,
        )
        for _ in range(quantity)
    ]

    # Phase 4: Only use parsed_items (deprecated fields removed)
    return OpenInputResponse(parsed_items=parsed_items)


# =============================================================================
# By-the-Pound Order Parsing
# =============================================================================

# Pattern to match by-weight orders like "half a pound of whitefish salad"
# Captures: quantity phrase + item name
BY_POUND_PATTERN = re.compile(
    r"""
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

    # Strip common action verb prefixes - these indicate intent, not item type
    # The quantity phrase ("quarter pound", "half pound") identifies by-the-pound orders
    action_prefixes = [
        "i'll have ", "i will have ", "i have ", "i'll take ", "i will take ", "i take ",
        "i'll get ", "i will get ", "i get ", "i want ", "i'd like ", "i would like ",
        "i like ", "i need ", "give me ", "can i have ", "can i get ", "let me get ",
        "let me have ", "may i have ", "could i get ", "could i have ",
    ]
    for prefix in action_prefixes:
        if text_lower.startswith(prefix):
            text_lower = text_lower[len(prefix):]
            break

    match = BY_POUND_PATTERN.match(text_lower)
    if not match:
        return None

    # Extract weight and convert to (size, quantity) pair
    # Available sizes in DB: "1/4 lb" and "1 lb"
    half_lb = match.group(1)
    numeric_lb = match.group(2)
    a_lb = match.group(3)
    quarter_lb = match.group(4)
    item_name = match.group(5).strip()

    # Convert weight phrases to (size, quantity) pairs
    # size is "1/4 lb" or "1 lb", quantity is how many of that size
    if quarter_lb:
        size = "1/4 lb"
        item_quantity = 1
    elif half_lb:
        size = "1/4 lb"
        item_quantity = 2
    elif numeric_lb:
        # Handle fractions like "1/4", "1/2", "3/4"
        if "/" in numeric_lb:
            num, denom = numeric_lb.replace(" ", "").split("/")
            fraction = float(num) / float(denom)
            if fraction <= 0.25:
                size = "1/4 lb"
                item_quantity = 1
            elif fraction <= 0.5:
                size = "1/4 lb"
                item_quantity = 2
            elif fraction <= 0.75:
                size = "1/4 lb"
                item_quantity = 3
            else:
                size = "1 lb"
                item_quantity = 1
        else:
            # Whole number of pounds
            num = int(numeric_lb)
            size = "1 lb"
            item_quantity = num
    elif a_lb:
        size = "1 lb"
        item_quantity = 1
    else:
        size = "1 lb"
        item_quantity = 1

    # Look up the item in database via find_by_pound_item
    result = _find_by_pound_item_category(item_name)
    if not result:
        logger.debug("By-pound pattern matched but item not found: '%s'", item_name)
        return None

    canonical_name, category = result
    logger.info(
        "BY-POUND ORDER: '%s' -> %s (size=%s, qty=%d, category=%s)",
        text[:50], canonical_name, size, item_quantity, category
    )

    # Build parsed_items using ParsedItemEntry (unified type)
    # By-pound items are just sized menu items
    parsed_items = [
        ParsedItemEntry(
            item_type=category,  # "cheese", "fish", "spread", etc.
            item_name=canonical_name,
            quantity=item_quantity,
            attribute_values={"size": size},
        )
    ]

    return OpenInputResponse(
        parsed_items=parsed_items,
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

            # Look up category keyword in DB-loaded cache
            category_info = menu_cache.get_category_keyword_mapping(item_text)
            if category_info:
                menu_type = category_info["slug"]
                logger.info("PRICE INQUIRY (category): '%s' -> menu_query_type=%s", text[:50], menu_type)
                return OpenInputResponse(
                    asks_about_price=True,
                    menu_query=True,
                    menu_query_type=menu_type,
                )

            your_match = re.match(r"your\s+(.+)", item_text)
            if your_match:
                item_after_your = your_match.group(1).strip()
                category_info = menu_cache.get_category_keyword_mapping(item_after_your)
                if category_info:
                    menu_type = category_info["slug"]
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

            # Check if it maps to a known category (DB lookup)
            category_info = menu_cache.get_category_keyword_mapping(category_text)
            if category_info:
                menu_type = category_info["slug"]
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


def _parse_modifier_inquiry(
    text: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
) -> OpenInputResponse | None:
    """Parse modifier/add-on inquiry questions.

    Args:
        text: User input text to parse
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
            If None, modifier category detection is skipped but item detection still works.
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
            If None, item detection is skipped.
    """
    text_lower = text.lower().strip()
    keywords = modifier_category_keywords or {}
    item_keywords = modifier_item_keywords or {}

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
                item_type = item_keywords.get(item_text.lower())
                # If item_text doesn't match known items, it might be a category
                if not item_type and item_text.lower() in keywords:
                    category_text = item_text
                    item_text = None

            # Normalize category
            category = None
            if category_text:
                category = keywords.get(category_text.lower())

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
    """Parse 'show more' menu requests like 'what other drinks do you have?'

    Also extracts the category from "what other X" patterns so the handler can
    start a fresh query if no pagination context exists.
    """
    text_lower = text.lower().strip()

    for pattern in MORE_MENU_ITEMS_PATTERNS:
        if pattern.search(text_lower):
            logger.info("MORE MENU ITEMS: '%s'", text[:50])

            # Try to extract the category from "what other X" patterns
            # e.g., "what other signature sandwiches do you have?" -> "signature sandwiches"
            category_match = re.search(
                r'what (?:other|else|more) ([a-z]+(?: [a-z]+)*?)(?:\s+(?:do you have|are there|can i get|you got)|\?|$)',
                text_lower
            )
            category = None
            if category_match:
                category = category_match.group(1).strip()
                # Clean up common suffixes
                if category.endswith(' options'):
                    category = category[:-8].strip()
                if category:
                    logger.info("MORE MENU ITEMS: extracted category '%s'", category)

            return OpenInputResponse(wants_more_menu_items=True, more_menu_category=category)

    return None


# =============================================================================
# Ingredient-Based Menu Search
# =============================================================================

def _parse_ingredient_search(
    text: str,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse | None:
    """
    Parse ingredient-only inputs and return matching menu items.

    When a user types just an ingredient name (like "chicken" or "something with bacon"),
    this function searches for menu items that contain that ingredient by default.

    Args:
        text: User input text to parse
        ingredient_to_items: Mapping from ingredient names to menu items containing them.
            If None, ingredient search is disabled.

    Returns:
        OpenInputResponse with ingredient_search_query and ingredient_search_matches set,
        or None if no ingredient match found.
    """
    if not ingredient_to_items:
        return None

    text_lower = text.lower().strip()

    # Patterns that indicate ingredient search:
    # - "chicken" (standalone ingredient)
    # - "something with chicken"
    # - "anything with bacon"
    # - "items with turkey"
    # - "what has chicken"
    # - "do you have anything with chicken"

    # Pattern 1: "something/anything/items with [ingredient]"
    with_pattern = re.match(
        r'^(?:(?:i(?:\'?d| would)? like |(?:can i )?(?:get|have) )?'
        r'(?:something|anything|an item|items|a sandwich|sandwiches) '
        r'(?:with|that (?:has|have|contain|contains)) '
        r'(\w+))\s*[?.]?$',
        text_lower
    )
    if with_pattern:
        ingredient = with_pattern.group(1)
        if ingredient in ingredient_to_items:
            matches = ingredient_to_items[ingredient]
            logger.info(
                "INGREDIENT SEARCH: '%s' -> found %d items with '%s'",
                text[:50], len(matches), ingredient
            )
            return OpenInputResponse(
                ingredient_search_query=ingredient,
                ingredient_search_matches=matches,
            )

    # Pattern 2: "what has [ingredient]" / "what contains [ingredient]"
    what_has_pattern = re.match(
        r'^what (?:has|have|contains?) (\w+)\s*[?.]?$',
        text_lower
    )
    if what_has_pattern:
        ingredient = what_has_pattern.group(1)
        if ingredient in ingredient_to_items:
            matches = ingredient_to_items[ingredient]
            logger.info(
                "INGREDIENT SEARCH (what has): '%s' -> found %d items with '%s'",
                text[:50], len(matches), ingredient
            )
            return OpenInputResponse(
                ingredient_search_query=ingredient,
                ingredient_search_matches=matches,
            )

    # Pattern 3: Standalone ingredient name (e.g., just "chicken")
    # Only trigger if it's a short phrase (1-3 words) ending with an ingredient
    # This avoids triggering on complex orders
    words = text_lower.split()
    if len(words) <= 3:
        # Check if the last word is a known ingredient
        potential_ingredient = words[-1].rstrip('?.,!')
        if potential_ingredient in ingredient_to_items:
            # Make sure it's not part of an obvious order ("chicken sandwich", "bacon egg")
            # or a modification/removal command ("remove the bacon", "cancel the ham")
            # or an add-modifier command ("add bacon", "extra cheese")
            order_signals = [
                "bagel", "sandwich", "salad", "soup", "egg", "omelette",
                "omelet", "coffee", "latte", "please", "want", "like", "get",
                # Cancel/remove commands - should not trigger ingredient search
                "remove", "cancel", "delete", "take off", "no more", "drop",
                "forget", "skip", "hold the", "without", "lose the", "scratch",
                # Add-modifier commands - should not trigger ingredient search
                "add", "extra", "more", "put",
            ]
            has_order_signal = any(signal in text_lower for signal in order_signals)

            if not has_order_signal:
                matches = ingredient_to_items[potential_ingredient]
                logger.info(
                    "INGREDIENT SEARCH (standalone): '%s' -> found %d items with '%s'",
                    text[:50], len(matches), potential_ingredient
                )
                return OpenInputResponse(
                    ingredient_search_query=potential_ingredient,
                    ingredient_search_matches=matches,
                )

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
    # Phase 4: Use parsed_items instead of deprecated fields
    soda_result = _parse_soda_deterministic(item_text)
    if soda_result and soda_result.parsed_items:
        # Set quantity to 1 for "add another"
        for item in soda_result.parsed_items:
            item.quantity = 1
        item_name = soda_result.parsed_items[0].item_name if hasattr(soda_result.parsed_items[0], 'item_name') else "soda"
        logger.info("ADD MORE: parsed as soda '%s' (qty=1)", item_name)
        return soda_result

    # Try configurable item types (bagels, coffees, etc.) using data-driven parser
    configurable_result = _parse_configurable_item(item_text)
    if configurable_result and configurable_result.parsed_items:
        # Set quantity to 1 for "add another"
        for item in configurable_result.parsed_items:
            item.quantity = 1
        item_type = configurable_result.parsed_items[0].item_type if hasattr(configurable_result.parsed_items[0], 'item_type') else "item"
        logger.info("ADD MORE: parsed as configurable item '%s' (qty=1)", item_type)
        return configurable_result

    # Try signature item
    speed_result = _parse_signature_item_deterministic(item_text)
    if speed_result and speed_result.parsed_items:
        # Set quantity to 1 for "add another"
        for item in speed_result.parsed_items:
            item.quantity = 1
        item_name = speed_result.parsed_items[0].menu_item_name if hasattr(speed_result.parsed_items[0], 'menu_item_name') else "signature item"
        logger.info("ADD MORE: parsed as signature item '%s' (qty=1)", item_name)
        return speed_result

    # Try menu item
    menu_item, _ = _extract_menu_item_from_text(item_text)
    if menu_item:
        logger.info("ADD MORE: parsed as menu item '%s' (qty=1)", menu_item)
        return OpenInputResponse(
            parsed_items=[_build_menu_item_parsed_item(item_name=menu_item, quantity=1)],
        )

    # Try bagel
    if re.search(r'\bbagels?\b', item_text, re.IGNORECASE):
        bagel_type = _slug_to_display(_extract_attribute_value(item_text, "bagel", "bread"))
        toasted = _extract_toasted(item_text)
        scooped = _extract_scooped(item_text)
        spread = _extract_spread(item_text)
        logger.info("ADD MORE: parsed as bagel type='%s' (qty=1)", bagel_type)
        return OpenInputResponse(
            parsed_items=[_build_bagel_parsed_item(bread=bagel_type, toasted=toasted, scooped=scooped, spread=spread)],
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
                parsed_items=[_build_coffee_parsed_item(item_name=canonical, quantity=1)],
            )

    # Couldn't parse the item - fall back to LLM
    logger.debug("ADD MORE: couldn't parse item '%s', falling back", item_text)
    return None


# =============================================================================
# Smart Tokenization for Multi-Item Orders
# =============================================================================

# Quantity words mapping
_QUANTITY_WORDS = {
    "a": 1, "an": 1, "one": 1,
    "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
    "dozen": 12, "half dozen": 6,
}

# Words to skip during tokenization (not meaningful for classification)
_SKIP_WORDS = {"please", "thanks", "thank", "you", "with", "the", "some", "of"}


def _extract_leading_quantity(text: str) -> tuple[int | None, str]:
    """Extract leading quantity from text.

    Args:
        text: Input text like "2 bagels", "a coffee", "three lattes"

    Returns:
        (quantity, remaining_text) - quantity and text with quantity removed

    Examples:
        >>> _extract_leading_quantity("2 bagels")
        (2, "bagels")
        >>> _extract_leading_quantity("a coffee")
        (1, "coffee")
        >>> _extract_leading_quantity("three lattes")
        (3, "lattes")
        >>> _extract_leading_quantity("coffee")
        (None, "coffee")
    """
    text = text.strip()
    text_lower = text.lower()

    # Check for numeric prefix
    match = re.match(r'^(\d+)\s+', text)
    if match:
        return int(match.group(1)), text[match.end():].strip()

    # Check for quantity words
    for word, qty in sorted(_QUANTITY_WORDS.items(), key=lambda x: -len(x[0])):
        if text_lower.startswith(word + " "):
            return qty, text[len(word):].strip()
        if text_lower == word:
            return qty, ""

    return None, text


def _has_item_indicator(text: str) -> tuple[bool, str | None, str | None]:
    """Check if text contains an item type trigger or matches a menu item.

    Prioritizes item triggers that appear early in the text (especially after
    articles like "a", "an") over longer triggers that appear later. This
    correctly identifies "a bagel with cream cheese" as a bagel, not cream cheese.

    Args:
        text: Text to check

    Returns:
        (has_indicator, item_type, resolved_name)
        - (True, "sized_beverage", "Latte") if triggers coffee
        - (True, "egg_sandwich", "The Classic BEC") if matches menu item
        - (False, None, None) if no item indicator

    Examples:
        >>> _has_item_indicator("large iced latte")
        (True, "sized_beverage", "latte")
        >>> _has_item_indicator("bacon egg and cheese")
        (True, "egg_sandwich", "The Classic BEC")  # if alias exists
        >>> _has_item_indicator("cream cheese")
        (False, None, None)
    """
    text_lower = text.lower().strip()

    # First, check if entire text matches a menu item (including aliases)
    resolved = menu_cache.resolve_menu_item_alias(text_lower)
    if resolved:
        # Get the item type for this menu item
        item_type, _ = _detect_item_type(text_lower)
        return True, item_type, resolved

    # Check for item type triggers - prioritize early matches
    all_triggers = menu_cache.get_item_type_triggers()

    # Find all matches and their positions
    matches: list[tuple[int, int, str, str]] = []  # (position, length, item_type, trigger)

    for item_type_slug, triggers in all_triggers.items():
        for keyword in triggers:
            keyword_lower = keyword.lower()
            pos = text_lower.find(keyword_lower)
            if pos >= 0:
                matches.append((pos, len(keyword_lower), item_type_slug, keyword))

    # Add implicit triggers for item type names themselves
    # This handles cases where "bagel" type doesn't have "bagel" as explicit trigger
    # Use get_configurable_item_types() to include all item types, not just those with triggers
    all_item_types = menu_cache.get_configurable_item_types()
    for item_type_slug in all_item_types:
        # Check for the item type name (with underscores replaced by spaces)
        type_variants = [
            item_type_slug.lower(),
            item_type_slug.lower().replace("_", " "),
        ]
        for variant in type_variants:
            if variant in text_lower:
                pos = text_lower.find(variant)
                # Only add if not already matched at this position
                existing = [(m[0], m[2]) for m in matches]
                if (pos, item_type_slug) not in existing:
                    matches.append((pos, len(variant), item_type_slug, variant))

    if not matches:
        return False, None, None


    # Get modifiers and attribute options for deprioritizing modifier-based triggers
    all_modifiers = menu_cache.get_all_modifier_words()
    all_attr_options = menu_cache.get_all_attribute_option_words()
    # Get coffee types - these are primary triggers for beverage item types
    coffee_types = get_coffee_types()
    coffee_types_lower = {c.lower() for c in coffee_types}

    # Item type priority: prefer specific types over generic ones
    # When trigger is the same word for multiple types, prefer the type
    # that matches the trigger word itself (e.g., "bagel" -> bagel type)
    def _type_priority(item_type: str, trigger: str) -> int:
        """Return priority score (lower = better)."""
        trigger_lower = trigger.lower()
        # Best: item type matches the trigger word (bagel -> bagel)
        if item_type.lower() == trigger_lower:
            return 0
        # Also best: trigger is a known coffee/beverage type and item_type is a beverage type
        # e.g., "latte" -> sized_beverage should have high priority
        # Use data-driven check instead of hardcoding "sized_beverage"
        if trigger_lower in coffee_types_lower and menu_cache.get_modifier_category(item_type) == "beverage":
            return 1
        # Also best: trigger matches another item type name exactly
        # This means the trigger is likely targeting that specific type, not this one
        # e.g., "bagel" trigger for "side" type should yield to "bagel" type if it exists
        if trigger_lower in all_item_types or trigger_lower.replace(" ", "_") in all_item_types:
            # This item_type doesn't match the trigger, but another type does
            # Demote this match significantly
            return 6
        # Deprioritize triggers that are actually modifiers/attributes (but not coffee types)
        # e.g., "large" is a size, not an item indicator
        if trigger_lower in all_modifiers or trigger_lower in all_attr_options:
            return 5
        # Good: item type contains the trigger word (e.g., "egg_sandwich" contains "egg")
        if trigger_lower in item_type.lower():
            return 1
        # Generic types have lower priority
        generic_types = {"side", "snack", "beverage", "menu_item"}
        if item_type in generic_types:
            return 4
        return 2

    # Check if any trigger word matches an item type name
    # Add implicit match for that item type (with position from the trigger location)
    added_implicit = []
    for pos, length, item_type, trigger in list(matches):
        trigger_lower = trigger.lower()
        if trigger_lower in all_item_types and trigger_lower != item_type:
            # The trigger word is an item type name, add it as a match
            matches.append((pos, length, trigger_lower, trigger))
            added_implicit.append((pos, length, trigger_lower, trigger))
        trigger_underscore = trigger_lower.replace(" ", "_")
        if trigger_underscore in all_item_types and trigger_underscore != item_type:
            matches.append((pos, length, trigger_underscore, trigger))
            added_implicit.append((pos, length, trigger_underscore, trigger))

    # PRIORITY RULES:
    # 1. Priority 0 matches (trigger == item_type, e.g., "bagel" -> bagel) always win
    # 2. Among same-priority matches, prefer earlier position
    # 3. For position < 15, prefer that match unless priority 0 exists elsewhere

    # First, check if any match has priority 0 (trigger matches item type)
    priority_0_matches = [
        m for m in matches
        if _type_priority(m[2], m[3]) == 0
    ]

    if priority_0_matches:
        # Sort priority 0 matches by position, then length
        priority_0_matches.sort(key=lambda x: (x[0], -x[1]))
        best = priority_0_matches[0]
        return True, best[2], best[3]

    # No priority 0 matches - use priority + position logic
    # Sort by priority first, then position (within first 30 chars), then length
    def _match_score(m):
        pos, length, item_type, trigger = m
        priority = _type_priority(item_type, trigger)
        # Group positions: early (<=15), mid (16-30), late (>30)
        pos_group = 0 if pos <= 15 else (1 if pos <= 30 else 2)
        return (priority, pos_group, pos, -length)

    matches.sort(key=_match_score)

    best = matches[0]
    return True, best[2], best[3]


def _is_modifier_only(text: str) -> tuple[bool, list[str]]:
    """Check if text contains ONLY modifiers (no item triggers).

    Modifiers include:
    - Known ingredients (bacon, cheese, cream cheese, lox)
    - Known attribute options (large, medium, iced, hot)
    - Quantity words are skipped

    Args:
        text: Text to check

    Returns:
        (is_modifier_only, list_of_modifiers)
        - (True, ["cream cheese"]) if only modifiers
        - (False, []) if contains item trigger or unknown words

    Examples:
        >>> _is_modifier_only("cream cheese")
        (True, ["Cream Cheese"])
        >>> _is_modifier_only("bacon and cheese")
        (True, ["Bacon", "American Cheese"])
        >>> _is_modifier_only("large iced latte")
        (False, [])  # "latte" is an item trigger
    """
    text_lower = text.lower().strip()

    # Remove quantity prefix
    _, remaining = _extract_leading_quantity(text_lower)
    if not remaining:
        return False, []

    # Check if this has any item indicators
    has_item, _, _ = _has_item_indicator(remaining)
    if has_item:
        return False, []

    # Get lookup data
    all_modifiers = menu_cache.get_all_modifier_words()
    attr_options = menu_cache.get_all_attribute_option_words()

    # Tokenize and check each word/phrase
    # First try to match multi-word modifiers (e.g., "cream cheese")
    found_modifiers = []
    remaining_to_check = remaining

    # Try to match known multi-word modifiers first
    for modifier in sorted(all_modifiers, key=len, reverse=True):
        if modifier in remaining_to_check:
            normalized = menu_cache.normalize_modifier(modifier)
            found_modifiers.append(normalized)
            remaining_to_check = remaining_to_check.replace(modifier, " ").strip()

    # Check remaining words
    words = remaining_to_check.split()
    for word in words:
        word = word.strip().lower()
        if not word:
            continue

        # Skip common words
        if word in _SKIP_WORDS:
            continue

        # Skip "and" separator
        if word == "and":
            continue

        # Check if it's a known modifier
        if word in all_modifiers:
            normalized = menu_cache.normalize_modifier(word)
            if normalized not in found_modifiers:
                found_modifiers.append(normalized)
            continue

        # Check if it's a known attribute option
        if word in attr_options:
            continue

        # Unknown word - this is NOT modifier-only
        return False, []

    return True, found_modifiers


def _classify_token(text: str) -> "Token":
    """Classify a token from split input.

    Args:
        text: Token text to classify

    Returns:
        Token with classification info
    """
    from orderbot.tasks.schemas.parser_responses import Token

    text = text.strip()
    text_lower = text.lower()

    # Check for separator
    if text_lower in ("and", ","):
        return Token(original=text, token_type="separator")

    # Extract quantity
    quantity, remaining = _extract_leading_quantity(text)

    # If only quantity (e.g., just "a" or "2"), it's a quantity token
    if not remaining and quantity is not None:
        return Token(original=text, token_type="quantity", quantity=quantity)

    # Check if it has an item indicator
    has_item, item_type, resolved_name = _has_item_indicator(remaining if remaining else text)
    if has_item:
        return Token(
            original=text,
            token_type="item",
            quantity=quantity or 1,
            item_type=item_type,
            resolved_name=resolved_name,
        )

    # Check if it's modifier-only
    is_mod, modifiers = _is_modifier_only(remaining if remaining else text)
    if is_mod:
        return Token(
            original=text,
            token_type="modifier",
            resolved_name=", ".join(modifiers) if modifiers else None,
        )

    # Check if it's an attribute option
    attr_options = menu_cache.get_all_attribute_option_words()
    if text_lower in attr_options:
        return Token(
            original=text,
            token_type="attribute",
            attribute_slug=attr_options[text_lower],
        )

    # Unknown
    return Token(original=text, token_type="unknown")


def _smart_split_and_tokenize(text: str) -> list["Token"]:
    """Split text on separators and classify each part.

    Args:
        text: Full input text

    Returns:
        List of classified tokens

    Examples:
        >>> _smart_split_and_tokenize("bacon egg and cheese and a coffee")
        [Token("bacon egg", item), Token("cheese", modifier), Token("a coffee", item)]
    """
    from orderbot.tasks.schemas.parser_responses import Token

    text_lower = text.lower().strip()

    # First, try to match entire input as a single item
    has_item, item_type, resolved_name = _has_item_indicator(text_lower)
    if has_item and " and " not in text_lower and ", " not in text_lower:
        qty, _ = _extract_leading_quantity(text_lower)
        return [Token(
            original=text,
            token_type="item",
            quantity=qty or 1,
            item_type=item_type,
            resolved_name=resolved_name,
        )]

    # Split on " and " and ", "
    # Normalize separators
    normalized = text_lower.replace(", and ", ", ").replace(" and ", ", ")
    parts = [p.strip() for p in normalized.split(",") if p.strip()]

    if len(parts) < 2:
        # Not a multi-item order
        return []

    # Classify each part
    tokens = []
    for part in parts:
        token = _classify_token(part)
        tokens.append(token)

    return tokens


def _recombine_tokens(tokens: list["Token"]) -> list["Token"]:
    """Recombine modifier tokens with their associated item tokens.

    Modifier tokens are attached to the PREVIOUS item token.

    Args:
        tokens: List of classified tokens

    Returns:
        List of item tokens with modifiers combined

    Examples:
        >>> tokens = [Token("bacon egg", item), Token("cheese", modifier), Token("coffee", item)]
        >>> _recombine_tokens(tokens)
        [Token("bacon egg and cheese", item), Token("coffee", item)]
    """
    from orderbot.tasks.schemas.parser_responses import Token

    if not tokens:
        return []

    result = []
    current_item = None
    accumulated_modifiers = []

    for token in tokens:
        if token.token_type == "item":
            # Save previous item with its modifiers
            if current_item:
                if accumulated_modifiers:
                    # Combine item with modifiers
                    combined_text = current_item.original + " and " + " and ".join(
                        m.original for m in accumulated_modifiers
                    )
                    # Re-check if combined text matches a menu item
                    has_item, item_type, resolved = _has_item_indicator(combined_text.lower())
                    result.append(Token(
                        original=combined_text,
                        token_type="item",
                        quantity=current_item.quantity,
                        item_type=item_type or current_item.item_type,
                        resolved_name=resolved or current_item.resolved_name,
                    ))
                else:
                    result.append(current_item)
            current_item = token
            accumulated_modifiers = []

        elif token.token_type == "modifier":
            if current_item:
                accumulated_modifiers.append(token)
            else:
                # Modifier without preceding item - treat as unknown/skip
                logger.debug("Modifier token without preceding item: %s", token.original)

        elif token.token_type == "attribute":
            # Attributes attach to current item
            if current_item:
                accumulated_modifiers.append(token)

        elif token.token_type == "unknown":
            # Unknown tokens might be part of an item name
            # Try combining with previous
            if current_item:
                combined = current_item.original + " " + token.original
                has_item, item_type, resolved = _has_item_indicator(combined.lower())
                if has_item:
                    current_item = Token(
                        original=combined,
                        token_type="item",
                        quantity=current_item.quantity,
                        item_type=item_type,
                        resolved_name=resolved,
                    )
                else:
                    # Can't combine - save current and start fresh
                    result.append(current_item)
                    current_item = None
                    accumulated_modifiers = []

    # Don't forget the last item
    if current_item:
        if accumulated_modifiers:
            combined_text = current_item.original + " and " + " and ".join(
                m.original for m in accumulated_modifiers
            )
            has_item, item_type, resolved = _has_item_indicator(combined_text.lower())
            result.append(Token(
                original=combined_text,
                token_type="item",
                quantity=current_item.quantity,
                item_type=item_type or current_item.item_type,
                resolved_name=resolved or current_item.resolved_name,
            ))
        else:
            result.append(current_item)

    return result


# =============================================================================
# Multi-Item Order Parsing
# =============================================================================

def _parse_multi_item_order(user_input: str) -> OpenInputResponse | None:
    """Parse multi-item orders like 'The Lexington and an orange juice'.

    This function uses smart tokenization to split multi-item orders while
    properly handling compound phrases (resolved via menu item aliases) and
    modifier chains. All logic is data-driven with no hardcoded food references.

    Returns OpenInputResponse with parsed_items list if 2+ items detected.
    """
    text = user_input.strip()
    text_lower = text.lower()

    # --- Step 1: Check for modifier chain (don't split) ---
    # e.g., "large iced coffee with sugar and 2 vanilla syrups" should NOT be split
    if _is_modifier_chain(text_lower):
        logger.debug("Multi-item: skipping split - detected modifier chain: '%s'", text[:60])
        return None

    # --- Step 2: Use smart tokenization to split and classify ---
    tokens = _smart_split_and_tokenize(text_lower)
    if len(tokens) < 2:
        # Not a multi-item order (single item or nothing)
        return None

    # --- Step 3: Check if tokens are all modifiers (don't split) ---
    # e.g., "butter, cream cheese, not toasted" should not be split
    non_modifier_count = sum(1 for t in tokens if t.token_type in ("item", "unknown"))
    if non_modifier_count < 2:
        # Check if first token is item and rest are modifiers
        if tokens and tokens[0].token_type == "item":
            modifier_types = ("modifier", "attribute", "separator")
            rest_are_modifiers = all(t.token_type in modifier_types for t in tokens[1:])
            if rest_are_modifiers:
                logger.debug("Multi-item: skipping split - item with modifiers: '%s'", text[:60])
                return None

    # --- Step 3b: Check for item + modifiers that also match as items ---
    # e.g., "pumpernickel bagel, butter, not toasted" - butter is also a menu item
    # but in this context it's a modifier for the bagel
    if tokens and tokens[0].token_type == "item":
        all_modifiers = menu_cache.get_all_modifier_words()
        attr_options = menu_cache.get_all_attribute_option_words()

        # Get boolean attribute names (like "toasted", "scooped")
        # Check all item types that might match the first token (handles ambiguous detection)
        boolean_attrs: set[str] = set()
        all_triggers = menu_cache.get_item_type_triggers()
        first_text = tokens[0].original.lower()

        # Find all item types that have triggers matching words in the first token
        item_types_to_check: set[str] = set()
        for item_type_slug, triggers in all_triggers.items():
            for trigger in triggers:
                if trigger.lower() in first_text:
                    item_types_to_check.add(item_type_slug)
                    break

        # Collect boolean attrs from all matching item types
        for check_type in item_types_to_check:
            item_attrs = menu_cache.get_item_type_attributes(check_type)
            if item_attrs:
                for attr_name, attr_info in item_attrs.items():
                    # Boolean attrs have input_type: 'boolean'
                    if isinstance(attr_info, dict) and attr_info.get("input_type") == "boolean":
                        boolean_attrs.add(attr_name.lower())
                        boolean_attrs.add(attr_name.lower().replace("_", " "))

        def _is_potential_modifier(token_text: str) -> bool:
            """Check if text could be a modifier (ignoring item matches)."""
            text_clean = token_text.lower().strip()
            # Remove common words
            for skip in _SKIP_WORDS:
                text_clean = text_clean.replace(skip, " ").strip()
            # Split and check each word
            words = text_clean.split()
            for word in words:
                word = word.strip()
                if not word or word == "and" or word == "not":
                    continue
                # Check if it's a known modifier, attribute option, or boolean attr
                if word in all_modifiers or word in attr_options or word in boolean_attrs:
                    continue
                # Check multi-word phrases
                if text_clean in all_modifiers or text_clean in attr_options:
                    continue
                # Unknown word - not a modifier
                return False
            return True

        other_tokens = [t for t in tokens[1:] if t.token_type != "separator"]
        if other_tokens and all(_is_potential_modifier(t.original) for t in other_tokens):
            logger.debug("Multi-item: skipping split - item with modifier-like parts: '%s'", text[:60])
            return None

    # --- Step 4: Recombine modifier tokens with their items ---
    combined_tokens = _recombine_tokens(tokens)
    logger.info("Multi-item tokens after recombine: %s", [(t.original, t.token_type) for t in combined_tokens])

    # --- Step 5: Filter to only item tokens ---
    item_tokens = [t for t in combined_tokens if t.token_type == "item"]
    if len(item_tokens) < 2:
        return None

    # --- Step 6: Parse each item token using generic parser ---
    parsed_items: list = []
    for token in item_tokens:
        # Use the generic parser with detected item type and resolved name
        parsed_item = _parse_item_generic(
            text=token.original,
            item_type=token.item_type,
            item_name=token.resolved_name,
        )

        if parsed_item:
            # Apply quantity from token if detected
            if token.quantity and token.quantity > 1:
                parsed_item.quantity = token.quantity
            parsed_items.append(parsed_item)
            logger.debug("Multi-item: parsed '%s' -> %s", token.original[:40], parsed_item.item_type)
        else:
            # Fallback: try full deterministic parser
            full_result = parse_open_input_deterministic(token.original)
            if full_result and full_result.parsed_items:
                for item in full_result.parsed_items:
                    parsed_items.append(item)
                logger.debug("Multi-item: fallback parsed '%s'", token.original[:40])

    # --- Step 7: Return if 2+ items found ---
    if len(parsed_items) >= 2:
        logger.info("Multi-item order parsed: %d items", len(parsed_items))
        return OpenInputResponse(parsed_items=parsed_items)

    return None


# =============================================================================
# Main Deterministic Parser
# =============================================================================

def parse_open_input_deterministic(
    user_input: str,
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Spread options are loaded from the database cache (GlobalAttributeOption for "spread").

    Args:
        user_input: The user's input string
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
        ingredient_to_items: Mapping of ingredient names to menu items containing them
            (e.g., {"chicken": [{"name": "Chicken Salad Sandwich", ...}]})

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.
    """
    text = user_input.strip()

    # Expand abbreviations before any parsing (e.g., "cc" -> "cream cheese")
    # This must happen first so downstream parsers see canonical forms
    text = menu_cache.expand_abbreviations(text)

    # Check for greetings (patterns loaded from database)
    if menu_cache.is_greeting(text):
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

    # Check for done ordering (patterns loaded from database)
    if menu_cache.is_done(text):
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

    # Check for add-modifier patterns ("add bacon", "extra cheese", "more cheese")
    # This MUST run BEFORE _parse_more_menu_items() because "more cheese" would otherwise
    # be caught by the "^more\b" pattern in MORE_MENU_ITEMS_PATTERNS
    add_modifier_result = _parse_add_modifier_to_item(text)
    if add_modifier_result:
        return add_modifier_result

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
    modifier_inquiry_result = _parse_modifier_inquiry(text, modifier_category_keywords, modifier_item_keywords)
    if modifier_inquiry_result:
        return modifier_inquiry_result

    # Check for ingredient-based menu search
    # When user says "chicken" or "something with bacon", show matching items
    ingredient_search_result = _parse_ingredient_search(text, ingredient_to_items)
    if ingredient_search_result:
        return ingredient_search_result

    # Check for by-the-pound orders EARLY
    # Must be checked BEFORE spread/salad sandwich matching to prevent
    # "half a pound of whitefish salad" from matching "Whitefish Salad Sandwich"
    by_pound_result = _parse_by_pound_order(text)
    if by_pound_result:
        return by_pound_result

    # Check for signature items
    signature_item_result = _parse_signature_item_deterministic(text)
    if signature_item_result:
        return signature_item_result

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

    # Check for "just one" / "only one" patterns - reduces quantity to 1
    # e.g., "actually just one bagel", "only one", "just one"
    reduce_to_one_match = REDUCE_TO_ONE_PATTERN.match(text)
    if reduce_to_one_match:
        # Extract item type if specified (any of the capture groups)
        item_type = None
        all_item_type_slugs = menu_cache.get_configurable_item_types()
        for i in range(1, 6):  # Check all capture groups
            if reduce_to_one_match.group(i):
                item_type = reduce_to_one_match.group(i).lower()
                # Normalize plurals using data-driven approach:
                # Check if the word matches an item type, if not try without 's'
                if item_type not in all_item_type_slugs and item_type.endswith('s'):
                    singular = item_type[:-1]
                    if singular in all_item_type_slugs:
                        item_type = singular
                break

        # Return special cancel_item value to signal quantity reduction
        if item_type:
            cancel_value = f"__reduce_to_one_{item_type}__"
        else:
            cancel_value = "__reduce_to_one__"

        logger.info("Deterministic parse: 'just/only one' detected, reducing to 1 (item_type=%s)", item_type or "any")
        return OpenInputResponse(cancel_item=cancel_value)

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
    modify_existing_result = _parse_modify_existing_item(text)
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

            parsed_replacement = parse_open_input_deterministic(replacement_item)
            if parsed_replacement:
                parsed_replacement.replace_last_item = True
                return parsed_replacement

            return OpenInputResponse(replace_last_item=True)

    # Check for cancellation phrases
    cancel_match = CANCEL_ITEM_PATTERN.match(text)
    if cancel_match:
        cancel_item = None
        for i in range(1, 11):  # 10 capture groups in pattern
            if cancel_match.group(i):
                cancel_item = cancel_match.group(i)
                break
        if cancel_item:
            cancel_item = cancel_item.strip()
            # Handle "all" / "everything" to clear entire order
            all_items_phrases = {
                "all", "everything", "all of it", "the order", "my order",
                "the whole order", "my whole order", "all items", "all the items",
                "the whole thing", "it all", "them all",
                # Without "the" prefix (pattern strips "the")
                "order", "whole order", "whole thing"
            }
            if cancel_item.lower() in all_items_phrases:
                logger.info("Deterministic parse: cancel ALL items detected (phrase='%s')", cancel_item)
                return OpenInputResponse(cancel_item="__all_items__")
            # Handle pronouns that refer to the last item
            last_item_pronouns = {
                "that", "it", "this", "last", "the last one", "the last item", "last one", "last item",
                # "remove from the order" -> remove the last item mentioned
                "from the order", "from my order"
            }
            if cancel_item.lower() in last_item_pronouns:
                logger.info("Deterministic parse: cancellation of last item detected (pronoun='%s')", cancel_item)
                return OpenInputResponse(cancel_item="__last_item__")
            logger.info("Deterministic parse: cancellation detected, item='%s'", cancel_item)
            return OpenInputResponse(cancel_item=cancel_item)

    # Check for "add more" requests (add a third, add another, etc.)
    add_more_result = _parse_add_more_request(text)
    if add_more_result:
        return add_more_result

    # Check for split-quantity bagels FIRST (e.g., "two bagels one with lox one with cream cheese")
    # This MUST run BEFORE configurable_item to handle multi-bagel orders with different configs
    split_qty_result = _parse_split_quantity_bagels(text)
    if split_qty_result:
        return split_qty_result

    # Check for split-quantity drinks (e.g., "two coffees one with milk one black")
    # This MUST run BEFORE configurable_item to handle multi-drink orders with different configs
    split_qty_drinks_result = _parse_split_quantity_drinks(text)
    if split_qty_drinks_result:
        logger.info(
            "DETERMINISTIC SPLIT-QTY DRINKS: matched '%s' -> %d drinks",
            text[:50], len(split_qty_drinks_result.coffee_details)
        )
        return split_qty_drinks_result

    # Check for configurable items (bagels, coffee, etc.) using data-driven patterns
    # This MUST run BEFORE multi-item parsing to prevent "with bacon and egg" from being
    # interpreted as multiple items. Also prevents "bacon" from matching as a side item.
    # Replaces _parse_bagel_with_modifiers and _parse_coffee_deterministic.
    configurable_item_result = _parse_configurable_item(text)
    if configurable_item_result:
        return configurable_item_result

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
            bagel_choice = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
            modifications = _extract_menu_item_modifications(text)
            logger.info("EARLY MENU ITEM: matched '%s' -> %s (qty=%d, toasted=%s, bagel=%s, mods=%s)", text[:50], menu_item, qty, toasted, bagel_choice, modifications)
            # Phase 4: Only use parsed_items (deprecated fields removed)
            early_parsed_items = [_build_menu_item_parsed_item(item_name=menu_item, quantity=1, bread=bagel_choice, toasted=toasted, modifiers=modifications) for _ in range(qty)]
            return OpenInputResponse(parsed_items=early_parsed_items)

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
            # Phase 4: Only use parsed_items (deprecated fields removed)
            standalone_side_parsed_items = [_build_side_parsed_item(side_name=canonical_name, quantity=1) for _ in range(qty)]
            return OpenInputResponse(parsed_items=standalone_side_parsed_items)

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
                # Phase 4: Only use parsed_items (deprecated fields removed)
                dessert_parsed_items = [_build_menu_item_parsed_item(item_name=full_item, quantity=1) for _ in range(qty)]
                return OpenInputResponse(parsed_items=dessert_parsed_items)

    # Check for known menu items FIRST - BEFORE any bagel patterns
    # This ensures specific items like "whitefish salad on everything bagel" are recognized
    # as menu items rather than just "everything bagel"
    menu_item, qty = _extract_menu_item_from_text(text)
    if menu_item:
        # Skip if this is a coffee type - let coffee parser handle it instead
        # This ensures espresso, latte, etc. are processed as coffee items with proper config
        coffee_types = get_coffee_types()
        if menu_item.lower() not in coffee_types:
            toasted = _extract_toasted(text)
            bagel_choice = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
            modifications = _extract_menu_item_modifications(text)
            logger.info("DETERMINISTIC MENU ITEM (early): matched '%s' -> %s (qty=%d, toasted=%s, bagel=%s, mods=%s)", text[:50], menu_item, qty, toasted, bagel_choice, modifications)
            # Phase 4: Only use parsed_items (deprecated fields removed)
            menu_item_parsed_items = [_build_menu_item_parsed_item(item_name=menu_item, quantity=1, bread=bagel_choice, toasted=toasted, modifiers=modifications) for _ in range(qty)]
            return OpenInputResponse(parsed_items=menu_item_parsed_items)
        else:
            logger.debug("DETERMINISTIC MENU ITEM (early): skipping '%s' - is a coffee type, letting coffee parser handle it", menu_item)

    # Check for bagel order with quantity
    quantity_match = BAGEL_QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity_str = quantity_match.group(1)
        quantity = _extract_quantity(quantity_str)

        if quantity:
            bagel_type = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
            toasted = _extract_toasted(text)
            scooped = _extract_scooped(text)
            spread = _extract_spread(text)
            side_item, side_qty = _extract_side_item(text)

            logger.debug(
                "Deterministic parse: bagel order - qty=%d, type=%s, toasted=%s, scooped=%s, spread=%s, side=%s",
                quantity, bagel_type, toasted, scooped, spread, side_item
            )

            # Build parsed_items for unified handler
            bagel_qty_parsed_items = [
                _build_bagel_parsed_item(bread=bagel_type, toasted=toasted, scooped=scooped, spread=spread)
                for _ in range(quantity)
            ]
            if side_item:
                bagel_qty_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

            # Phase 4: Only use parsed_items (deprecated fields removed)
            return OpenInputResponse(parsed_items=bagel_qty_parsed_items)

    # Check for simple "a bagel" / "bagel please"
    if SIMPLE_BAGEL_PATTERN.search(text):
        bagel_type = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
        toasted = _extract_toasted(text)
        scooped = _extract_scooped(text)
        spread = _extract_spread(text)
        side_item, side_qty = _extract_side_item(text)

        logger.debug(
            "Deterministic parse: single bagel - type=%s, toasted=%s, scooped=%s, spread=%s, side=%s",
            bagel_type, toasted, scooped, spread, side_item
        )

        # Build parsed_items for unified handler
        simple_bagel_parsed_items = [_build_bagel_parsed_item(bread=bagel_type, toasted=toasted, scooped=scooped, spread=spread)]
        if side_item:
            simple_bagel_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

        # Phase 4: Only use parsed_items (deprecated fields removed)
        return OpenInputResponse(parsed_items=simple_bagel_parsed_items)

    # Check if text contains "bagel" anywhere (but only if no menu item was matched earlier)
    if re.search(r"\bbagels?\b", text, re.IGNORECASE):
        bagel_type = _slug_to_display(_extract_attribute_value(text, "bagel", "bread"))
        toasted = _extract_toasted(text)
        scooped = _extract_scooped(text)
        spread = _extract_spread(text)
        side_item, side_qty = _extract_side_item(text)

        if bagel_type or toasted is not None or scooped is not None or spread or side_item:
            logger.debug(
                "Deterministic parse: bagel mention - type=%s, toasted=%s, scooped=%s, spread=%s, side=%s",
                bagel_type, toasted, scooped, spread, side_item
            )
            # Build parsed_items for unified handler
            bagel_mention_parsed_items = [_build_bagel_parsed_item(bread=bagel_type, toasted=toasted, scooped=scooped, spread=spread)]
            if side_item:
                bagel_mention_parsed_items.extend([_build_side_parsed_item(side_name=side_item, quantity=1) for _ in range(side_qty)])

            # Phase 4: Only use parsed_items (deprecated fields removed)
            return OpenInputResponse(parsed_items=bagel_mention_parsed_items)

    # Check for soda/bottled drink order (more specific names like "Snapple Iced Tea")
    # Note: Sized beverages (coffee, tea, lattes) are handled by _parse_configurable_item
    soda_result = _parse_soda_deterministic(text)
    if soda_result:
        logger.info("DETERMINISTIC SODA: matched '%s'", text[:50])
        return soda_result

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None
