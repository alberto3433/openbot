"""
Deterministic Parsing Functions (no LLM).

This module contains all regex/string-based parsing functions that don't
require LLM calls. These are used for fast, consistent parsing of common
input patterns like greetings, simple bagel orders, coffee orders, etc.
"""

import re
import logging
from typing import TYPE_CHECKING

from ..schemas import (
    OpenInputResponse,
    ExtractedModifiers,
    ExtractedCoffeeModifiers,
    CoffeeOrderDetails,
)
from .constants import (
    WORD_TO_NUM,
    BAGEL_TYPES,
    SPREADS,
    SPREAD_TYPES,
    SPEED_MENU_BAGELS,
    BAGEL_PROTEINS,
    BAGEL_CHEESES,
    BAGEL_TOPPINGS,
    BAGEL_SPREADS,
    MODIFIER_NORMALIZATIONS,
    QUALIFIER_PATTERNS,
    GREETING_PATTERNS,
    DONE_PATTERNS,
    REPEAT_ORDER_PATTERNS,
    SIDE_ITEM_MAP,
    SIDE_ITEM_TYPES,
    KNOWN_MENU_ITEMS,
    NO_THE_PREFIX_ITEMS,
    MENU_ITEM_CANONICAL_NAMES,
    COFFEE_TYPO_MAP,
    COFFEE_BEVERAGE_TYPES,
    SODA_DRINK_TYPES,
    PRICE_INQUIRY_PATTERNS,
    MENU_CATEGORY_KEYWORDS,
    STORE_HOURS_PATTERNS,
    STORE_LOCATION_PATTERNS,
    DELIVERY_ZONE_PATTERNS,
    NYC_NEIGHBORHOOD_ZIPS,
    RECOMMENDATION_PATTERNS,
    ITEM_DESCRIPTION_PATTERNS,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Compiled Regex Patterns (internal use)
# =============================================================================

# Replace item patterns: "make it a X instead", "change it to X", "actually X instead", etc.
REPLACE_ITEM_PATTERN = re.compile(
    r"^(?:"
    # "make it X", "make it a X" - requires "make it"
    r"make\s+it\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "change it to X", "change to X" - requires "change"
    r"change\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "switch to X", "switch it to X" - requires "switch"
    r"switch\s+(?:it\s+)?(?:to\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "swap for X", "swap it for X" - requires "swap"
    r"swap\s+(?:it\s+)?(?:for\s+)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "actually X", "no X", "nope X", "wait X" - requires one of these words
    r"(?:actually|nope|wait)[,]?\s+(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "no X" but NOT "no more X" (which is cancellation)
    r"no[,]?\s+(?!more\s)(?:make\s+(?:it\s+)?)?(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "i meant X" - requires "i meant"
    r"i\s+meant\s+(?:a\s+)?(.+?)(?:\s+instead)?[\s!.,]*$"
    r"|"
    # "X instead" - requires "instead" at end
    r"(?:a\s+)?(.+?)\s+instead[\s!.,]*$"
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

# Bagel quantity pattern
BAGEL_QUANTITY_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple(?:\s+of)?)\s+"
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

# Coffee order pattern
COFFEE_ORDER_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(?:an?\s+)?"
    r"(?:(\d+|two|three|four|five)\s+)?"
    r"(?:(small|medium|large)\s+)?"
    r"(?:(iced|hot)\s+)?"
    r"(" + "|".join(COFFEE_BEVERAGE_TYPES) + r")"
    r"(?:\s|$|[.,!?])",
    re.IGNORECASE
)


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
    for bagel_type in sorted(BAGEL_TYPES, key=len, reverse=True):
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
                        normalized = MODIFIER_NORMALIZATIONS.get(modifier, modifier)
                        if normalized not in target_list:
                            target_list.append(normalized)
                            logger.debug(f"Extracted {category}: '{modifier}' -> '{normalized}'")

                start = pos + 1

    # Extract in order of specificity
    find_and_add(BAGEL_SPREADS, result.spreads, "spread")
    find_and_add(BAGEL_PROTEINS, result.proteins, "protein")
    find_and_add(BAGEL_CHEESES, result.cheeses, "cheese")
    find_and_add(BAGEL_TOPPINGS, result.toppings, "topping")

    # Special case: if user just says "cheese" without a specific type, default to american
    if "cheese" in input_lower and not result.cheeses:
        cheese_match = re.search(r'\bcheese\b', input_lower)
        if cheese_match:
            pos = cheese_match.start()
            if "cream cheese" not in input_lower[max(0, pos-6):pos+7]:
                result.cheeses.append("american")
                logger.debug("Extracted cheese: 'cheese' -> 'american' (default)")

    # Extract notes (filter to only bagel-related notes)
    notes_list = extract_notes_from_input(user_input)
    bagel_keywords = {
        'cream cheese', 'butter', 'cream', 'lox', 'spread',
        'bacon', 'ham', 'turkey', 'egg', 'sausage', 'meat',
        'cheese', 'american', 'cheddar', 'swiss', 'muenster',
        'tomato', 'onion', 'lettuce', 'cucumber', 'capers', 'avocado',
    }
    bagel_notes = [n for n in notes_list if any(kw in n.lower() for kw in bagel_keywords)]
    result.notes = bagel_notes

    return result


def extract_coffee_modifiers_from_input(user_input: str) -> ExtractedCoffeeModifiers:
    """
    Extract coffee modifiers from user input using keyword matching.

    Args:
        user_input: The raw user input string

    Returns:
        ExtractedCoffeeModifiers with sweetener and flavor_syrup if found
    """
    result = ExtractedCoffeeModifiers()
    input_lower = user_input.lower()

    sweeteners = ["splenda", "sugar", "stevia", "equal", "sweet n low", "sweet'n low", "honey"]
    syrups = ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice", "cinnamon", "lavender", "almond"]

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

    # Extract flavor syrup
    for syrup in syrups:
        if re.search(rf'\b{syrup}\b', input_lower):
            result.flavor_syrup = syrup
            logger.debug(f"Extracted coffee flavor syrup: {syrup}")
            break

    result.notes = extract_notes_from_input(user_input)

    return result


def extract_notes_from_input(user_input: str) -> list[str]:
    """
    Extract special instruction notes from user input.

    Args:
        user_input: The raw user input string

    Returns:
        List of note strings like ["light cream cheese", "extra bacon"]
    """
    notes = []
    input_lower = user_input.lower()

    for pattern, qualifier in QUALIFIER_PATTERNS:
        for match in re.finditer(pattern, input_lower, re.IGNORECASE):
            item = match.group(1).strip()
            skip_words = {'the', 'a', 'an', 'and', 'or', 'on', 'with', 'please', 'thanks'}
            if item.lower() in skip_words:
                continue
            if qualifier == 'no':
                note = f"no {item}"
            else:
                note = f"{qualifier} {item}"
            if note not in notes:
                notes.append(note)
                logger.debug(f"Extracted note: '{note}' from input")

    return notes


# =============================================================================
# Helper Extraction Functions
# =============================================================================

def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of'."""
    text = text.lower().strip()
    text = re.sub(r"\s+of$", "", text)

    if text.isdigit():
        return int(text)

    return WORD_TO_NUM.get(text)


def _extract_bagel_type(text: str) -> str | None:
    """Extract bagel type from text."""
    text_lower = text.lower()

    for bagel_type in sorted(BAGEL_TYPES, key=len, reverse=True):
        if bagel_type in text_lower:
            return bagel_type

    return None


def _extract_toasted(text: str) -> bool | None:
    """Extract toasted preference from text."""
    text_lower = text.lower()

    if re.search(r"\bnot\s+toasted\b", text_lower):
        return False
    if re.search(r"\btoasted\b", text_lower):
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
    """Extract spread and spread type from text. Returns (spread, spread_type)."""
    text_lower = text.lower()

    spread = None
    spread_type = None

    for s in sorted(SPREADS, key=len, reverse=True):
        if s in text_lower:
            spread = s
            break

    all_spread_types = SPREAD_TYPES.copy()
    if extra_spread_types:
        all_spread_types.update(extra_spread_types)

    for st in sorted(all_spread_types, key=len, reverse=True):
        if st in text_lower:
            spread_type = st
            break

    if spread_type and not spread:
        spread = "cream cheese"

    return spread, spread_type


def _extract_side_item(text: str) -> tuple[str | None, int]:
    """Extract side item from text. Returns (side_item_name, quantity)."""
    text_lower = text.lower()

    side_match = re.search(r'\bside\s+of\s+(\w+(?:\s+\w+){0,2})', text_lower)
    if not side_match:
        return None, 1

    side_text = side_match.group(1).strip()

    for keyword in sorted(SIDE_ITEM_MAP.keys(), key=len, reverse=True):
        if side_text == keyword or side_text.startswith(keyword + " ") or side_text.startswith(keyword):
            return SIDE_ITEM_MAP[keyword], 1

    return f"Side of {side_text.title()}", 1


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

    for item in sorted(KNOWN_MENU_ITEMS, key=len, reverse=True):
        if item in text_lower or text_lower.startswith(item):
            if item in MENU_ITEM_CANONICAL_NAMES:
                canonical = MENU_ITEM_CANONICAL_NAMES[item]
            elif item in NO_THE_PREFIX_ITEMS:
                canonical = " ".join(word.capitalize() for word in item.split())
            else:
                canonical = " ".join(word.capitalize() for word in item.split())
                if not canonical.startswith("The "):
                    canonical = "The " + canonical
            return canonical, quantity

    return None, 0


# =============================================================================
# Speed Menu Bagel Parsing
# =============================================================================

def _parse_speed_menu_bagel_deterministic(text: str) -> OpenInputResponse | None:
    """Parse speed menu bagel orders like 'The Classic BEC on a wheat bagel'."""
    text_lower = text.lower()

    matched_item = None
    matched_key = None

    for key in sorted(SPEED_MENU_BAGELS.keys(), key=len, reverse=True):
        if key in text_lower:
            matched_item = SPEED_MENU_BAGELS[key]
            matched_key = key
            break

    if not matched_item:
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
    bagel_choice = None
    bagel_choice_pattern = re.compile(
        r"(?:on|with)\s+(?:(?:a|an)\s+)?(\w+(?:\s+\w+)?)\s+bagels?",
        re.IGNORECASE
    )
    bagel_match = bagel_choice_pattern.search(text)
    if bagel_match:
        potential_type = bagel_match.group(1).lower().strip()
        if potential_type in BAGEL_TYPES:
            bagel_choice = potential_type
        else:
            for bagel_type in BAGEL_TYPES:
                if potential_type == bagel_type or bagel_type.startswith(potential_type):
                    bagel_choice = bagel_type
                    break

    if not bagel_choice:
        for bagel_type in sorted(BAGEL_TYPES, key=len, reverse=True):
            pattern = re.compile(
                r"(?:on|with)\s+(?:(?:a|an)\s+)?" + re.escape(bagel_type) + r"(?:\s|$|[,.])",
                re.IGNORECASE
            )
            if pattern.search(text_lower):
                bagel_choice = bagel_type
                break

    logger.info(
        "SPEED MENU PARSED: item=%s, qty=%d, toasted=%s, bagel_choice=%s",
        matched_item, quantity, toasted, bagel_choice
    )

    return OpenInputResponse(
        new_speed_menu_bagel=True,
        new_speed_menu_bagel_name=matched_item,
        new_speed_menu_bagel_quantity=quantity,
        new_speed_menu_bagel_toasted=toasted,
        new_speed_menu_bagel_bagel_choice=bagel_choice,
    )


# =============================================================================
# Coffee/Soda Parsing
# =============================================================================

def _parse_coffee_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse coffee/beverage orders deterministically."""
    text_lower = text.lower()

    coffee_type = None
    for bev in COFFEE_BEVERAGE_TYPES:
        if re.search(rf'\b{bev}s?\b', text_lower):
            coffee_type = bev
            break

    if not coffee_type:
        for typo, correct in COFFEE_TYPO_MAP.items():
            if re.search(rf'\b{typo}\b', text_lower):
                coffee_type = correct
                logger.debug("Deterministic parse: corrected typo '%s' -> '%s'", typo, correct)
                break

    if not coffee_type:
        return None

    logger.debug("Deterministic parse: detected coffee type '%s'", coffee_type)

    # Extract quantity
    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+(?:' + '|'.join(COFFEE_BEVERAGE_TYPES) + r')', text_lower)
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

    notes_list = extract_notes_from_input(text)
    coffee_keywords = {'milk', 'cream', 'ice', 'hot', 'shot', 'espresso', 'foam', 'whip', 'sugar', 'syrup'}
    coffee_notes = [n for n in notes_list if any(kw in n.lower() for kw in coffee_keywords)]
    notes = ", ".join(coffee_notes) if coffee_notes else None

    logger.debug(
        "Deterministic parse: coffee order - type=%s, qty=%d, size=%s, iced=%s, milk=%s, sweetener=%s(%d), syrup=%s, notes=%s",
        coffee_type, quantity, size, iced, milk,
        coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup, notes
    )

    return OpenInputResponse(
        new_coffee=True,
        new_coffee_type=coffee_type,
        new_coffee_quantity=quantity,
        new_coffee_size=size,
        new_coffee_iced=iced,
        new_coffee_milk=milk,
        new_coffee_sweetener=coffee_mods.sweetener,
        new_coffee_sweetener_quantity=coffee_mods.sweetener_quantity,
        new_coffee_flavor_syrup=coffee_mods.flavor_syrup,
        new_coffee_notes=notes,
    )


def _parse_soda_deterministic(text: str) -> OpenInputResponse | None:
    """Try to parse soda/bottled drink orders deterministically."""
    text_lower = text.lower()

    drink_type = None
    for soda in sorted(SODA_DRINK_TYPES, key=len, reverse=True):
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

    logger.debug("Deterministic parse: detected soda type '%s'", drink_type)

    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    logger.debug("Deterministic parse: soda order - type=%s, qty=%d", drink_type, quantity)

    return OpenInputResponse(
        new_coffee=True,
        new_coffee_type=drink_type,
        new_coffee_quantity=quantity,
        new_coffee_size=None,
        new_coffee_iced=None,
        new_coffee_milk=None,
        new_coffee_sweetener=None,
        new_coffee_sweetener_quantity=1,
        new_coffee_flavor_syrup=None,
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


# =============================================================================
# Multi-Item Order Parsing
# =============================================================================

def _parse_multi_item_order(user_input: str) -> OpenInputResponse | None:
    """Parse multi-item orders like 'The Lexington and an orange juice'."""
    text = user_input.strip()
    text_lower = text.lower()

    compound_phrases = [
        ("ham and cheese", "HAM_CHEESE_PLACEHOLDER"),
        ("ham and egg", "HAM_EGG_PLACEHOLDER"),
        ("bacon and egg", "BACON_EGG_PLACEHOLDER"),
        ("lox and cream cheese", "LOX_CC_PLACEHOLDER"),
        ("cream cheese and lox", "CC_LOX_PLACEHOLDER"),
        ("salt and pepper", "SALT_PEPPER_PLACEHOLDER"),
        ("eggs and bacon", "EGGS_BACON_PLACEHOLDER"),
        ("black and white", "BLACK_WHITE_PLACEHOLDER"),
        ("spinach and feta", "SPINACH_FETA_PLACEHOLDER"),
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

    menu_item = None
    menu_item_qty = 1
    menu_item_bagel_choice = None
    menu_item_toasted = None
    coffee_list: list[CoffeeOrderDetails] = []
    bagel = False
    bagel_qty = 1
    bagel_type = None
    bagel_toasted = None
    bagel_spread = None
    bagel_spread_type = None
    side_item = None
    side_item_qty = 1

    for part in restored_parts:
        part = part.strip()
        if not part:
            continue

        item_name, item_qty = _extract_menu_item_from_text(part)
        if item_name:
            menu_item = item_name
            menu_item_qty = item_qty
            menu_item_bagel_choice = _extract_bagel_type(part)
            menu_item_toasted = _extract_toasted(part)
            logger.info("Multi-item: detected menu item '%s' (qty=%d, bagel=%s, toasted=%s)",
                        menu_item, menu_item_qty, menu_item_bagel_choice, menu_item_toasted)
            continue

        parsed = parse_open_input_deterministic(part)
        if not parsed:
            logger.debug("Multi-item: could not parse part '%s' deterministically", part)
            continue

        if parsed.new_menu_item:
            menu_item = parsed.new_menu_item
            menu_item_qty = parsed.new_menu_item_quantity or 1
            menu_item_bagel_choice = parsed.new_menu_item_bagel_choice
            menu_item_toasted = parsed.new_menu_item_toasted
            logger.info("Multi-item: detected menu item '%s' (qty=%d)", menu_item, menu_item_qty)

        if parsed.new_coffee:
            coffee_list.append(CoffeeOrderDetails(
                drink_type=parsed.new_coffee_type or "coffee",
                size=parsed.new_coffee_size,
                iced=parsed.new_coffee_iced,
                quantity=parsed.new_coffee_quantity or 1,
                milk=parsed.new_coffee_milk,
                notes=parsed.new_coffee_notes,
            ))
            logger.info("Multi-item: detected coffee '%s' (qty=%d, milk=%s, notes=%s)",
                        parsed.new_coffee_type, parsed.new_coffee_quantity or 1,
                        parsed.new_coffee_milk, parsed.new_coffee_notes)

        if parsed.new_bagel:
            bagel = True
            bagel_qty = parsed.new_bagel_quantity or 1
            bagel_type = parsed.new_bagel_type
            bagel_toasted = parsed.new_bagel_toasted
            bagel_spread = parsed.new_bagel_spread
            bagel_spread_type = parsed.new_bagel_spread_type
            logger.info("Multi-item: detected bagel (type=%s, qty=%d, toasted=%s)", bagel_type, bagel_qty, bagel_toasted)

        if parsed.new_side_item:
            side_item = parsed.new_side_item
            side_item_qty = parsed.new_side_item_quantity or 1
            logger.info("Multi-item: detected side item '%s' (qty=%d)", side_item, side_item_qty)

    items_found = sum([
        menu_item is not None,
        len(coffee_list) > 0,
        bagel,
        side_item is not None,
    ])
    total_items = items_found + max(0, len(coffee_list) - 1)

    if items_found >= 2 or total_items >= 2:
        first_coffee = coffee_list[0] if coffee_list else None
        logger.info("Multi-item order parsed: menu_item=%s, coffees=%d, bagel=%s, side=%s", menu_item, len(coffee_list), bagel, side_item)
        return OpenInputResponse(
            new_menu_item=menu_item,
            new_menu_item_quantity=menu_item_qty,
            new_menu_item_bagel_choice=menu_item_bagel_choice,
            new_menu_item_toasted=menu_item_toasted,
            new_coffee=first_coffee is not None,
            new_coffee_type=first_coffee.drink_type if first_coffee else None,
            new_coffee_quantity=first_coffee.quantity if first_coffee else 1,
            new_coffee_size=first_coffee.size if first_coffee else None,
            new_coffee_iced=first_coffee.iced if first_coffee else None,
            new_coffee_milk=first_coffee.milk if first_coffee else None,
            new_coffee_notes=first_coffee.notes if first_coffee else None,
            coffee_details=coffee_list,
            new_bagel=bagel,
            new_bagel_quantity=bagel_qty,
            new_bagel_type=bagel_type,
            new_bagel_toasted=bagel_toasted,
            new_bagel_spread=bagel_spread,
            new_bagel_spread_type=bagel_spread_type,
            new_side_item=side_item,
            new_side_item_quantity=side_item_qty,
        )

    if menu_item:
        return OpenInputResponse(
            new_menu_item=menu_item,
            new_menu_item_quantity=menu_item_qty,
            new_menu_item_bagel_choice=menu_item_bagel_choice,
            new_menu_item_toasted=menu_item_toasted,
        )
    if coffee_list:
        first_coffee = coffee_list[0]
        return OpenInputResponse(
            new_coffee=True,
            new_coffee_type=first_coffee.drink_type,
            new_coffee_quantity=first_coffee.quantity,
            new_coffee_size=first_coffee.size,
            new_coffee_iced=first_coffee.iced,
            new_coffee_milk=first_coffee.milk,
            new_coffee_notes=first_coffee.notes,
            coffee_details=coffee_list,
        )
    if bagel:
        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=bagel_qty,
            new_bagel_type=bagel_type,
            new_bagel_toasted=bagel_toasted,
            new_bagel_spread=bagel_spread,
            new_bagel_spread_type=bagel_spread_type,
        )
    if side_item:
        return OpenInputResponse(new_side_item=side_item, new_side_item_quantity=side_item_qty)

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

    # Check for done ordering
    if DONE_PATTERNS.match(text):
        logger.debug("Deterministic parse: done ordering detected")
        return OpenInputResponse(done_ordering=True)

    # Check for repeat order
    if REPEAT_ORDER_PATTERNS.match(text):
        logger.debug("Deterministic parse: repeat order detected")
        return OpenInputResponse(wants_repeat_order=True)

    # Check for price inquiries
    price_result = _parse_price_inquiry_deterministic(text)
    if price_result:
        return price_result

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

    # Check for speed menu bagels
    speed_menu_result = _parse_speed_menu_bagel_deterministic(text)
    if speed_menu_result:
        return speed_menu_result

    # Check for replacement phrases
    replace_match = REPLACE_ITEM_PATTERN.match(text)
    if replace_match:
        replacement_item = None
        for i in range(1, 9):
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
            logger.info("EARLY MENU ITEM: matched '%s' -> %s (qty=%d, toasted=%s)", text[:50], menu_item, qty, toasted)
            return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty, new_menu_item_toasted=toasted)

    # Early check for standalone side items
    standalone_side_items = {
        "bagel chips": "Bagel Chips",
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
            return OpenInputResponse(new_side_item=canonical_name, new_side_item_quantity=qty)

    # Check for bagel order with quantity
    quantity_match = BAGEL_QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity_str = quantity_match.group(1)
        quantity = _extract_quantity(quantity_str)

        if quantity:
            bagel_type = _extract_bagel_type(text)
            toasted = _extract_toasted(text)
            spread, spread_type = _extract_spread(text, spread_types)
            side_item, side_qty = _extract_side_item(text)

            logger.debug(
                "Deterministic parse: bagel order - qty=%d, type=%s, toasted=%s, spread=%s/%s, side=%s",
                quantity, bagel_type, toasted, spread, spread_type, side_item
            )

            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=quantity,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
            )

    # Check for simple "a bagel" / "bagel please"
    if SIMPLE_BAGEL_PATTERN.search(text):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        logger.debug(
            "Deterministic parse: single bagel - type=%s, toasted=%s, spread=%s/%s, side=%s",
            bagel_type, toasted, spread, spread_type, side_item
        )

        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=1,
            new_bagel_type=bagel_type,
            new_bagel_toasted=toasted,
            new_bagel_spread=spread,
            new_bagel_spread_type=spread_type,
            new_side_item=side_item,
            new_side_item_quantity=side_qty,
        )

    # Check if text contains "bagel" anywhere
    if re.search(r"\bbagels?\b", text, re.IGNORECASE):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        if bagel_type or toasted is not None or spread or side_item:
            logger.debug(
                "Deterministic parse: bagel mention - type=%s, toasted=%s, spread=%s/%s, side=%s",
                bagel_type, toasted, spread, spread_type, side_item
            )
            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=1,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
            )

    # Check for coffee/beverage order
    coffee_result = _parse_coffee_deterministic(text)
    if coffee_result:
        logger.info("DETERMINISTIC COFFEE: matched '%s' -> type=%s", text[:50], coffee_result.new_coffee_type)
        return coffee_result

    # Check for soda/bottled drink order
    soda_result = _parse_soda_deterministic(text)
    if soda_result:
        return soda_result

    # Check for known menu items
    menu_item, qty = _extract_menu_item_from_text(text)
    if menu_item:
        toasted = _extract_toasted(text)
        logger.info("DETERMINISTIC MENU ITEM: matched '%s' -> %s (qty=%d, toasted=%s)", text[:50], menu_item, qty, toasted)
        return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty, new_menu_item_toasted=toasted)

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None
