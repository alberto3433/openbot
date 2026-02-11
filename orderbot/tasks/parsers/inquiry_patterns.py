"""
Inquiry Patterns.

Regex patterns for detecting various types of customer inquiries:
- Price inquiries
- Store hours/location
- Delivery zones
- Recommendations
- Item descriptions
- Modifier options
- Off-topic requests during configuration
- "Show more" menu requests
"""

import re


# =============================================================================
# Price Inquiry Patterns
# =============================================================================

PRICE_INQUIRY_PATTERNS = [
    # "how much are/is X"
    re.compile(r"how\s+much\s+(?:are|is|does?|do)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\s+cost)?(?:\?|$)", re.IGNORECASE),
    # "what's the price of X" / "what is the price of X"
    re.compile(r"what(?:'?s|\s+is)\s+the\s+price\s+(?:of|for)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what do X cost"
    re.compile(r"what\s+do(?:es)?\s+(?:the\s+)?(?:a\s+)?(.+?)\s+cost(?:\?|$)", re.IGNORECASE),
    # "cost of X"
    re.compile(r"(?:the\s+)?cost\s+of\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "price of X"
    re.compile(r"(?:the\s+)?price\s+(?:of|for)\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "how much for X"
    re.compile(r"how\s+much\s+for\s+(?:the\s+)?(?:a\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Store Info Inquiry Patterns
# =============================================================================

STORE_HOURS_PATTERNS = [
    re.compile(r"what\s+(?:are|is)\s+(?:your|the)\s+(?:store\s+)?hours", re.IGNORECASE),
    re.compile(r"when\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:are\s+you|you)\s+open\s+(?:today|now|on)", re.IGNORECASE),
    re.compile(r"what\s+time\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:hours|opening\s+hours|business\s+hours|store\s+hours)", re.IGNORECASE),
    re.compile(r"how\s+late\s+(?:are\s+you|do\s+you\s+stay)\s+open", re.IGNORECASE),
]

STORE_LOCATION_PATTERNS = [
    re.compile(r"where\s+(?:are\s+you|is\s+the\s+store)\s+located", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your|the)\s+address", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:address|location)", re.IGNORECASE),
    re.compile(r"where\s+(?:are\s+you|is\s+(?:this|the\s+store))", re.IGNORECASE),
    re.compile(r"how\s+do\s+i\s+(?:get|find)\s+(?:you|there|the\s+store)", re.IGNORECASE),
    re.compile(r"what\s+(?:are|is)\s+(?:your|the)\s+(?:store\s+)?locations?", re.IGNORECASE),
]

# Delivery zone inquiry patterns - capture the location they're asking about
DELIVERY_ZONE_PATTERNS = [
    # "do you deliver to X" / "can you deliver to X"
    re.compile(r"(?:do|can|will)\s+you\s+deliver\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "is X in your delivery area/zone"
    re.compile(r"is\s+(.+?)\s+in\s+(?:your|the)\s+delivery\s+(?:area|zone|range)", re.IGNORECASE),
    # "can I get delivery to X"
    re.compile(r"can\s+i\s+get\s+delivery\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "do you deliver in X"
    re.compile(r"(?:do|can)\s+you\s+deliver\s+in\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "delivery to X" / "deliver to X"
    re.compile(r"deliver(?:y)?\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Recommendation Inquiry Patterns
# =============================================================================

# General recommendation patterns (no term extraction) - domain-agnostic
# These return "general" as the recommendation type
RECOMMENDATION_GENERAL_PATTERNS = [
    re.compile(r"what\s+(?:do\s+you|would\s+you|should\s+i|can\s+you)\s+recommend\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular|the\s+best)(?:\s+here)?\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:most\s+)?popular\??$", re.IGNORECASE),
    re.compile(r"what\s+(?:are\s+)?(?:your\s+)?(?:best|most\s+popular)\s+(?:sellers?|items?)", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?most\s+popular\s+item", re.IGNORECASE),
    re.compile(r"(?:any|have\s+any|got\s+any|do\s+you\s+have\s+any)\s+recommendations?\??", re.IGNORECASE),
    re.compile(r"(?:suggest|recommend)\s+(?:something|anything)", re.IGNORECASE),
    re.compile(r"what\s+sells\s+best", re.IGNORECASE),
    re.compile(r"what\s+(?:should\s+i|do\s+i)\s+(?:get|try|order)(?:\s+here)?\??$", re.IGNORECASE),
    re.compile(r"what\s+(?:do\s+you|would\s+you|can\s+you)\s+suggest\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+your\s+favorite\??$", re.IGNORECASE),
    # Meal-based recommendations (breakfast/lunch) - treat as general
    re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular)\s+for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
    re.compile(r"recommend\s+(?:something\s+)?for\s+(?:breakfast|lunch|dinner|brunch)", re.IGNORECASE),
    # Specials inquiry - "do you have any specials today?", "any specials?"
    re.compile(r"(?:do\s+you\s+have\s+)?(?:any\s+)?specials?\s*(?:today|right\s+now)?\??$", re.IGNORECASE),
]

# Term-extracting recommendation patterns - data-driven item/type lookup
# These patterns capture a search term (e.g., "bagels", "coffee", "teas")
# The term is singularized and used for menu_items -> item_type fallback search
RECOMMENDATION_TERM_PATTERNS = [
    # "what {TERM} do you recommend" - captures term before verb phrase
    re.compile(r"what\s+(?:kind\s+of\s+)?(.+?)\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE),
    # "what's your best/popular {TERM}" - captures term after adjective
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "which {TERM} is/are best/popular/good" - captures term after "which"
    re.compile(r"which\s+(.+?)\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE),
    # "recommend a {TERM}" - captures term after "recommend a/some"
    re.compile(r"recommend\s+(?:a\s+|some\s+)?(.+?)(?:\?|$)", re.IGNORECASE),
    # "best/popular/favorite {TERM}" - captures term after adjective
    re.compile(r"(?:best|popular|favorite)\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "what's popular for {TERM}" - captures term after "for"
    re.compile(r"what(?:'?s|\s+is)\s+popular\s+for\s+(.+?)(?:\?|$)", re.IGNORECASE),
    # "what {TERM} is popular/good/best" - captures term between what and is
    re.compile(r"what\s+(.+?)\s+is\s+(?:popular|good|best)", re.IGNORECASE),
]

# =============================================================================
# Item Description Inquiry Patterns
# =============================================================================

# Pattern to extract item name from "what's on/in the X?" questions
ITEM_DESCRIPTION_PATTERNS = [
    # "what's on the health nut?" "what's in the BLT?"
    re.compile(r"what(?:'s|s| is) (?:on|in) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what comes on the health nut?"
    re.compile(r"what comes (?:on|in|with) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "what does the health nut have on it?"
    re.compile(r"what does (?:the |a )?(.+?) (?:have|come with)", re.IGNORECASE),
    # "tell me about the health nut"
    re.compile(r"tell me (?:about|what's in) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "describe the health nut"
    re.compile(r"describe (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
    # "ingredients in the health nut"
    re.compile(r"ingredients (?:in|of|for) (?:the |a )?(.+?)(?:\?|$)", re.IGNORECASE),
]

# =============================================================================
# Modifier/Add-on Inquiry Patterns
# =============================================================================

# Patterns for modifier inquiries - each returns (pattern, item_group_index, category_group_index)
# Group indices are 1-based, or 0 if not captured
MODIFIER_INQUIRY_PATTERNS = [
    # "what can I add to coffee?" / "what can I add to my coffee?"
    (re.compile(r"what (?:can|could) (?:i|you|we) (?:add|put|get) (?:to|on|in|for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what do you have for coffee?" / "what options for coffee?"
    (re.compile(r"what (?:do you have|options?|choices?) (?:for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what goes on a bagel?" / "what goes in coffee?"
    (re.compile(r"what (?:goes|can go) (?:on|in|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 1, 0),
    # "what kind of bagel toppings do you have?" / "what types of spreads do you have?"
    (re.compile(r"what (?:kind|kinds|type|types) of (\w+(?:\s+\w+)?) do you (?:have|offer|carry)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "what sweeteners do you have?" / "what milks do you have?"
    (re.compile(r"what (\w+(?:\s+\w+)?) do you (?:have|offer|carry)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "do you have sweeteners?" / "do you have flavored syrups?"
    (re.compile(r"do you (?:have|offer|carry) (?:any )?(\w+(?:\s+\w+)?)(?:\?|$)", re.IGNORECASE), 0, 1),
    # "what sweeteners for coffee?" / "what milks for lattes?"
    (re.compile(r"what (\w+(?:\s+\w+)?) (?:for|with) (?:a |my |the )?(.+?)(?:\?|$)", re.IGNORECASE), 2, 1),
    # "coffee options" / "bagel toppings"
    (re.compile(r"^(.+?) (options?|choices?|add-?ons?|extras?)(?:\?|$)", re.IGNORECASE), 1, 2),
]

# =============================================================================
# Off-Topic Request Patterns (during item configuration)
# =============================================================================

# Patterns to detect off-topic requests during configuration
# These are questions or requests that aren't answers to the current config question
OFF_TOPIC_PATTERNS = [
    # Menu inquiries: "what syrups do you have?" / "what sweeteners do you have?"
    re.compile(r"what (\w+(?:\s+\w+)?)\s+do\s+you\s+(?:have|offer|carry)", re.IGNORECASE),
    # "what options do you have?" / "what are my options?"
    re.compile(r"what (?:are (?:my|the) )?options", re.IGNORECASE),
    # "what can I add?" / "what can I get?"
    re.compile(r"what (?:can|could)\s+(?:i|you)\s+(?:add|get|put)", re.IGNORECASE),
    # "do you have vanilla?" / "do you have oat milk?"
    re.compile(r"do you (?:have|offer|carry)\s+(?:any\s+)?(\w+)", re.IGNORECASE),
    # "what flavors do you have?" / "what sizes are there?"
    re.compile(r"what (\w+)\s+(?:are there|do you offer)", re.IGNORECASE),
    # "can I get vanilla?" / "can I add sugar?"
    re.compile(r"can\s+(?:i|you)\s+(?:get|add|have)\s+\w+\?", re.IGNORECASE),
    # "what kinds of X do you have?"
    re.compile(r"what (?:kind|type|kinds|types)\s+of\s+\w+", re.IGNORECASE),
    # Modifier additions: "add vanilla syrup" / "add oat milk"
    re.compile(r"^add\s+\w+", re.IGNORECASE),
    # "with vanilla" / "with caramel syrup"
    re.compile(r"^with\s+\w+", re.IGNORECASE),
    # "put vanilla in it" / "put some sugar"
    re.compile(r"^put\s+\w+", re.IGNORECASE),
    # "I want vanilla" / "I'd like oat milk"
    re.compile(r"^i(?:'?d)?\s*(?:want|like|need)\s+(?:to\s+add\s+)?\w+", re.IGNORECASE),
    # "make it with vanilla" / "make it iced" (but not "make it small/large")
    re.compile(r"^make\s+it\s+(?:with\s+)?\w+", re.IGNORECASE),
]

# =============================================================================
# "Show More" Menu Items Patterns
# =============================================================================

# Patterns to detect when user wants to see more items from a previous menu query
MORE_MENU_ITEMS_PATTERNS = [
    # "what other pastries do you have?" / "what other options?"
    re.compile(r"what (?:other|else|more)\b", re.IGNORECASE),
    # "any other pastries?" / "any more options?"
    re.compile(r"any (?:other|more)\b", re.IGNORECASE),
    # "more pastries" / "more options" / "more please"
    re.compile(r"^more\b", re.IGNORECASE),
    # "show me more" / "tell me more"
    re.compile(r"(?:show|tell|give) (?:me )?more\b", re.IGNORECASE),
    # "what else?" / "anything else?" (when asking about menu, not ordering)
    re.compile(r"(?:what|anything) else\??\s*$", re.IGNORECASE),
    # "keep going" / "continue"
    re.compile(r"^(?:keep going|continue|go on)\s*\??$", re.IGNORECASE),
    # "and?" / "and what else?"
    re.compile(r"^and\s*\??\s*$", re.IGNORECASE),
]

# =============================================================================
# Attribute Inquiry Patterns
# =============================================================================

# Patterns for attribute option inquiries - asking about item type attributes
# Format: (pattern, item_group_index, signal_group_index)
# Group indices are 1-based, or 0 if not captured (standalone signal word)
ATTRIBUTE_INQUIRY_PATTERNS = [
    # "what bagel types do you have?" - item=bagel, signal=types
    (re.compile(r"what\s+(\w+)\s+(type|types|flavor|flavors|kind|kinds|option|options|variety|varieties|choice|choices)\s+do\s+you\s+have", re.IGNORECASE), 1, 2),
    # "what types of bagels do you have?" - item=bagels, signal=types
    (re.compile(r"what\s+(type|types|flavor|flavors|kind|kinds|option|options|variety|varieties|choice|choices)\s+of\s+(\w+)\s+do\s+you\s+have", re.IGNORECASE), 2, 1),
    # "what kinds of coffee?" - item=coffee, signal=kinds
    (re.compile(r"what\s+(type|types|flavor|flavors|kind|kinds|option|options|variety|varieties|choice|choices)\s+of\s+(\w+)\s*\??$", re.IGNORECASE), 2, 1),
    # "bagel types?" / "coffee sizes?" - item=bagel/coffee, signal=types/sizes
    (re.compile(r"^(\w+)\s+(type|types|flavor|flavors|size|sizes|kind|kinds|option|options|choice|choices)\s*\??$", re.IGNORECASE), 1, 2),
    # "what sizes do you have?" - item=None, signal=sizes (standalone)
    (re.compile(r"what\s+(size|sizes|temperature|temperatures)\s+do\s+you\s+have", re.IGNORECASE), 0, 1),
]


# =============================================================================
# Dietary & Allergen Inquiry Patterns
# =============================================================================

# Dietary property names (matching database column names)
DIETARY_PROPERTIES = {
    "vegan": "is_vegan",
    "vegetarian": "is_vegetarian",
    "gluten-free": "is_gluten_free",
    "gluten free": "is_gluten_free",
    "gf": "is_gluten_free",
    "dairy-free": "is_dairy_free",
    "dairy free": "is_dairy_free",
    "non-dairy": "is_dairy_free",
    "lactose-free": "is_dairy_free",
    "kosher": "is_kosher",
}

# Default allergen column names (fallback when cache is not loaded)
# These are schema knowledge (DB column names), not domain knowledge
_DEFAULT_ALLERGEN_COLUMNS = ["contains_eggs", "contains_fish", "contains_sesame", "contains_nuts"]


def _get_allergen_columns() -> list[str]:
    """Get allergen column names from cache, with fallback.

    Returns the list of allergen columns from the menu cache if available,
    otherwise falls back to the default list. This makes allergen patterns
    data-driven rather than hardcoded.

    Returns:
        List of allergen column names (e.g., ["contains_eggs", "contains_fish", ...]).
    """
    try:
        from orderbot.cache import menu_cache
        if menu_cache.is_loaded:
            columns = menu_cache.get_allergen_column_names()
            if columns:
                return columns
    except Exception:
        pass
    # Fallback for tests/startup when cache isn't loaded
    return _DEFAULT_ALLERGEN_COLUMNS


def _build_allergen_properties() -> dict[str, str]:
    """Build allergen keyword -> column mapping from column names."""
    props = {}
    for col in _get_allergen_columns():
        base = col.replace("contains_", "")
        props[base] = col
        # Add singular if plural (eggs->egg, nuts->nut), but not for "fish"
        if base.endswith("s") and base != "fish":
            props[base[:-1]] = col
    # Add common synonyms that map to existing columns
    props["seafood"] = "contains_fish"
    props["tree nuts"] = "contains_nuts"
    props["peanuts"] = "contains_nuts"
    return props


# Allergen property names (derived from database column names)
ALLERGEN_PROPERTIES = _build_allergen_properties()


def _build_allergen_regex_part() -> str:
    """Build regex alternation for allergen terms."""
    terms = list(ALLERGEN_PROPERTIES.keys())
    # Sort by length descending so longer terms match first (e.g., "tree nuts" before "nuts")
    return r"(" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")"


# Pre-built allergen regex alternation for use in patterns
_ALLERGEN_TERMS = _build_allergen_regex_part()

# Patterns for combined dietary + category queries ("what vegan drinks do you have?")
# These ask about dietary options filtered by a category
# Group 1: dietary term, Group 2: category term
DIETARY_CATEGORY_PATTERNS = [
    # "what vegan drinks do you have?"
    re.compile(r"what\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy)\s+(\w+(?:\s+\w+)?)\s+(?:do\s+you\s+have|are\s+there)", re.IGNORECASE),
    # "do you have vegan drinks?" / "do you have any gluten-free sandwiches?"
    re.compile(r"do\s+you\s+have\s+(?:any\s+)?(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy)\s+(\w+(?:\s+\w+)?)\s*\??$", re.IGNORECASE),
    # "any vegan drinks?" / "any vegetarian sandwiches?"
    re.compile(r"(?:any|got\s+any|have\s+any)\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy)\s+(\w+(?:\s+\w+)?)\s*\??$", re.IGNORECASE),
    # "vegan drinks?" / "gluten-free bagels?"
    re.compile(r"^(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy)\s+(\w+(?:\s+\w+)?)\s*\??$", re.IGNORECASE),
    # "show me vegan drinks"
    re.compile(r"(?:show|list|tell)\s+(?:me\s+)?(?:your\s+|the\s+)?(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy)\s+(\w+(?:\s+\w+)?)\s*$", re.IGNORECASE),
]

# Patterns for general dietary options inquiry ("do you have vegan options?")
# These ask about what items match a dietary property
DIETARY_OPTIONS_PATTERNS = [
    # "do you have vegan options?" / "do you have any gluten-free items?"
    re.compile(r"do\s+you\s+have\s+(?:any\s+)?(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy|lactose[- ]?free)\s+(?:options?|items?|choices?|food|menu items?)", re.IGNORECASE),
    # "what vegan options do you have?" / "what gluten-free items are there?"
    re.compile(r"what\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy|lactose[- ]?free)\s+(?:options?|items?|choices?|food|menu items?)\s+(?:do\s+you\s+have|are\s+there|you\s+got)", re.IGNORECASE),
    # "any vegan options?" / "any vegetarian items?"
    re.compile(r"(?:any|got\s+any|have\s+any)\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy|lactose[- ]?free)\s+(?:options?|items?|choices?|food)?", re.IGNORECASE),
    # "vegan options?" / "vegetarian menu?"
    re.compile(r"^(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy|lactose[- ]?free)\s+(?:options?|items?|menu|choices?|food)?\s*\??$", re.IGNORECASE),
    # "what's vegan?" / "what is vegetarian?"
    re.compile(r"what(?:'?s|\s+is)\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf)", re.IGNORECASE),
    # "show me vegan items" / "list vegetarian options"
    re.compile(r"(?:show|list|tell)\s+(?:me\s+)?(?:your\s+|the\s+)?(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf|non[- ]?dairy|lactose[- ]?free)\s+(?:options?|items?|menu|choices?)", re.IGNORECASE),
]

# Patterns for specific item dietary inquiry ("is the classic gluten-free?")
# Item type suffixes (sandwich, bagel, etc.) are stripped during menu item matching, not here
DIETARY_ITEM_PATTERNS = [
    # "is the classic vegan?" / "is the BLT gluten-free?"
    re.compile(r"is\s+(?:the\s+|a\s+)?(.+?)\s+(vegan|vegetarian|gluten[- ]?free|dairy[- ]?free|kosher|gf)\s*\??$", re.IGNORECASE),
]

# Patterns for allergen inquiry ("does X contain nuts?")
# Uses dynamically built allergen terms from _ALLERGEN_TERMS
ALLERGEN_ITEM_PATTERNS = [
    # "does the classic contain nuts?" / "does this have eggs?"
    re.compile(rf"does\s+(?:the\s+|a\s+|this\s+)?(.+?)\s+(?:contain|have|include)\s+{_ALLERGEN_TERMS}", re.IGNORECASE),
    # "is there nuts in the classic?" / "are there eggs in this?"
    re.compile(rf"(?:is|are)\s+there\s+{_ALLERGEN_TERMS}\s+in\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "does the classic have any allergens?" (general allergen question)
    re.compile(r"does\s+(?:the\s+|a\s+)?(.+?)\s+have\s+(?:any\s+)?allergens?\s*\??$", re.IGNORECASE),
    # "what allergens are in the classic?"
    re.compile(r"what\s+allergens?\s+(?:are\s+)?in\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "allergens in the classic?" / "nuts in the BLT?"
    re.compile(rf"^({_ALLERGEN_TERMS[1:-1]}|allergens?)\s+in\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
]


def _build_allergen_free_regex_part() -> str:
    """Build regex alternation for allergen-free terms (singular form + dairy)."""
    # Get singular base forms for X-free patterns
    bases = set()
    for col in _get_allergen_columns():
        base = col.replace("contains_", "")
        # Use singular form if ends with 's' (eggs->egg, nuts->nut), else use as-is
        if base.endswith("s") and base != "fish":
            bases.add(base[:-1])
        else:
            bases.add(base)
    bases.add("dairy")  # Common allergen-free term not in contains_ columns
    bases.add("seafood")  # Synonym for fish
    return r"(" + "|".join(sorted(bases, key=len, reverse=True)) + r")"


_ALLERGEN_FREE_TERMS = _build_allergen_free_regex_part()


# Patterns for general allergen-free options inquiry
ALLERGEN_FREE_OPTIONS_PATTERNS = [
    # "do you have anything without nuts?" / "anything nut-free?"
    re.compile(rf"(?:do\s+you\s+have\s+)?(?:any(?:thing)?|items?|options?)\s+(?:without|with\s+no|free\s+of)\s+{_ALLERGEN_TERMS}", re.IGNORECASE),
    # "nut-free options?" / "egg-free items?"
    re.compile(rf"{_ALLERGEN_FREE_TERMS}[- ]?free\s+(?:options?|items?|choices?|menu)?", re.IGNORECASE),
]


# =============================================================================
# Availability Inquiry Patterns
# =============================================================================

# Patterns for checking if specific items are in stock
AVAILABILITY_PATTERNS = [
    # "do you have everything bagels in stock?"
    re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)\s+(?:in\s+stock|available|left|today)\s*\??$", re.IGNORECASE),
    # "are everything bagels available?" / "is the classic available?"
    re.compile(r"(?:are|is)\s+(?:the\s+|any\s+)?(.+?)\s+(?:available|in\s+stock|left)\s*\??$", re.IGNORECASE),
    # "are you out of everything bagels?" / "out of cream cheese?"
    re.compile(r"(?:are\s+you\s+)?out\s+of\s+(?:the\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "do you still have lox?" / "still have cream cheese?"
    re.compile(r"(?:do\s+you\s+)?still\s+have\s+(?:any\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "is the special still available?" / "is the seasonal item available?"
    re.compile(r"is\s+(?:the\s+)?(.+?)\s+still\s+(?:available|in\s+stock)\s*\??$", re.IGNORECASE),
    # "any X left?" / "any everything bagels left?"
    re.compile(r"any\s+(.+?)\s+left\s*\??$", re.IGNORECASE),
    # "do you have X" (simple availability question, "any" and "?" are optional)
    # This is the broadest pattern - must be last so more specific patterns match first
    re.compile(r"do\s+you\s+have\s+(?:any\s+)?(.+?)\s*\??$", re.IGNORECASE),
]


# =============================================================================
# Customization Inquiry Patterns
# =============================================================================

# Patterns for asking about customization possibilities
CUSTOMIZATION_INQUIRY_PATTERNS = [
    # "can I customize the classic?" / "can I modify the BLT?"
    re.compile(r"can\s+i\s+(?:customize|modify|change)\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "is the classic customizable?" / "is the sandwich customizable?"
    re.compile(r"is\s+(?:the\s+|a\s+)?(.+?)\s+(?:customizable|modifiable)\s*\??$", re.IGNORECASE),
    # "what can I change on the classic?" / "what modifications are allowed?"
    re.compile(r"what\s+(?:can\s+i\s+)?(?:change|modify|customize)\s+(?:on|about|with)\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "how customizable is the classic?" / "how customizable is X?"
    re.compile(r"how\s+(?:customizable|modifiable)\s+is\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "what modifications are allowed on X?"
    re.compile(r"what\s+(?:modifications?|changes?|customizations?)\s+(?:are\s+)?(?:allowed|possible|available)\s+(?:on|for|with)\s+(?:the\s+|a\s+)?(.+?)\s*\??$", re.IGNORECASE),
    # "can I get it half-toasted?" - requires "it" to refer to current item
    re.compile(r"can\s+i\s+(?:get|have)\s+it\s+(.+?)\s*\??$", re.IGNORECASE),
    # "can I get extra cream cheese?" - requires modifier keyword (not "a/an/the" which indicates ordering)
    re.compile(r"can\s+i\s+(?:get|have)\s+(?:extra|less|no|without|some|more|a\s+little|double)\s+(.+?)\s*\??$", re.IGNORECASE),
]


# =============================================================================
# Order History Inquiry Patterns
# =============================================================================

# Patterns to detect order history inquiry ("what did I order before?")
ORDER_HISTORY_PATTERNS = [
    # "what did I order before?" / "what have I ordered?"
    re.compile(r"what\s+(?:did|have)\s+i\s+order(?:ed)?(?:\s+before)?(?:\s+here)?\s*\??$", re.IGNORECASE),
    # "my order history" / "order history"
    re.compile(r"(?:my\s+)?(?:order\s+)?history\s*\??$", re.IGNORECASE),
    # "show my orders" / "show my previous orders"
    re.compile(r"(?:show|see|view)\s+(?:me\s+)?(?:my\s+)?(?:previous\s+)?orders?\s*\??$", re.IGNORECASE),
    # "my past orders" / "past orders"
    re.compile(r"(?:my\s+)?past\s+orders?\s*\??$", re.IGNORECASE),
    # "what have I gotten here before?"
    re.compile(r"what\s+have\s+i\s+(?:gotten|had|bought)\s+(?:here\s+)?before\s*\??$", re.IGNORECASE),
    # "my previous orders"
    re.compile(r"(?:my\s+)?previous\s+orders?\s*\??$", re.IGNORECASE),
]

# Patterns to detect view last order inquiry ("what was in my last order?")
VIEW_LAST_ORDER_PATTERNS = [
    # "what was in my last order?"
    re.compile(r"what\s+(?:was|is)\s+in\s+(?:my\s+)?(?:last\s+)?order\s*\??$", re.IGNORECASE),
    # "what did I order last time?" / "what did I have last time?"
    re.compile(r"what\s+did\s+i\s+(?:order|have|get)\s+last\s+time\s*\??$", re.IGNORECASE),
    # "what was my last order?"
    re.compile(r"what\s+(?:was|is)\s+my\s+last\s+order\s*\??$", re.IGNORECASE),
    # "show me my last order" / "tell me about my last order"
    re.compile(r"(?:show|tell)\s+me\s+(?:about\s+)?my\s+last\s+order\s*\??$", re.IGNORECASE),
    # "details of my last order"
    re.compile(r"(?:details?\s+)?(?:of|about)\s+my\s+last\s+order\s*\??$", re.IGNORECASE),
]

# Patterns to detect reorder specific item from history
# Captures the item reference in group(1) or group(2)
REORDER_ITEM_PATTERNS = [
    # "just the bagel from last time" / "the coffee I had before"
    re.compile(r"(?:just\s+)?(?:the\s+)?(.+?)\s+(?:from|i\s+had)\s+(?:last\s+time|before|my\s+last\s+order)\s*\??$", re.IGNORECASE),
    # "order the same coffee as before" / "get the same bagel I had"
    re.compile(r"(?:order|get)\s+(?:the\s+)?same\s+(.+?)\s+(?:i\s+had|as\s+before)\s*\??$", re.IGNORECASE),
    # "same coffee again" / "same bagel as before"
    re.compile(r"same\s+(.+?)\s+(?:again|as\s+before|as\s+last\s+time)\s*\??$", re.IGNORECASE),
]

# Pattern to extract modification text from repeat order requests
# "same as before but iced", "repeat my order except without the bagel"
MODIFICATION_EXTRACTOR = re.compile(
    r"(?:same\s+as\s+(?:before|last\s+time)|repeat\s+(?:my\s+)?(?:last\s+)?order|my\s+usual)"
    r"\s+(?:but|except|and)\s+(.+)",
    re.IGNORECASE
)

# Pattern to detect "without X" modifications
WITHOUT_PATTERN = re.compile(r"without\s+(?:the\s+)?(.+)", re.IGNORECASE)


# Reorder modification keywords - lazily built from cache
_reorder_modification_keywords_cache: dict[str, tuple[str, bool | str]] | None = None


def get_reorder_modification_keywords() -> dict[str, tuple[str, bool | str]]:
    """Get modification keywords for reorder requests, built from menu cache.

    Returns a mapping of keyword -> (attribute_slug, value) for deterministic modification.
    Built lazily from cache data the first time it's called.

    Returns:
        Dict mapping keyword to (attribute_slug, value) tuple.
        Returns empty dict if cache is not loaded.
    """
    global _reorder_modification_keywords_cache

    if _reorder_modification_keywords_cache is not None:
        return _reorder_modification_keywords_cache

    # Build from cache - import here to avoid circular imports
    from orderbot.cache import menu_cache

    keywords: dict[str, tuple[str, bool | str]] = {}

    try:
        option_words = menu_cache.get_all_attribute_option_words()
    except Exception:
        # Cache not loaded - return empty dict
        return {}

    # For each option word, determine the appropriate value
    for word, attr_slug in option_words.items():
        # Get input type for this attribute
        input_type = None
        for item_type_slug, attrs in menu_cache._item_type_attributes.items():
            if attr_slug in attrs:
                input_type = attrs[attr_slug].get("input_type")
                break

        if input_type == "boolean":
            # Boolean attribute: word maps to True
            keywords[word] = (attr_slug, True)
            # Add negation patterns
            keywords[f"not {word}"] = (attr_slug, False)
            keywords[f"un{word}"] = (attr_slug, False)
        else:
            # Non-boolean: word is the value itself
            keywords[word] = (attr_slug, word)

    _reorder_modification_keywords_cache = keywords
    return keywords


def clear_reorder_modification_keywords_cache() -> None:
    """Clear the cached modification keywords. Call when menu cache is reloaded."""
    global _reorder_modification_keywords_cache
    _reorder_modification_keywords_cache = None

# Pattern to detect order number references ("reorder order number 42")
ORDER_NUMBER_PATTERN = re.compile(
    r"(?:reorder|repeat)\s+order\s+(?:number\s+)?#?(\d+)\s*$",
    re.IGNORECASE
)
