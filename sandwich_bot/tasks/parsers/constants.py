"""
Parser Constants.

This module contains constants used by both LLM and deterministic parsers
for recognizing and normalizing user input. These include menu items,
ingredient lists, regex patterns for intent detection, and price data.
"""

import re

# =============================================================================
# Drink Type Categories
# =============================================================================

# Sodas and cold beverages that don't need hot/iced or size configuration
# These are added directly without asking configuration questions
SODA_DRINK_TYPES = {
    "coke", "coca cola", "coca-cola",
    "diet coke", "diet coca cola",
    "coke zero", "coca cola zero",
    "sprite", "diet sprite",
    "fanta", "orange fanta",
    "dr pepper", "dr. pepper",
    "pepsi", "diet pepsi",
    "mountain dew", "mtn dew",
    "ginger ale",
    "root beer",
    "lemonade",
    "iced tea",  # Pre-made bottled iced tea
    "bottled water", "water",
    "sparkling water", "seltzer",
    "juice", "orange juice", "apple juice", "cranberry juice",
    "snapple",
    "gatorade",
    # Dr. Brown's sodas
    "dr brown's", "dr browns", "dr. brown's", "dr. browns",
    "dr brown's cream soda", "dr browns cream soda",
    "dr brown's black cherry", "dr browns black cherry",
    "dr brown's cel-ray", "dr browns cel-ray", "cel-ray",
}

# Coffee/tea beverages that need hot/iced and size configuration
COFFEE_BEVERAGE_TYPES = {
    "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
    "mocha", "cold brew", "tea", "chai", "matcha", "hot chocolate",
}

# Compound tea names - these are full menu item names that should be matched exactly
# Sorted by length (longest first) to ensure more specific matches take priority
COMPOUND_TEA_NAMES = [
    "english breakfast tea",
    "snapple peach tea",
    "snapple iced tea",
    "ito en green tea",
    "iced chai tea",
    "peppermint tea",
    "chamomile tea",
    "earl grey tea",
    "green tea",
    "chai tea",
    "iced tea",
    "hot tea",
]


def is_soda_drink(drink_type: str | None) -> bool:
    """Check if a drink type is a soda/cold beverage that doesn't need configuration."""
    if not drink_type:
        return False
    drink_lower = drink_type.lower().strip()
    # Check exact match first
    if drink_lower in SODA_DRINK_TYPES:
        return True
    # Check if any soda type is contained in the drink name
    for soda in SODA_DRINK_TYPES:
        if soda in drink_lower or drink_lower in soda:
            return True
    return False


# =============================================================================
# Word to Number Mapping
# =============================================================================

WORD_TO_NUM = {
    "a": 1, "an": 1, "one": 1,
    "two": 2, "couple": 2, "a couple": 2, "a couple of": 2, "couple of": 2,
    "three": 3, "a few": 3, "few": 3,
    "four": 4,
    "five": 5,
    "six": 6, "half dozen": 6, "half a dozen": 6, "a half dozen": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12, "dozen": 12, "a dozen": 12,
}

# =============================================================================
# Bagel Types and Spreads
# =============================================================================

BAGEL_TYPES = {
    "plain", "everything", "sesame", "poppy", "onion",
    "cinnamon raisin", "cinnamon", "raisin", "pumpernickel",
    "whole wheat", "wheat", "salt", "garlic", "bialy",
    "egg", "multigrain", "asiago", "jalapeno", "blueberry",
    "gluten free", "gluten-free",
}

SPREADS = {
    "cream cheese", "butter", "peanut butter", "jelly",
    "jam", "nutella", "hummus", "avocado",
}

# Spread types/varieties (exclude "plain" - too ambiguous with bagel type)
SPREAD_TYPES = {
    "scallion", "veggie", "vegetable", "strawberry",
    "honey walnut", "lox", "chive", "garlic herb", "jalapeno",
    "tofu", "olive", "blueberry", "truffle", "nova", "sun-dried tomato",
    "maple raisin walnut", "kalamata olive",
}

# =============================================================================
# Modifier Category Classification
# =============================================================================

# Bagel types that are ONLY bagel types (not spread types)
BAGEL_ONLY_TYPES = {
    "plain", "everything", "sesame", "poppy", "onion",
    "cinnamon raisin", "cinnamon", "raisin", "pumpernickel",
    "whole wheat", "wheat", "salt", "garlic", "bialy",
    "egg", "multigrain", "asiago", "gluten free", "gluten-free",
}

# Spread types that are ONLY spread types (not bagel types)
SPREAD_ONLY_TYPES = {
    "scallion", "veggie", "vegetable", "strawberry",
    "honey walnut", "lox", "chive", "garlic herb",
    "tofu", "olive", "truffle", "nova", "sun-dried tomato",
    "maple raisin walnut", "kalamata olive",
}

# Modifiers that could be EITHER bagel type OR spread type (ambiguous)
AMBIGUOUS_MODIFIERS = {
    "blueberry",  # blueberry bagel or blueberry cream cheese
    "jalapeno",   # jalapeno bagel or jalapeno cream cheese
}

# =============================================================================
# Speed Menu Bagels
# =============================================================================

# Speed menu bagels - pre-configured signature items
# Maps variations to canonical names
SPEED_MENU_BAGELS = {
    # The Classic (nova, cream cheese, capers, onion, tomato)
    "the classic": "The Classic",
    "classic": "The Classic",
    # The Classic BEC (eggs, bacon, cheddar)
    "the classic bec": "The Classic BEC",
    "classic bec": "The Classic BEC",
    "bec": "The Classic BEC",
    "b.e.c.": "The Classic BEC",
    "b.e.c": "The Classic BEC",
    "bacon egg and cheese": "The Classic BEC",
    "bacon egg cheese": "The Classic BEC",
    "bacon and egg and cheese": "The Classic BEC",
    "bacon eggs and cheese": "The Classic BEC",
    "bacon eggs cheese": "The Classic BEC",
    "egg bacon and cheese": "The Classic BEC",
    "egg and bacon and cheese": "The Classic BEC",
    "egg bacon cheese": "The Classic BEC",
    "bacon n egg n cheese": "The Classic BEC",
    "bacon n egg and cheese": "The Classic BEC",
    # Ham and sausage variants (map to BEC as the closest item)
    "ham egg and cheese": "The Classic BEC",
    "ham egg cheese": "The Classic BEC",
    "ham and egg and cheese": "The Classic BEC",
    "ham eggs and cheese": "The Classic BEC",
    "sausage egg and cheese": "The Classic BEC",
    "sausage egg cheese": "The Classic BEC",
    "sausage and egg and cheese": "The Classic BEC",
    "sausage eggs and cheese": "The Classic BEC",
    # The Traditional (nova, cream cheese, capers, onion)
    "the traditional": "The Traditional",
    "traditional": "The Traditional",
    "the zucker's traditional": "The Traditional",
    "zucker's traditional": "The Traditional",
    # The Leo (nova, cream cheese, tomato, onion, capers, scrambled eggs)
    "the leo": "The Leo",
    "leo": "The Leo",
    # The Max Zucker (eggs, pastrami, swiss, mustard)
    "the max zucker": "The Max Zucker",
    "max zucker": "The Max Zucker",
    # The Avocado Toast
    "the avocado toast": "The Avocado Toast",
    "avocado toast": "The Avocado Toast",
    # The Chelsea Club
    "the chelsea club": "The Chelsea Club",
    "chelsea club": "The Chelsea Club",
    # The Flatiron Traditional (sturgeon version)
    "the flatiron traditional": "The Flatiron Traditional",
    "flatiron traditional": "The Flatiron Traditional",
    # The Old School Tuna Sandwich
    "the old school tuna sandwich": "The Old School Tuna Sandwich",
    "the old school tuna": "The Old School Tuna Sandwich",
    "old school tuna sandwich": "The Old School Tuna Sandwich",
    "old school tuna": "The Old School Tuna Sandwich",
    # The Lexington (egg whites, swiss, spinach)
    "the lexington": "The Lexington",
    "lexington": "The Lexington",
    # Latke BEC
    "latke bec": "Latke BEC",
    "the latke bec": "Latke BEC",
    # The Mulberry
    "the mulberry": "The Mulberry",
    "mulberry": "The Mulberry",
    # Truffled Egg Sandwich
    "the truffled egg": "Truffled Egg Sandwich",
    "truffled egg": "Truffled Egg Sandwich",
    "truffled egg sandwich": "Truffled Egg Sandwich",
}

# =============================================================================
# By-the-Pound Items and Prices
# =============================================================================

BY_POUND_ITEMS = {
    "cheese": [
        "Muenster",
        "Swiss",
        "American",
        "Cheddar",
        "Provolone",
        "Gouda",
    ],
    "spread": [
        "Plain Cream Cheese",
        "Scallion Cream Cheese",
        "Vegetable Cream Cheese",
        "Lox Spread",
        "Jalapeño Cream Cheese",
        "Honey Walnut Cream Cheese",
        "Strawberry Cream Cheese",
        "Olive Cream Cheese",
        "Tofu Cream Cheese",
    ],
    "cold_cut": [
        "Turkey Breast",
        "Roast Beef",
        "Pastrami",
        "Corned Beef",
        "Ham",
        "Salami",
        "Bologna",
    ],
    "fish": [
        "Nova Scotia Salmon (Lox)",
        "Baked Salmon",
        "Sable",
        "Whitefish",
        "Kippered Salmon",
        "Smoked Sturgeon",
    ],
    "salad": [
        "Tuna Salad",
        "Egg Salad",
        "Chicken Salad",
        "Whitefish Salad",
        "Baked Salmon Salad",
    ],
}

BY_POUND_CATEGORY_NAMES = {
    "cheese": "cheeses",
    "spread": "spreads",
    "cold_cut": "cold cuts",
    "fish": "smoked fish",
    "salad": "salads",
}

BY_POUND_PRICES = {
    # Cheeses (per pound)
    "muenster": 12.99,
    "swiss": 14.99,
    "american": 10.99,
    "cheddar": 12.99,
    "provolone": 13.99,
    "gouda": 15.99,
    # Spreads (per pound)
    "plain cream cheese": 14.99,
    "scallion cream cheese": 16.99,
    "vegetable cream cheese": 16.99,
    "lox spread": 24.99,
    "jalapeño cream cheese": 16.99,
    "honey walnut cream cheese": 18.99,
    "strawberry cream cheese": 16.99,
    "olive cream cheese": 16.99,
    "tofu cream cheese": 16.99,
    # Cold cuts (per pound)
    "turkey breast": 15.99,
    "turkey": 15.99,
    "roast beef": 18.99,
    "pastrami": 22.99,
    "corned beef": 22.99,
    "ham": 14.99,
    "salami": 16.99,
    "bologna": 12.99,
    # Fish (per pound)
    "nova scotia salmon (lox)": 44.99,
    "nova scotia salmon": 44.99,
    "nova": 44.99,
    "lox": 44.99,
    "baked salmon": 34.99,
    "sable": 54.99,
    "whitefish": 32.99,
    "kippered salmon": 38.99,
    "smoked sturgeon": 64.99,
    "sturgeon": 64.99,
    # Salads (per pound)
    "tuna salad": 18.99,
    "egg salad": 14.99,
    "chicken salad": 16.99,
    "whitefish salad": 28.99,
    "baked salmon salad": 26.99,
}

# =============================================================================
# Bagel Modifiers
# =============================================================================

# Valid proteins that can be added to a bagel
BAGEL_PROTEINS = {
    "bacon", "ham", "turkey", "pastrami", "corned beef",
    "nova", "lox", "nova scotia salmon", "baked salmon",
    "egg", "eggs", "egg white", "egg whites", "scrambled egg", "scrambled eggs",
    "sausage", "avocado",
}

# Valid cheeses
BAGEL_CHEESES = {
    "american", "american cheese",
    "swiss", "swiss cheese",
    "cheddar", "cheddar cheese",
    "muenster", "muenster cheese",
    "provolone", "provolone cheese",
    "gouda", "gouda cheese",
    "mozzarella", "mozzarella cheese",
    "pepper jack", "pepper jack cheese",
}

# Valid toppings/extras
BAGEL_TOPPINGS = {
    "tomato", "tomatoes",
    "onion", "onions", "red onion", "red onions",
    "lettuce",
    "capers",
    "cucumber", "cucumbers",
    "pickles", "pickle",
    "sauerkraut",
    "sprouts",
    "everything seeds",
    "mayo", "mayonnaise",
    "mustard",
    "ketchup",
    "hot sauce",
    "salt", "pepper", "salt and pepper",
}

# Valid spreads (cream cheese varieties, butter)
BAGEL_SPREADS = {
    "cream cheese", "plain cream cheese",
    "scallion cream cheese", "scallion",
    "veggie cream cheese", "vegetable cream cheese", "veggie",
    "lox spread",
    "jalapeño cream cheese", "jalapeno cream cheese",
    "honey walnut cream cheese", "honey walnut",
    "strawberry cream cheese", "strawberry",
    "blueberry cream cheese", "blueberry",
    "olive cream cheese", "olive",
    "tofu cream cheese", "tofu",
    "butter",
}

# Map short names to full names for normalization
MODIFIER_NORMALIZATIONS = {
    # Proteins
    "eggs": "egg",
    "egg whites": "egg white",
    "scrambled eggs": "scrambled egg",
    "nova": "nova scotia salmon",
    "lox": "nova scotia salmon",
    # Cheeses - normalize to just the cheese name
    "american cheese": "american",
    "swiss cheese": "swiss",
    "cheddar cheese": "cheddar",
    "muenster cheese": "muenster",
    "provolone cheese": "provolone",
    "gouda cheese": "gouda",
    "mozzarella cheese": "mozzarella",
    "pepper jack cheese": "pepper jack",
    # Toppings
    "tomatoes": "tomato",
    "onions": "onion",
    "red onions": "red onion",
    "cucumbers": "cucumber",
    "pickles": "pickle",
    # Spreads
    "plain cream cheese": "cream cheese",
    "veggie cream cheese": "vegetable cream cheese",
    "veggie": "vegetable cream cheese",
    "scallion": "scallion cream cheese",
    "strawberry": "strawberry cream cheese",
    "blueberry": "blueberry cream cheese",
    "olive": "olive cream cheese",
    "honey walnut": "honey walnut cream cheese",
    "tofu": "tofu cream cheese",
    "jalapeno cream cheese": "jalapeño cream cheese",
}

# =============================================================================
# Regex Patterns
# =============================================================================

# Qualifier patterns for notes extraction
# These are phrases that modify a standard modifier in a non-standard way
QUALIFIER_PATTERNS = [
    # "light on the X" / "light X" / "go light on X"
    (r'\b(?:go\s+)?light\s+(?:on\s+(?:the\s+)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'light'),
    # "easy on the X" / "go easy on the X"
    (r'\b(?:go\s+)?easy\s+on\s+(?:the\s+)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'light'),
    # "extra X" / "extra heavy on the X"
    (r'\bextra\s+(?:heavy\s+(?:on\s+(?:the\s+)?)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "lots of X" / "a lot of X"
    (r'\b(?:a\s+)?lot(?:s)?\s+of\s+(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "heavy on the X"
    (r'\bheavy\s+(?:on\s+(?:the\s+)?)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'extra'),
    # "a splash of X" / "splash of X"
    (r'\b(?:a\s+)?splash\s+of\s+(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'a splash of'),
    # "a little X" / "just a little X"
    (r'\b(?:just\s+)?a\s+little\s+(?:bit\s+of\s+)?(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'a little'),
    # "no X" / "hold the X" / "without X"
    (r'\b(?:no\s+|hold\s+the\s+|without\s+)(\w+(?:\s+(?!and\b|or\b|with\b|a\b|the\b)\w+)?)', 'no'),
]

# Greeting patterns
GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|good morning|good afternoon|good evening|howdy|yo)[\s!.,]*$",
    re.IGNORECASE
)

# Done ordering patterns
DONE_PATTERNS = re.compile(
    r"^(that'?s?\s*(all|it)|no(pe|thing)?(\s*(else|more))?|i'?m\s*(good|done|all\s*set)|"
    r"nothing(\s*(else|more))?|done|all\s*set|that\s*will\s*be\s*all|nah)[\s!.,]*$",
    re.IGNORECASE
)

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
    # "can you change it to X" / "could you make it X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+(?:it|that)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "can you change the bagel to X"
    (re.compile(r"(?:can|could|would)\s+you\s+(?:change|make|switch)\s+the\s+(\w+(?:\s+\w+)?)\s+to\s+(.+?)(?:\?|$)", re.IGNORECASE), (1, 2)),
    # "actually X instead" / "actually make it X"
    (re.compile(r"actually\s+(?:make\s+it\s+)?(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "I meant X" / "I want X instead"
    (re.compile(r"(?:i\s+meant|i\s+want(?:ed)?)\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
    # "no wait, X" / "wait, X instead"
    (re.compile(r"(?:no\s+)?wait[,.]?\s+(.+?)(?:\s+instead)?(?:\?|$)", re.IGNORECASE), (None, 1)),
]

# Repeat order patterns: "repeat my order", "same as last time", "my usual", etc.
REPEAT_ORDER_PATTERNS = re.compile(
    r"^(repeat\s+(my\s+)?(last\s+)?order|same\s+(as\s+)?(last\s+time|before)|"
    r"(my\s+)?usual|what\s+i\s+(usually\s+)?(get|have|order)|"
    r"same\s+(thing|order)(\s+as\s+(last\s+time|before))?|"
    r"(i'?ll\s+have\s+)?(the\s+)?same(\s+(thing|order))?(\s+again)?|"
    r"repeat\s+(that|it)|order\s+again)[\s!.,]*$",
    re.IGNORECASE
)

# =============================================================================
# Side Item Mapping
# =============================================================================

# Map of side item keywords to canonical menu names
SIDE_ITEM_MAP = {
    "sausage": "Side of Sausage",
    "turkey sausage": "Side of Sausage",  # No turkey sausage on menu, map to regular
    "bacon": "Side of Bacon",
    "turkey bacon": "Side of Turkey Bacon",
    "ham": "Side of Ham",
    "chicken sausage": "Side of Chicken Sausage",
    "latke": "Side of Breakfast Latke",
    "breakfast latke": "Side of Breakfast Latke",
    "hard boiled egg": "Hard Boiled Egg (2)",
    "eggs": "Hard Boiled Egg (2)",
}

# Side item types (chips, salads, etc.)
SIDE_ITEM_TYPES = {
    "chips", "potato chips", "kettle chips",
    "salad", "side salad", "green salad",
    "fruit", "fresh fruit", "fruit cup",
    "coleslaw", "cole slaw",
    "pickle", "pickles",
    "fries", "french fries",
    "soup", "soup of the day",
}

# =============================================================================
# Menu Item Recognition
# =============================================================================

# Known menu item names for deterministic matching
# Items starting with "the" will be prefixed with "The " in canonical form
# Other items (sandwiches, etc.) will be title-cased without prefix
KNOWN_MENU_ITEMS = {
    # Egg sandwiches (signature items with "The" prefix)
    "the lexington", "lexington",
    "the classic bec", "classic bec",
    "the grand central", "grand central",
    "the wall street", "wall street",
    "the tribeca", "tribeca",
    "the columbus", "columbus",
    "the hudson", "hudson",
    "the chelsea", "chelsea",
    "the midtown", "midtown",
    # Other signature sandwiches (with "The" prefix)
    "the delancey", "delancey",
    "the leo", "leo",
    "the avocado toast", "avocado toast",
    "the health nut", "health nut",
    "the zucker's traditional", "zucker's traditional", "the traditional", "traditional",
    "the reuben", "reuben",
    "the blt", "blt",
    "the chelsea club", "chelsea club",
    "the natural", "natural",
    "turkey club",
    "hot pastrami sandwich", "pastrami sandwich",
    "nova scotia salmon", "nova salmon",
    # Omelettes
    "chipotle egg omelette", "the chipotle egg omelette", "chipotle omelette",
    "cheese omelette",
    "western omelette",
    "veggie omelette",
    "spinach & feta omelette", "spinach and feta omelette", "spinach feta omelette",
    "spinach & feta omelet", "spinach and feta omelet", "spinach feta omelet",
    # Spread Sandwiches (cream cheese, butter, etc.)
    "plain cream cheese sandwich", "plain cream cheese",
    "scallion cream cheese sandwich", "scallion cream cheese",
    "vegetable cream cheese sandwich", "veggie cream cheese", "vegetable cream cheese",
    "sun-dried tomato cream cheese sandwich", "sun dried tomato cream cheese",
    "strawberry cream cheese sandwich", "strawberry cream cheese",
    "blueberry cream cheese sandwich", "blueberry cream cheese",
    "kalamata olive cream cheese sandwich", "olive cream cheese",
    "maple raisin walnut cream cheese sandwich", "maple raisin walnut", "maple walnut cream cheese",
    "jalapeno cream cheese sandwich", "jalapeno cream cheese", "jalapeño cream cheese",
    "nova scotia cream cheese sandwich", "nova cream cheese", "lox spread sandwich",
    "truffle cream cheese sandwich", "truffle cream cheese",
    "butter sandwich", "bagel with butter",
    "peanut butter sandwich", "peanut butter bagel",
    "nutella sandwich", "nutella bagel",
    "hummus sandwich", "hummus bagel", "hummus",
    "avocado spread sandwich", "avocado spread",
    "tofu plain sandwich", "tofu plain", "plain tofu",
    "tofu scallion sandwich", "tofu scallion", "scallion tofu",
    "tofu vegetable sandwich", "tofu veggie", "tofu vegetable", "veggie tofu",
    "tofu nova sandwich", "tofu nova", "nova tofu",
    # Smoked Fish Sandwiches (not salads - these are actual fish)
    "belly lox sandwich", "belly lox", "belly lox on bagel",
    "gravlax sandwich", "gravlax", "gravlax on bagel",
    "nova scotia salmon sandwich", "nova sandwich", "nova on bagel",
    # Salad Sandwiches
    "tuna salad sandwich", "tuna salad", "tuna sandwich",
    "whitefish salad sandwich", "whitefish salad", "whitefish sandwich",
    "baked salmon salad sandwich", "baked salmon salad", "salmon salad sandwich",
    "egg salad sandwich", "egg salad",
    "chicken salad sandwich", "chicken salad",
    "cranberry pecan chicken salad sandwich", "cranberry pecan chicken salad", "cranberry chicken salad",
    "lemon chicken salad sandwich", "lemon chicken salad",
    # Additional omelettes
    "the mulberry omelette", "mulberry omelette", "the mulberry", "mulberry",
    "the nova omelette", "nova omelette",
    "bacon and cheddar omelette", "bacon cheddar omelette",
    # Grilled items
    "grilled cheese", "grilled cheese sandwich",
    # Sides (for multi-item orders)
    "side of bacon", "bacon", "side of sausage", "sausage",
    "turkey bacon", "side of turkey bacon",
    "latkes", "potato latkes",
    "bagel chips", "chips",
    "fruit cup", "fruit salad",
    "cole slaw", "coleslaw",
    "potato salad", "macaroni salad",
    # Breakfast items
    "oatmeal", "steel cut oatmeal", "organic steel-cut oatmeal",
    "yogurt parfait", "yogurt", "low fat yogurt granola parfait",
    # Nova/Lox synonyms (for natural language matching)
    "nova lox", "nova lox sandwich", "lox sandwich", "lox",
    # Pastries and snacks (for multi-item orders)
    "blueberry muffin", "corn muffin", "chocolate chip muffin",
    "banana walnut muffin", "cranberry muffin", "lemon poppy muffin",
    "morning glory muffin", "apple cinnamon muffin", "double-chocolate muffin",
    "muffin",  # Generic - will ask for type
    "black and white cookie", "black & white cookie", "chocolate chip cookie",
    "peanut butter cookie", "oatmeal raisin cookie",
    "cookie",  # Generic - will ask for type
    "brownie", "danish", "rugelach", "babka",
    # Specific beverage items (need to match before generic coffee parsing)
    "tropicana orange juice 46 oz", "tropicana orange juice", "tropicana 46 oz",
    "tropicana no pulp", "tropicana",
    "fresh squeezed orange juice",
}

# Items that should NOT get "The " prefix (salad and spread sandwiches)
NO_THE_PREFIX_ITEMS = {
    "plain cream cheese sandwich", "plain cream cheese",
    "scallion cream cheese sandwich", "scallion cream cheese",
    "vegetable cream cheese sandwich", "veggie cream cheese", "vegetable cream cheese",
    "sun-dried tomato cream cheese sandwich", "sun dried tomato cream cheese",
    "strawberry cream cheese sandwich", "strawberry cream cheese",
    "blueberry cream cheese sandwich", "blueberry cream cheese",
    "kalamata olive cream cheese sandwich", "olive cream cheese",
    "maple raisin walnut cream cheese sandwich", "maple raisin walnut", "maple walnut cream cheese",
    "jalapeno cream cheese sandwich", "jalapeno cream cheese", "jalapeño cream cheese",
    "nova scotia cream cheese sandwich", "nova cream cheese", "lox spread sandwich",
    "truffle cream cheese sandwich", "truffle cream cheese",
    "butter sandwich", "bagel with butter",
    "peanut butter sandwich", "peanut butter bagel",
    "nutella sandwich", "nutella bagel",
    "hummus sandwich", "hummus bagel", "hummus",
    "avocado spread sandwich", "avocado spread",
    "tofu plain sandwich", "tofu plain", "plain tofu",
    "tofu scallion sandwich", "tofu scallion", "scallion tofu",
    "tofu vegetable sandwich", "tofu veggie", "tofu vegetable", "veggie tofu",
    "tofu nova sandwich", "tofu nova", "nova tofu",
    # Smoked Fish Sandwiches
    "belly lox sandwich", "belly lox", "belly lox on bagel",
    "gravlax sandwich", "gravlax", "gravlax on bagel",
    "nova scotia salmon sandwich", "nova sandwich", "nova on bagel",
    # Salad Sandwiches
    "tuna salad sandwich", "tuna salad", "tuna sandwich",
    "whitefish salad sandwich", "whitefish salad", "whitefish sandwich",
    "baked salmon salad sandwich", "baked salmon salad", "salmon salad sandwich",
    "egg salad sandwich", "egg salad",
    "chicken salad sandwich", "chicken salad",
    "cranberry pecan chicken salad sandwich", "cranberry pecan chicken salad", "cranberry chicken salad",
    "lemon chicken salad sandwich", "lemon chicken salad",
    "turkey club",
    "hot pastrami sandwich", "pastrami sandwich",
    "cheese omelette",
    "western omelette",
    "veggie omelette",
    "spinach & feta omelette", "spinach and feta omelette", "spinach feta omelette",
    "spinach & feta omelet", "spinach and feta omelet", "spinach feta omelet",
    "mulberry omelette", "bacon and cheddar omelette", "bacon cheddar omelette",
    "nova omelette",
    # Grilled items (no "The" prefix)
    "grilled cheese", "grilled cheese sandwich",
    # Sides (no "The" prefix)
    "side of bacon", "bacon", "side of sausage", "sausage",
    "turkey bacon", "side of turkey bacon",
    "latkes", "potato latkes",
    "bagel chips", "chips",
    "fruit cup", "fruit salad",
    "cole slaw", "coleslaw",
    "potato salad", "macaroni salad",
    # Breakfast items (no "The" prefix)
    "oatmeal", "steel cut oatmeal", "organic steel-cut oatmeal",
    "yogurt parfait", "yogurt", "low fat yogurt granola parfait",
    # Nova/Lox synonyms
    "nova lox", "nova lox sandwich", "lox sandwich", "lox",
    # Specific beverage items
    "tropicana orange juice 46 oz", "tropicana orange juice", "tropicana 46 oz",
    "tropicana no pulp", "tropicana",
    "fresh squeezed orange juice",
}

# Mapping from short forms to canonical menu item names
MENU_ITEM_CANONICAL_NAMES = {
    # Spread sandwiches - map short forms to full names
    "plain cream cheese": "Plain Cream Cheese Sandwich",
    "scallion cream cheese": "Scallion Cream Cheese Sandwich",
    "veggie cream cheese": "Vegetable Cream Cheese Sandwich",
    "vegetable cream cheese": "Vegetable Cream Cheese Sandwich",
    "sun dried tomato cream cheese": "Sun-Dried Tomato Cream Cheese Sandwich",
    "strawberry cream cheese": "Strawberry Cream Cheese Sandwich",
    "blueberry cream cheese": "Blueberry Cream Cheese Sandwich",
    "olive cream cheese": "Kalamata Olive Cream Cheese Sandwich",
    "maple raisin walnut": "Maple Raisin Walnut Cream Cheese Sandwich",
    "maple walnut cream cheese": "Maple Raisin Walnut Cream Cheese Sandwich",
    "jalapeno cream cheese": "Jalapeno Cream Cheese Sandwich",
    "jalapeño cream cheese": "Jalapeno Cream Cheese Sandwich",
    "nova cream cheese": "Nova Scotia Cream Cheese Sandwich",
    "lox spread sandwich": "Nova Scotia Cream Cheese Sandwich",
    "truffle cream cheese": "Truffle Cream Cheese Sandwich",
    "bagel with butter": "Butter Sandwich",
    "peanut butter bagel": "Peanut Butter Sandwich",
    "nutella bagel": "Nutella Sandwich",
    "hummus bagel": "Hummus Sandwich",
    "avocado spread": "Avocado Spread Sandwich",
    "tofu plain": "Tofu Plain Sandwich",
    "plain tofu": "Tofu Plain Sandwich",
    "tofu scallion": "Tofu Scallion Sandwich",
    "scallion tofu": "Tofu Scallion Sandwich",
    "tofu veggie": "Tofu Vegetable Sandwich",
    "tofu vegetable": "Tofu Vegetable Sandwich",
    "veggie tofu": "Tofu Vegetable Sandwich",
    "tofu nova": "Tofu Nova Sandwich",
    "nova tofu": "Tofu Nova Sandwich",
    # Smoked fish sandwiches - map short forms to full names
    "belly lox": "Belly Lox Sandwich",
    "belly lox sandwich": "Belly Lox Sandwich",
    "belly lox on bagel": "Belly Lox Sandwich",
    "gravlax": "Gravlax Sandwich",
    "gravlax sandwich": "Gravlax Sandwich",
    "gravlax on bagel": "Gravlax Sandwich",
    "nova sandwich": "Nova Scotia Salmon Sandwich",
    "nova on bagel": "Nova Scotia Salmon Sandwich",
    # Salad sandwiches - map short forms to full names
    "tuna salad": "Tuna Salad Sandwich",
    "tuna sandwich": "Tuna Salad Sandwich",
    "whitefish salad": "Whitefish Salad Sandwich",
    "whitefish sandwich": "Whitefish Salad Sandwich",
    "baked salmon salad": "Baked Salmon Salad Sandwich",
    "salmon salad sandwich": "Baked Salmon Salad Sandwich",
    "egg salad": "Egg Salad Sandwich",
    "chicken salad": "Chicken Salad Sandwich",
    "cranberry pecan chicken salad": "Cranberry Pecan Chicken Salad Sandwich",
    "cranberry chicken salad": "Cranberry Pecan Chicken Salad Sandwich",
    "lemon chicken salad": "Lemon Chicken Salad Sandwich",
    # Signature sandwiches - uppercase acronyms
    "blt": "The BLT",
    "the blt": "The BLT",
    "chelsea club": "The Chelsea Club",
    "the chelsea club": "The Chelsea Club",
    "natural": "The Natural",
    "the natural": "The Natural",
    # Specific beverage items
    # Note: "tropicana orange juice" is intentionally NOT mapped here to allow
    # lookup_menu_items to find both "Tropicana Orange Juice 46 oz" and
    # "Tropicana Orange Juice No Pulp" and ask user for clarification
    "tropicana orange juice 46 oz": "Tropicana Orange Juice 46 oz",
    "tropicana 46 oz": "Tropicana Orange Juice 46 oz",
    "tropicana no pulp": "Tropicana Orange Juice No Pulp",
    "tropicana": "Tropicana Orange Juice No Pulp",
    "fresh squeezed orange juice": "Fresh Squeezed Orange Juice",
    # Dr. Brown's sodas - map to database names (with period)
    "dr brown's cream soda": "Dr. Brown's Cream Soda",
    "dr browns cream soda": "Dr. Brown's Cream Soda",
    "dr brown's black cherry": "Dr. Brown's Black Cherry",
    "dr browns black cherry": "Dr. Brown's Black Cherry",
    "dr brown's cel-ray": "Dr. Brown's Cel-Ray",
    "dr browns cel-ray": "Dr. Brown's Cel-Ray",
    "cel-ray": "Dr. Brown's Cel-Ray",
    "dr brown's": "Dr. Brown's Cream Soda",  # Default to cream soda
    "dr browns": "Dr. Brown's Cream Soda",
    "dr. brown's": "Dr. Brown's Cream Soda",
    "dr. browns": "Dr. Brown's Cream Soda",
    # Omelettes - map "and" to "&" for database match
    "spinach and feta omelette": "Spinach & Feta Omelette",
    "spinach feta omelette": "Spinach & Feta Omelette",
    # Single 't' spelling variants (omelet vs omelette)
    "spinach and feta omelet": "Spinach & Feta Omelette",
    "spinach feta omelet": "Spinach & Feta Omelette",
    "spinach & feta omelet": "Spinach & Feta Omelette",
    # Additional omelettes
    "mulberry": "The Mulberry Omelette",
    "the mulberry": "The Mulberry Omelette",
    "mulberry omelette": "The Mulberry Omelette",
    "the mulberry omelette": "The Mulberry Omelette",
    "nova omelette": "The Nova Omelette",
    "the nova omelette": "The Nova Omelette",
    "bacon and cheddar omelette": "Bacon and Cheddar Omelette",
    "bacon cheddar omelette": "Bacon and Cheddar Omelette",
    # Grilled items
    "grilled cheese": "Grilled Cheese",
    "grilled cheese sandwich": "Grilled Cheese",
    # Sides
    "side of bacon": "Bacon",
    "bacon": "Bacon",
    "side of sausage": "Side of Sausage",
    "sausage": "Side of Sausage",
    "turkey bacon": "Turkey Bacon",
    "side of turkey bacon": "Turkey Bacon",
    "latkes": "Latkes",
    "potato latkes": "Latkes",
    "bagel chips": "Bagel Chips",
    "chips": "Bagel Chips",
    "fruit cup": "Fruit Cup",
    "fruit salad": "Fruit Salad",
    "cole slaw": "Cole Slaw",
    "coleslaw": "Cole Slaw",
    "potato salad": "Potato Salad",
    "macaroni salad": "Macaroni Salad",
    # Breakfast items
    "oatmeal": "Oatmeal",
    "steel cut oatmeal": "Organic Steel-Cut Oatmeal",
    "organic steel-cut oatmeal": "Organic Steel-Cut Oatmeal",
    "yogurt parfait": "Yogurt Parfait",
    "yogurt": "Yogurt Parfait",
    "low fat yogurt granola parfait": "Low Fat Yogurt Granola Parfait",
    # Nova/Lox synonyms - map to Nova Scotia Salmon Sandwich
    "nova lox": "Nova Scotia Salmon Sandwich",
    "nova lox sandwich": "Nova Scotia Salmon Sandwich",
    "lox sandwich": "Nova Scotia Salmon Sandwich",
    "lox": "Belly Lox Sandwich",  # "lox" alone defaults to Belly Lox
}

# =============================================================================
# Coffee Typo Corrections
# =============================================================================

# Common typos/variations for coffee beverages
COFFEE_TYPO_MAP = {
    "appuccino": "cappuccino",
    "capuccino": "cappuccino",
    "cappucino": "cappuccino",
    "cappuccinno": "cappuccino",
    "capuchino": "cappuccino",
    "expresso": "espresso",
    "expreso": "espresso",
    "esspresso": "espresso",
    "late": "latte",
    "lattee": "latte",
    "latte'": "latte",
    "americano": "americano",
    "amercano": "americano",
    "macchiato": "macchiato",
    "machiato": "macchiato",
    "machato": "macchiato",
    "mocca": "mocha",
    "moca": "mocha",
}

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

# Menu type keywords for category price inquiries (e.g., "how much are bagels?")
# Only plural forms - singular forms should be treated as specific item queries
MENU_CATEGORY_KEYWORDS = {
    "bagels": "bagel",
    "coffees": "coffee",
    "lattes": "coffee",
    "cappuccinos": "coffee",
    "espressos": "coffee",
    "teas": "tea",
    "drinks": "beverage",
    "beverages": "beverage",
    "sodas": "beverage",
    "sandwiches": "sandwich",
    "egg sandwiches": "egg_sandwich",
    "fish sandwiches": "fish_sandwich",
    "cream cheese sandwiches": "spread_sandwich",
    "spread sandwiches": "spread_sandwich",
    "salad sandwiches": "salad_sandwich",
    "deli sandwiches": "deli_sandwich",
    "signature sandwiches": "signature_sandwich",
    "omelettes": "omelette",
    "sides": "side",
    # Desserts and pastries
    "desserts": "dessert",
    "pastries": "dessert",
    "sweets": "dessert",
    "sweet stuff": "dessert",
    "bakery": "dessert",
    "baked goods": "dessert",
    "treats": "dessert",
    "cookies": "dessert",
    "muffins": "dessert",
    "brownies": "dessert",
    "donuts": "dessert",
    "doughnuts": "dessert",
}

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

# NYC neighborhood to zip code mapping (common neighborhoods)
NYC_NEIGHBORHOOD_ZIPS = {
    # Manhattan
    "tribeca": ["10007", "10013", "10282"],
    "soho": ["10012", "10013"],
    "noho": ["10003", "10012"],
    "greenwich village": ["10003", "10011", "10012", "10014"],
    "west village": ["10011", "10014"],
    "east village": ["10003", "10009"],
    "lower east side": ["10002"],
    "les": ["10002"],
    "chinatown": ["10002", "10013"],
    "little italy": ["10012", "10013"],
    "nolita": ["10012"],
    "chelsea": ["10001", "10011"],
    "flatiron": ["10010", "10016"],
    "gramercy": ["10003", "10010", "10016"],
    "murray hill": ["10016", "10017"],
    "midtown": ["10017", "10018", "10019", "10020", "10036"],
    "midtown east": ["10017", "10022"],
    "midtown west": ["10019", "10036"],
    "hell's kitchen": ["10019", "10036"],
    "times square": ["10036"],
    "upper east side": ["10021", "10028", "10065", "10075", "10128"],
    "ues": ["10021", "10028", "10065", "10075", "10128"],
    "upper west side": ["10023", "10024", "10025"],
    "uws": ["10023", "10024", "10025"],
    "harlem": ["10026", "10027", "10030", "10037", "10039"],
    "east harlem": ["10029", "10035"],
    "washington heights": ["10032", "10033", "10040"],
    "inwood": ["10034", "10040"],
    "financial district": ["10004", "10005", "10006", "10038"],
    "fidi": ["10004", "10005", "10006", "10038"],
    "battery park": ["10004", "10280", "10282"],
    "battery park city": ["10280", "10282"],
    # Brooklyn
    "williamsburg": ["11211", "11249"],
    "greenpoint": ["11222"],
    "bushwick": ["11206", "11221", "11237"],
    "bed-stuy": ["11205", "11206", "11216", "11221", "11233"],
    "bedford-stuyvesant": ["11205", "11206", "11216", "11221", "11233"],
    "crown heights": ["11213", "11216", "11225", "11238"],
    "prospect heights": ["11217", "11238"],
    "park slope": ["11215", "11217"],
    "cobble hill": ["11201"],
    "brooklyn heights": ["11201"],
    "dumbo": ["11201"],
    "downtown brooklyn": ["11201", "11217"],
    "fort greene": ["11205", "11217"],
    "clinton hill": ["11205", "11238"],
    "boerum hill": ["11201", "11217"],
    "carroll gardens": ["11231"],
    "red hook": ["11231"],
    "sunset park": ["11220", "11232"],
    "bay ridge": ["11209", "11220"],
    "flatbush": ["11226", "11230", "11234"],
    "bensonhurst": ["11204", "11214", "11219"],
    "borough park": ["11204", "11219"],
    "coney island": ["11224"],
    "brighton beach": ["11235"],
    # Queens
    "astoria": ["11102", "11103", "11105", "11106"],
    "long island city": ["11101", "11109"],
    "lic": ["11101", "11109"],
    "sunnyside": ["11104"],
    "woodside": ["11377"],
    "jackson heights": ["11372"],
    "flushing": ["11354", "11355", "11358"],
    "forest hills": ["11375"],
    "rego park": ["11374"],
    "jamaica": ["11432", "11433", "11434", "11435"],
    "bayside": ["11360", "11361"],
    # Bronx
    "south bronx": ["10451", "10454", "10455", "10459"],
    "mott haven": ["10451", "10454"],
    "hunts point": ["10459", "10474"],
    "fordham": ["10458", "10468"],
    "riverdale": ["10463", "10471"],
}

# =============================================================================
# Recommendation Inquiry Patterns
# =============================================================================

# Recommendation inquiry patterns - these are QUESTIONS, not orders
# When matched, we should answer with recommendations but NOT add to cart
RECOMMENDATION_PATTERNS = [
    # General recommendations - catch-all patterns (order matters, specific first)
    (re.compile(r"what\s+(?:do\s+you|would\s+you|should\s+i|can\s+you)\s+recommend\??$", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular|the\s+best)\??$", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:most\s+)?popular\??$", re.IGNORECASE), "general"),
    (re.compile(r"what\s+(?:are\s+)?(?:your\s+)?(?:best|most\s+popular)\s+(?:sellers?|items?)", re.IGNORECASE), "general"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?most\s+popular\s+item", re.IGNORECASE), "general"),
    (re.compile(r"(?:any|have\s+any|got\s+any|do\s+you\s+have\s+any)\s+recommendations?\??", re.IGNORECASE), "general"),
    (re.compile(r"(?:suggest|recommend)\s+(?:something|anything)", re.IGNORECASE), "general"),
    (re.compile(r"what\s+sells\s+best", re.IGNORECASE), "general"),
    # Bagel-specific recommendations
    (re.compile(r"what\s+(?:kind\s+of\s+)?bagels?\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "bagel"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+bagel", re.IGNORECASE), "bagel"),
    (re.compile(r"which\s+bagels?\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE), "bagel"),
    (re.compile(r"recommend\s+(?:a\s+)?bagel", re.IGNORECASE), "bagel"),
    (re.compile(r"(?:best|popular|favorite)\s+bagels?", re.IGNORECASE), "bagel"),
    (re.compile(r"what(?:'?s|\s+is)\s+popular\s+for\s+bagels?\??", re.IGNORECASE), "bagel"),
    # Sandwich-specific recommendations
    (re.compile(r"what\s+sandwi(?:ch|ches)\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "sandwich"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+sandwich", re.IGNORECASE), "sandwich"),
    (re.compile(r"which\s+sandwi(?:ch|ches)\s+(?:is|are)\s+(?:best|popular|good)", re.IGNORECASE), "sandwich"),
    (re.compile(r"recommend\s+(?:a\s+)?sandwich", re.IGNORECASE), "sandwich"),
    (re.compile(r"(?:best|popular|favorite)\s+sandwi(?:ch|ches)", re.IGNORECASE), "sandwich"),
    # Coffee-specific recommendations
    (re.compile(r"what\s+(?:kind\s+of\s+)?(?:coffee|drink)s?\s+(?:do\s+you|would\s+you|should\s+i)\s+recommend", re.IGNORECASE), "coffee"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:your\s+)?(?:best|most\s+popular)\s+(?:coffee|drink)", re.IGNORECASE), "coffee"),
    (re.compile(r"recommend\s+(?:a\s+)?(?:coffee|drink)", re.IGNORECASE), "coffee"),
    (re.compile(r"what\s+coffee\s+is\s+(?:popular|good|best)", re.IGNORECASE), "coffee"),
    # Breakfast/lunch recommendations
    (re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"what(?:'?s|\s+is)\s+good\s+for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"recommend\s+(?:something\s+)?for\s+breakfast", re.IGNORECASE), "breakfast"),
    (re.compile(r"what\s+(?:do\s+you\s+)?recommend\s+for\s+lunch", re.IGNORECASE), "lunch"),
    (re.compile(r"what(?:'?s|\s+is)\s+(?:good|popular)\s+for\s+lunch", re.IGNORECASE), "lunch"),
    (re.compile(r"recommend\s+(?:something\s+)?for\s+lunch", re.IGNORECASE), "lunch"),
]

# =============================================================================
# Item Description Inquiry Patterns
# =============================================================================

# =============================================================================
# String Normalization Utilities
# =============================================================================

def normalize_for_match(s: str) -> str:
    """
    Normalize a string for fuzzy matching.

    Handles variations like:
    - "blue berry" matching "blueberry"
    - "black and white" matching "black & white"

    Args:
        s: The string to normalize

    Returns:
        Normalized string with spaces removed and & converted to "and"
    """
    return s.replace("&", "and").replace(" ", "")


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
