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
    re.compile(r"what\s+(?:are|is)\s+(?:your|the)\s+hours", re.IGNORECASE),
    re.compile(r"when\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:are\s+you|you)\s+open\s+(?:today|now|on)", re.IGNORECASE),
    re.compile(r"what\s+time\s+(?:do\s+you|are\s+you)\s+(?:open|close)", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:hours|opening\s+hours|business\s+hours)", re.IGNORECASE),
    re.compile(r"how\s+late\s+(?:are\s+you|do\s+you\s+stay)\s+open", re.IGNORECASE),
]

STORE_LOCATION_PATTERNS = [
    re.compile(r"where\s+(?:are\s+you|is\s+the\s+store)\s+located", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your|the)\s+address", re.IGNORECASE),
    re.compile(r"(?:your|the)\s+(?:address|location)", re.IGNORECASE),
    re.compile(r"where\s+(?:are\s+you|is\s+(?:this|the\s+store))", re.IGNORECASE),
    re.compile(r"how\s+do\s+i\s+(?:get|find)\s+(?:you|there|the\s+store)", re.IGNORECASE),
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
    re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular|the\s+best)\??$", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:most\s+)?popular\??$", re.IGNORECASE),
    re.compile(r"what\s+(?:are\s+)?(?:your\s+)?(?:best|most\s+popular)\s+(?:sellers?|items?)", re.IGNORECASE),
    re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?most\s+popular\s+item", re.IGNORECASE),
    re.compile(r"(?:any|have\s+any|got\s+any|do\s+you\s+have\s+any)\s+recommendations?\??", re.IGNORECASE),
    re.compile(r"(?:suggest|recommend)\s+(?:something|anything)", re.IGNORECASE),
    re.compile(r"what\s+sells\s+best", re.IGNORECASE),
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
