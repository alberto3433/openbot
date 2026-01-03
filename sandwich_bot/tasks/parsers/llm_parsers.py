"""
LLM-Powered Parsers.

This module contains all parsing functions that use instructor/OpenAI
to parse user input in context-specific ways. Each function is designed
for a specific state in the order flow.
"""

import os
import logging

import instructor
from openai import OpenAI

from ..schemas import (
    SideChoiceResponse,
    BagelChoiceResponse,
    MultiBagelChoiceResponse,
    MultiToastedResponse,
    MultiSpreadResponse,
    SpreadChoiceResponse,
    ToastedChoiceResponse,
    CoffeeSizeResponse,
    CoffeeStyleResponse,
    ByPoundCategoryResponse,
    DeliveryChoiceResponse,
    NameResponse,
    ConfirmationResponse,
    PaymentMethodResponse,
    EmailResponse,
    PhoneResponse,
    OpenInputResponse,
)
from .deterministic import (
    parse_open_input_deterministic,
    _parse_multi_item_order,
)

logger = logging.getLogger(__name__)


def get_instructor_client():
    """Get instructor-wrapped OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return instructor.from_openai(OpenAI(api_key=api_key))


def parse_side_choice(user_input: str, item_name: str, model: str = "gpt-4o-mini") -> SideChoiceResponse:
    """Parse user input when waiting for omelette side choice."""
    client = get_instructor_client()

    prompt = f"""The user ordered "{item_name}" which comes with a choice of bagel or fruit salad.
We asked: "Would you like a bagel or fruit salad with your {item_name}?"

The user said: "{user_input}"

Determine their choice. If they mention a specific bagel type (like "plain bagel", "everything"),
capture that too - it means they chose bagel AND specified the type.

Examples:
- "bagel" -> choice: "bagel"
- "plain bagel" -> choice: "bagel", bagel_type: "plain"
- "fruit salad" -> choice: "fruit_salad"
- "the fruit" -> choice: "fruit_salad"
- "everything bagel please" -> choice: "bagel", bagel_type: "everything"
"""

    return client.chat.completions.create(
        model=model,
        response_model=SideChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_bagel_choice(user_input: str, num_pending_bagels: int = 1, model: str = "gpt-4o-mini") -> BagelChoiceResponse:
    """Parse user input when waiting for bagel type."""
    client = get_instructor_client()

    prompt = f"""We asked the user "What kind of bagel?" for ONE specific bagel.
The user said: "{user_input}"

Extract the bagel type. Common types: plain, everything, sesame, poppy, onion, cinnamon raisin, pumpernickel, whole wheat, salt, garlic, bialy.

CRITICAL: quantity should be 1 UNLESS the user EXPLICITLY uses quantity words.
- Just a bagel type like "plain" or "everything" -> quantity: 1
- "2 of them plain" or "both plain" -> quantity: 2
- "all of them plain" or "all plain" -> quantity: {num_pending_bagels}

The user has {num_pending_bagels} bagel(s) remaining that need types, but we are asking about them ONE AT A TIME.
Only set quantity > 1 if the user EXPLICITLY says "both", "all", "2 of them", "two", "three", etc.

Examples:
- "plain" -> bagel_type: "plain", quantity: 1
- "everything" -> bagel_type: "everything", quantity: 1
- "sesame please" -> bagel_type: "sesame", quantity: 1
- "I'll do plain" -> bagel_type: "plain", quantity: 1
- "2 of them plain" -> bagel_type: "plain", quantity: 2
- "both plain" -> bagel_type: "plain", quantity: 2
- "all plain" -> bagel_type: "plain", quantity: {num_pending_bagels}
- "make them all everything" -> bagel_type: "everything", quantity: {num_pending_bagels}
"""

    return client.chat.completions.create(
        model=model,
        response_model=BagelChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_multi_bagel_choice(user_input: str, num_bagels: int, bagel_descriptions: list[str], model: str = "gpt-4o-mini") -> MultiBagelChoiceResponse:
    """Parse user input when waiting for multiple bagel types."""
    client = get_instructor_client()

    bagel_list = ", ".join(bagel_descriptions) if bagel_descriptions else f"{num_bagels} bagels"

    prompt = f"""We asked the user what kind of bagels they want for their {num_bagels} bagels.
The user said: "{user_input}"

Extract the bagel types. Common types: plain, everything, sesame, poppy, onion,
cinnamon raisin, pumpernickel, whole wheat, salt, garlic, bialy.

- If they specify different types, list them in bagel_types in order mentioned
- If all bagels are the same type (e.g., "both plain", "all everything"), set all_same_type

Examples:
- "one plain, one cinnamon raisin" -> bagel_types: ["plain", "cinnamon raisin"]
- "plain and everything" -> bagel_types: ["plain", "everything"]
- "both plain" -> all_same_type: "plain"
- "all everything" -> all_same_type: "everything"
- "the first one plain, second one sesame" -> bagel_types: ["plain", "sesame"]
"""

    return client.chat.completions.create(
        model=model,
        response_model=MultiBagelChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_multi_toasted(user_input: str, num_bagels: int, bagel_descriptions: list[str], model: str = "gpt-4o-mini") -> MultiToastedResponse:
    """Parse user input about toasting multiple bagels."""
    client = get_instructor_client()

    bagel_list = ", ".join(bagel_descriptions) if bagel_descriptions else f"{num_bagels} bagels"

    prompt = f"""We asked if the user wants their bagels toasted. They have: {bagel_list}
The user said: "{user_input}"

- If ALL bagels should be toasted (e.g., "yes", "both toasted"), set all_toasted=true
- If NONE should be toasted (e.g., "no", "not toasted"), set all_toasted=false
- If MIXED (e.g., "toast the plain one"), populate toasted_list with true/false for each bagel in order

Examples:
- "yes" -> all_toasted: true
- "both toasted" -> all_toasted: true
- "no thanks" -> all_toasted: false
- "toast the plain one" (for plain and cinnamon raisin) -> toasted_list: [true, false]
- "just the first one" -> toasted_list: [true, false]
"""

    return client.chat.completions.create(
        model=model,
        response_model=MultiToastedResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_multi_spread(user_input: str, num_bagels: int, bagel_descriptions: list[str], model: str = "gpt-4o-mini") -> MultiSpreadResponse:
    """Parse user input about spreads for multiple bagels."""
    client = get_instructor_client()

    bagel_list = ", ".join(bagel_descriptions) if bagel_descriptions else f"{num_bagels} bagels"

    prompt = f"""We asked what spread the user wants on their bagels. They have: {bagel_list}
The user said: "{user_input}"

Spread options: cream cheese, butter, none/nothing.
Cream cheese varieties: plain, scallion, veggie, lox spread, strawberry, etc.

- If ALL bagels get the same spread, set all_same_spread (and all_same_spread_type if specified)
- If DIFFERENT spreads, populate spreads list in order with dicts like {{"spread": "butter"}} or {{"spread": "cream cheese", "spread_type": "scallion"}}

Examples:
- "cream cheese on both" -> all_same_spread: "cream cheese"
- "butter" -> all_same_spread: "butter"
- "butter on the plain, cream cheese on the other" -> spreads: [{{"spread": "butter"}}, {{"spread": "cream cheese"}}]
- "scallion cream cheese on the first, strawberry on the second" -> spreads: [{{"spread": "cream cheese", "spread_type": "scallion"}}, {{"spread": "cream cheese", "spread_type": "strawberry"}}]
"""

    return client.chat.completions.create(
        model=model,
        response_model=MultiSpreadResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_spread_choice(user_input: str, model: str = "gpt-4o-mini") -> SpreadChoiceResponse:
    """Parse user input when waiting for spread choice."""
    client = get_instructor_client()

    prompt = f"""We asked the user what spread they want on their bagel.
The user said: "{user_input}"

Extract their spread choice. Options: cream cheese, butter, none/nothing.
Cream cheese varieties: plain, scallion, veggie, lox spread, etc.

Also extract any special instructions about quantity or application into special_instructions.
These are modifiers like: "a little", "extra", "light", "heavy", "on the side", "not too much", "lots of", etc.

Examples:
- "cream cheese" -> spread: "cream cheese"
- "scallion cream cheese" -> spread: "cream cheese", spread_type: "scallion"
- "butter" -> spread: "butter"
- "nothing" or "plain" or "no spread" -> no_spread: true
- "a little cream cheese" -> spread: "cream cheese", special_instructions: "a little"
- "extra butter" -> spread: "butter", special_instructions: "extra"
- "light on the scallion cream cheese" -> spread: "cream cheese", spread_type: "scallion", special_instructions: "light"
- "cream cheese on the side" -> spread: "cream cheese", special_instructions: "on the side"
"""

    return client.chat.completions.create(
        model=model,
        response_model=SpreadChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_toasted_choice(user_input: str, model: str = "gpt-4o-mini") -> ToastedChoiceResponse:
    """Parse user input when waiting for toasted preference."""
    client = get_instructor_client()

    prompt = f"""We asked the user if they want their bagel toasted.
The user said: "{user_input}"

Examples:
- "yes" / "toasted" / "please" -> toasted: true
- "no" / "not toasted" / "no thanks" -> toasted: false
"""

    return client.chat.completions.create(
        model=model,
        response_model=ToastedChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_coffee_size(user_input: str, model: str = "gpt-4o-mini") -> CoffeeSizeResponse:
    """Parse user input when waiting for coffee size."""
    client = get_instructor_client()

    prompt = f"""We asked the user what size coffee they want.
The user said: "{user_input}"

Examples:
- "small" / "a small" -> size: "small"
- "regular" -> size: null (ask for size - only small or large available)
- "large" / "a large one" -> size: "large"
- Any unclear response -> size: null
"""

    return client.chat.completions.create(
        model=model,
        response_model=CoffeeSizeResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_coffee_style(user_input: str, model: str = "gpt-4o-mini") -> CoffeeStyleResponse:
    """Parse user input when waiting for hot/iced preference."""
    client = get_instructor_client()

    prompt = f"""We asked the user if they want their coffee hot or iced.
The user said: "{user_input}"

Examples:
- "iced" / "cold" / "iced please" -> iced: true
- "hot" / "regular" / "warm" -> iced: false
- Any unclear response -> iced: null
"""

    return client.chat.completions.create(
        model=model,
        response_model=CoffeeStyleResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_by_pound_category(user_input: str, model: str = "gpt-4o-mini") -> ByPoundCategoryResponse:
    """Parse user input when they're selecting a by-the-pound category or item."""
    client = get_instructor_client()

    prompt = f"""We asked the user which by-the-pound category they're interested in.
We sell cheeses, spreads, cold cuts, fish, and salads by the pound.

The user said: "{user_input}"

Categories:
- "cheese" - if they mention cheese, cheeses
- "spread" - if they mention spread, spreads, cream cheese (by the pound)
- "cold_cut" - if they mention cold cuts, deli meats, turkey, ham, pastrami, corned beef
- "fish" - if they mention fish, lox, salmon, smoked fish, nova, sable, whitefish
- "salad" - if they mention salad, salads, tuna salad, egg salad, chicken salad

If user mentions a specific item they want to order (e.g., "I'll take the muenster" or "half pound of nova"),
set wants_to_order to that item name.

Examples:
- "cheeses" / "the cheese" / "I'm interested in cheese" -> category: "cheese"
- "what cheese do you sell" / "what cheeses do you have by the pound" -> category: "cheese"
- "spreads" / "cream cheese by the pound" -> category: "spread"
- "cold cuts" / "deli meats" -> category: "cold_cut"
- "what cold cuts do you sell by the pound" / "what deli meats" -> category: "cold_cut"
- "fish" / "smoked fish" / "the lox" -> category: "fish"
- "what fish do you have" / "what smoked fish do you sell" -> category: "fish"
- "salads" / "what salads" -> category: "salad"
- "I'll take a half pound of nova" -> category: "fish", wants_to_order: "nova"
- "the muenster please" -> category: "cheese", wants_to_order: "muenster"
- "never mind" / "nothing" / "I'm good" -> category: null, unclear: false (they're declining)
- Any unclear response -> unclear: true
"""

    return client.chat.completions.create(
        model=model,
        response_model=ByPoundCategoryResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_open_input(user_input: str, context: str = "", model: str = "gpt-4o-mini", spread_types: set[str] | None = None) -> OpenInputResponse:
    """Parse user input when open for new orders.

    Tries deterministic parsing first for speed and consistency.
    Falls back to LLM for complex orders (menu items, multi-config bagels, coffee).

    Args:
        user_input: The user's input string
        context: Optional context string for LLM fallback
        model: Model to use for LLM fallback
        spread_types: Optional set of spread type keywords from database
    """
    # Check if input likely contains multiple items
    input_lower = user_input.lower()
    # Clean up common phrases that contain "and" but aren't multi-item orders
    # Order matters: longer phrases first to match properly
    cleaned = input_lower
    for phrase in [
        # Egg sandwich phrases (must come first - longer phrases)
        "bacon egg and cheese", "ham egg and cheese", "sausage egg and cheese",
        "bacon and egg and cheese", "ham and egg and cheese",
        "bacon eggs and cheese", "ham eggs and cheese", "egg and cheese",
        "egg cheese and bacon", "egg, cheese and bacon",
        # Other compound phrases
        "ham and cheese", "ham and egg", "bacon and egg", "egg and bacon",
        "lox and cream cheese", "salt and pepper", "cream cheese and lox",
        "eggs and bacon", "black and white", "spinach and feta",
    ]:
        cleaned = cleaned.replace(phrase, "")

    # If "and" or comma still appears, try multi-item deterministic parsing first
    if " and " in cleaned or ", " in cleaned:
        logger.info("Multi-item order detected, trying deterministic parse: %s", user_input[:50])
        result = _parse_multi_item_order(user_input)
        if result is not None:
            logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
            return result

    # Try deterministic parsing for single-item orders
    result = parse_open_input_deterministic(user_input, spread_types=spread_types)
    if result is not None:
        logger.info("Parsed deterministically: %s", user_input[:50])
        return result

    # Fall back to LLM for complex cases
    logger.info("Falling back to LLM for: %s", user_input[:50])
    client = get_instructor_client()

    prompt = f"""Parse this customer message at a bagel shop.
{f"Context: {context}" if context else ""}

The user said: "{user_input}"

Determine what they want:
- If ordering a SPEED MENU BAGEL (The Classic, The Leo, The Traditional, The Max Zucker,
  The Classic BEC, The Avocado Toast, The Chelsea Club, The Flatiron Traditional,
  The Old School Tuna Sandwich), use new_speed_menu_bagel fields (see examples below)
- If ordering a different menu item by name (e.g., "the chipotle egg omelette", omelettes, sandwiches),
  set new_menu_item to the item name and new_menu_item_quantity to the number ordered
- If ordering bagels:
  - Set new_bagel=true
  - Set new_bagel_quantity to the number of bagels (default 1)
  - If ALL bagels are the same, use new_bagel_type, new_bagel_toasted, new_bagel_spread, new_bagel_spread_type
  - If bagels have DIFFERENT configurations, populate parsed_items list with ParsedBagelEntry objects: {{"type": "bagel", "bagel_type": "...", "toasted": true/false/null, "spread": "...", "spread_type": "..."}}
- If ordering coffee/drink (IMPORTANT: latte, cappuccino, espresso, americano, macchiato, mocha, drip coffee, cold brew, tea, and similar beverages are ALWAYS coffee orders - use new_coffee fields, NOT new_menu_item):
  - Set new_coffee=true
  - Set new_coffee_quantity to the number of drinks (e.g., "3 diet cokes" -> 3, "two coffees" -> 2, default 1)
  - Set new_coffee_type if specified (e.g., "latte", "cappuccino", "drip coffee", "diet coke", "coke")
  - Set new_coffee_size if specified ("small", "large") - note: size may not be specified initially
  - Set new_coffee_iced=true if they want iced, false if they want hot, null if not specified
  - Set new_coffee_milk if specified (e.g., "oat", "almond", "skim", "whole"). "black" means no milk. If they just say "with milk" without specifying type, use "whole".
  - Set new_coffee_sweetener if specified (e.g., "sugar", "splenda", "stevia", "equal")
  - Set new_coffee_sweetener_quantity for number of sweeteners (e.g., "two sugars" = 2, "2 splenda" = 2)
  - Set new_coffee_flavor_syrup if specified (e.g., "vanilla", "caramel", "hazelnut")
  - Set new_coffee_notes for special instructions like "a splash of milk", "extra hot", "light ice"
- If they're done ordering ("that's all", "nothing else", "no", "nope", "I'm good"), set done_ordering=true
- If they want to repeat their previous order ("repeat my order", "same as last time", "my usual", "same thing again"), set wants_repeat_order=true
- If just greeting ("hi", "hello"), set is_greeting=true
- If user mentions order type upfront ("pickup order", "delivery order", "I'd like to place a pickup", "this is for delivery"), set order_type to "pickup" or "delivery"
  - "I'd like to place a pickup order" -> order_type: "pickup"
  - "I want to place a delivery order" -> order_type: "delivery"
  - "pickup order please" -> order_type: "pickup"
  - "this is for pickup" -> order_type: "pickup"
  - Can be combined with items: "pickup order, I'll have a plain bagel" -> order_type: "pickup", new_bagel: true, new_bagel_type: "plain"

IMPORTANT: When parsing quantities, recognize both spelled-out words AND numeric digits:
- "two" / "2" = 2
- "three" / "3" = 3
- "four" / "4" = 4
- "five" / "5" = 5

Examples:
- "can I get the chipotle egg omelette" -> new_menu_item: "The Chipotle Egg Omelette", new_menu_item_quantity: 1
- "3 tuna salad sandwiches" -> new_menu_item: "Tuna Salad Sandwich", new_menu_item_quantity: 3
- "two western omelettes" -> new_menu_item: "Western Omelette", new_menu_item_quantity: 2
- "ham egg and cheese on wheat toasted" -> new_menu_item: "Ham Egg & Cheese on Wheat", new_menu_item_quantity: 1, new_menu_item_toasted: true
- "I'd like a plain bagel" -> new_bagel: true, new_bagel_quantity: 1, new_bagel_type: "plain"
- "two bagels please" -> new_bagel: true, new_bagel_quantity: 2
- "three bagels" -> new_bagel: true, new_bagel_quantity: 3
- "I want three bagels" -> new_bagel: true, new_bagel_quantity: 3
- "3 bagels please" -> new_bagel: true, new_bagel_quantity: 3
- "four bagels" -> new_bagel: true, new_bagel_quantity: 4
- "I'd like 5 bagels" -> new_bagel: true, new_bagel_quantity: 5
- "two plain bagels toasted" -> new_bagel: true, new_bagel_quantity: 2, new_bagel_type: "plain", new_bagel_toasted: true
- "one plain bagel and one everything bagel" -> new_bagel: true, new_bagel_quantity: 2, parsed_items: [{{"type": "bagel", "bagel_type": "plain"}}, {{"type": "bagel", "bagel_type": "everything"}}]
- "plain bagel with butter and cinnamon raisin with cream cheese" -> new_bagel: true, new_bagel_quantity: 2, parsed_items: [{{"type": "bagel", "bagel_type": "plain", "spread": "butter"}}, {{"type": "bagel", "bagel_type": "cinnamon raisin", "spread": "cream cheese"}}]
- "two everything bagels with scallion cream cheese toasted" -> new_bagel: true, new_bagel_quantity: 2, new_bagel_type: "everything", new_bagel_toasted: true, new_bagel_spread: "cream cheese", new_bagel_spread_type: "scallion"
- "coffee please" -> new_coffee: true
- "a large latte" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "large"
- "large iced coffee" -> new_coffee: true, new_coffee_size: "large", new_coffee_iced: true
- "small hot latte" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "small", new_coffee_iced: false
- "iced cappuccino" -> new_coffee: true, new_coffee_type: "cappuccino", new_coffee_iced: true
- "small coffee black with two sugars" -> new_coffee: true, new_coffee_size: "small", new_coffee_milk: "none", new_coffee_sweetener: "sugar", new_coffee_sweetener_quantity: 2
- "large latte with oat milk" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "large", new_coffee_milk: "oat"
- "coffee with milk" -> new_coffee: true, new_coffee_milk: "whole"
- "small coffee with a splash of milk" -> new_coffee: true, new_coffee_size: "small", new_coffee_milk: "whole", new_coffee_notes: "a splash of milk"
- "latte extra hot" -> new_coffee: true, new_coffee_type: "latte", new_coffee_notes: "extra hot"
- "iced coffee light ice" -> new_coffee: true, new_coffee_iced: true, new_coffee_notes: "light ice"
- "large coffee with vanilla syrup" -> new_coffee: true, new_coffee_size: "large", new_coffee_flavor_syrup: "vanilla"
- "coffee with 2 hazelnut syrups" -> new_coffee: true, new_coffee_flavor_syrup: "hazelnut", new_coffee_syrup_quantity: 2
- "large iced coffee with double vanilla" -> new_coffee: true, new_coffee_size: "large", new_coffee_iced: true, new_coffee_flavor_syrup: "vanilla", new_coffee_syrup_quantity: 2
- "latte with triple caramel syrup" -> new_coffee: true, new_coffee_type: "latte", new_coffee_flavor_syrup: "caramel", new_coffee_syrup_quantity: 3
- "small coffee black with two sugars and vanilla syrup" -> new_coffee: true, new_coffee_size: "small", new_coffee_milk: "none", new_coffee_sweetener: "sugar", new_coffee_sweetener_quantity: 2, new_coffee_flavor_syrup: "vanilla"
- "iced latte with almond milk and caramel" -> new_coffee: true, new_coffee_type: "latte", new_coffee_iced: true, new_coffee_milk: "almond", new_coffee_flavor_syrup: "caramel"
- "cappuccino with 2 splenda and vanilla syrup" -> new_coffee: true, new_coffee_type: "cappuccino", new_coffee_sweetener: "splenda", new_coffee_sweetener_quantity: 2, new_coffee_flavor_syrup: "vanilla"
- "latte with oat milk" -> new_coffee: true, new_coffee_type: "latte", new_coffee_milk: "oat"
- "espresso with sugar" -> new_coffee: true, new_coffee_type: "espresso", new_coffee_sweetener: "sugar", new_coffee_sweetener_quantity: 1
- "cappuccino" -> new_coffee: true, new_coffee_type: "cappuccino"
- "mocha with whipped cream" -> new_coffee: true, new_coffee_type: "mocha"

Side orders (IMPORTANT - these are SEPARATE items, not toppings on bagels!):
- When user says "side of X", "with a side of X", or orders a side item -> set new_side_item
- Available sides: Side of Sausage, Side of Bacon, Side of Turkey Bacon, Side of Ham, Side of Chicken Sausage, Side of Breakfast Latke, Hard Boiled Egg
- CRITICAL: If user says "side of" anything, it is a SIDE ITEM, NOT a bagel topping. Do NOT add it to bagel modifiers!
- "side of sausage" -> new_side_item: "Side of Sausage"
- "side of turkey sausage" -> new_side_item: "Side of Sausage" (map to closest available item)
- "with a side of bacon" -> new_side_item: "Side of Bacon"
- "side of turkey bacon" -> new_side_item: "Side of Turkey Bacon"
- "bagel with a side of sausage" -> new_bagel: true, new_side_item: "Side of Sausage" (TWO separate items!)
- "everything bagel and a side of bacon" -> new_bagel: true, new_bagel_type: "everything", new_side_item: "Side of Bacon"
- DO NOT add sausage/bacon/ham as bagel toppings when user says "side of" - these are separate menu items!
- "3 diet cokes" -> new_coffee: true, new_coffee_type: "diet coke", new_coffee_quantity: 3
- "two coffees" -> new_coffee: true, new_coffee_quantity: 2
- "three lattes" -> new_coffee: true, new_coffee_type: "latte", new_coffee_quantity: 3
- "2 iced coffees" -> new_coffee: true, new_coffee_iced: true, new_coffee_quantity: 2
- "a coke" -> new_coffee: true, new_coffee_type: "coke", new_coffee_quantity: 1
- "that's all" -> done_ordering: true
- "repeat my order" -> wants_repeat_order: true
- "same as last time" -> wants_repeat_order: true
- "my usual" -> wants_repeat_order: true

Speed menu bagel orders (pre-configured sandwiches):
- These are specific named menu items that come pre-configured: "The Classic", "The Classic BEC",
  "The Traditional", "The Leo", "The Max Zucker", "The Avocado Toast", "The Chelsea Club",
  "The Flatiron Traditional", "The Old School Tuna Sandwich"
- "bacon egg and cheese" / "BEC" / "bacon egg cheese" are ALL "The Classic BEC"
- "ham egg and cheese" / "HEC" are The Classic with ham instead of bacon
- When user orders these by name, set new_speed_menu_bagel=true and new_speed_menu_bagel_name to the item name
- "3 Classics" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic", new_speed_menu_bagel_quantity: 3
- "The Leo please" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Leo"
- "two Traditionals toasted" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Traditional", new_speed_menu_bagel_quantity: 2, new_speed_menu_bagel_toasted: true
- "a Max Zucker" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Max Zucker"
- "Classic BEC" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC"
- "bacon egg and cheese bagel" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC" (DO NOT set bagel_choice to "egg" - the "egg" is part of the item name, not the bagel type!)
- "bacon egg and cheese on everything" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC", new_speed_menu_bagel_bagel_choice: "everything"
- "ham egg and cheese bagel" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC" (ham variant, but map to BEC)
- "the avocado toast" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Avocado Toast"
- "Chelsea Club toasted" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Chelsea Club", new_speed_menu_bagel_toasted: true

MULTI-ITEM ORDERS (IMPORTANT - extract ALL items!):
- When user orders MULTIPLE different items in one message, you MUST extract ALL of them
- If ordering a sandwich/menu item AND a drink together, set BOTH new_menu_item AND new_coffee fields
- "The Lexington and an orange juice" -> new_menu_item: "The Lexington", new_coffee: true, new_coffee_type: "orange juice"
- "Classic BEC with a coffee" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC", new_coffee: true, new_coffee_type: "coffee"
- "Delancey and a latte" -> new_menu_item: "The Delancey", new_coffee: true, new_coffee_type: "latte"
- "two bagels and a coffee" -> new_bagel: true, new_bagel_quantity: 2, new_coffee: true, new_coffee_type: "coffee"
- "plain bagel and orange juice" -> new_bagel: true, new_bagel_type: "plain", new_coffee: true, new_coffee_type: "orange juice"

Menu queries (asking what items are available):
- If user asks "what X do you have?" where X is a type of menu item -> menu_query: true, menu_query_type: "<type>"
  - "what sodas do you have" -> menu_query: true, menu_query_type: "soda"
  - "what juices do you have" -> menu_query: true, menu_query_type: "juice"
  - "what drinks do you have" -> menu_query: true, menu_query_type: "drink"
  - "what beverages do you have" -> menu_query: true, menu_query_type: "beverage"
  - "what coffees do you have" -> menu_query: true, menu_query_type: "coffee"
  - "what teas do you have" -> menu_query: true, menu_query_type: "tea"
  - "what bagels do you have" -> menu_query: true, menu_query_type: "bagel"
  - "what egg sandwiches do you have" -> menu_query: true, menu_query_type: "egg_sandwich"
  - "what fish sandwiches do you have" -> menu_query: true, menu_query_type: "fish_sandwich"
  - "what sandwiches do you have" -> menu_query: true, menu_query_type: "sandwich"
  - "what spread sandwiches do you have" -> menu_query: true, menu_query_type: "spread_sandwich"
  - "what are your spread sandwiches" -> menu_query: true, menu_query_type: "spread_sandwich"
  - "what salad sandwiches do you have" -> menu_query: true, menu_query_type: "salad_sandwich"
  - "what are your salad sandwiches" -> menu_query: true, menu_query_type: "salad_sandwich"
  - "what omelettes do you have" -> menu_query: true, menu_query_type: "omelette"
  - "what sides do you have" -> menu_query: true, menu_query_type: "side"
  - "what snacks do you have" -> menu_query: true, menu_query_type: "snack"
- Do NOT use asking_signature_menu for general menu queries - only for signature/speed menu items

Signature/Speed menu inquiries:
- If user asks about signature items, speed menu, or pre-made options -> asking_signature_menu: true
- Also set signature_menu_type to the specific type if mentioned:
  - "what are your signature sandwiches" -> asking_signature_menu: true, signature_menu_type: "signature_sandwich"
  - "what signature sandwiches do you have" -> asking_signature_menu: true, signature_menu_type: "signature_sandwich"
  - "what are your speed menu bagels" -> asking_signature_menu: true, signature_menu_type: "speed_menu_bagel"
  - "what speed menu options do you have" -> asking_signature_menu: true (no specific type)
  - "what signature bagels do you have" -> asking_signature_menu: true, signature_menu_type: "speed_menu_bagel"
  - "what are the signature items" -> asking_signature_menu: true (no specific type)
  - "tell me about the speed menu" -> asking_signature_menu: true (no specific type)
  - "what pre-made bagels do you have" -> asking_signature_menu: true, signature_menu_type: "speed_menu_bagel"

By-the-pound inquiries:
- If user asks "what do you sell by the pound" or "do you have anything by the pound" -> asking_by_pound: true
- If user asks about a specific category by the pound, also set by_pound_category:
  - "what cheeses do you have" or "I'm interested in cheese" -> asking_by_pound: true, by_pound_category: "cheese"
  - "what spreads do you have" / "what cream cheese do you have" / "what cream cheese types do you have" / "what cream cheese flavors do you have" / "what kind of cream cheese" -> asking_by_pound: true, by_pound_category: "spread"
  - "what cold cuts do you have" -> asking_by_pound: true, by_pound_category: "cold_cut"
  - "what fish do you sell" or "what smoked fish" -> asking_by_pound: true, by_pound_category: "fish"
  - "what salads do you have by the pound" -> asking_by_pound: true, by_pound_category: "salad"

By-the-pound ORDERS (user is ordering, not asking):
- If user orders items by the pound, populate by_pound_items list with each item:
  - "give me a pound of Muenster" -> by_pound_items: [{{"item_name": "Muenster", "quantity": "1 lb", "category": "cheese"}}]
  - "a pound of Muenster and a pound of Provolone" -> by_pound_items: [{{"item_name": "Muenster", "quantity": "1 lb", "category": "cheese"}}, {{"item_name": "Provolone", "quantity": "1 lb", "category": "cheese"}}]
  - "half pound of nova" -> by_pound_items: [{{"item_name": "Nova", "quantity": "half lb", "category": "fish"}}]
  - "two pounds of turkey" -> by_pound_items: [{{"item_name": "Turkey", "quantity": "2 lbs", "category": "cold_cut"}}]
  - "I'll take the muenster and the swiss" -> by_pound_items: [{{"item_name": "Muenster", "quantity": "1 lb", "category": "cheese"}}, {{"item_name": "Swiss", "quantity": "1 lb", "category": "cheese"}}]
  - "give me a pound of tuna salad" -> by_pound_items: [{{"item_name": "Tuna Salad", "quantity": "1 lb", "category": "salad"}}]
  - "a quarter pound of lox" -> by_pound_items: [{{"item_name": "Lox", "quantity": "quarter lb", "category": "fish"}}]
"""

    return client.chat.completions.create(
        model=model,
        response_model=OpenInputResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_delivery_choice(user_input: str, model: str = "gpt-4o-mini") -> DeliveryChoiceResponse:
    """Parse user input when waiting for pickup/delivery choice."""
    client = get_instructor_client()

    prompt = f"""We asked the user if their order is for pickup or delivery.
The user said: "{user_input}"

Examples:
- "pickup" / "pick up" / "I'll pick it up" -> choice: "pickup"
- "delivery" / "deliver" / "delivered" -> choice: "delivery"
- "delivery to 123 Main St" -> choice: "delivery", address: "123 Main St"
"""

    return client.chat.completions.create(
        model=model,
        response_model=DeliveryChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_name(user_input: str, model: str = "gpt-4o-mini") -> NameResponse:
    """Parse user input when waiting for name."""
    client = get_instructor_client()

    prompt = f"""We asked the user for their name for the order.
The user said: "{user_input}"

Extract just the name. Examples:
- "John" -> name: "John"
- "It's Sarah" -> name: "Sarah"
- "My name is Mike" -> name: "Mike"
"""

    return client.chat.completions.create(
        model=model,
        response_model=NameResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_confirmation(user_input: str, model: str = "gpt-4o-mini") -> ConfirmationResponse:
    """Parse user input when waiting for order confirmation."""
    client = get_instructor_client()

    prompt = f"""We showed the user their order summary and asked if it looks right.
The user said: "{user_input}"

Examples:
- "yes" / "looks good" / "correct" / "perfect" -> confirmed: true
- "no" / "wait" / "change" / "actually" -> wants_changes: true
"""

    return client.chat.completions.create(
        model=model,
        response_model=ConfirmationResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_payment_method(user_input: str, model: str = "gpt-4o-mini") -> PaymentMethodResponse:
    """Parse user input when asking how to send order details."""
    client = get_instructor_client()

    prompt = f"""We asked the user for a phone number or email to send the order confirmation.
The user said: "{user_input}"

Examples:
- "text" / "text me" / "sms" -> choice: "text"
- "email" / "email me" / "send me an email" -> choice: "email"
- "text me at 555-1234" -> choice: "text", phone_number: "555-1234"
- "555-123-4567" -> choice: "text", phone_number: "555-123-4567"
- "email it to john@example.com" -> choice: "email", email_address: "john@example.com"
- "john@example.com" -> choice: "email", email_address: "john@example.com"
"""

    return client.chat.completions.create(
        model=model,
        response_model=PaymentMethodResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_email(user_input: str, model: str = "gpt-4o-mini") -> EmailResponse:
    """Parse user input when collecting email address."""
    client = get_instructor_client()

    prompt = f"""We asked the user for their email address.
The user said: "{user_input}"

Extract the email address from their response.
Examples:
- "john@example.com" -> email: "john@example.com"
- "it's john at gmail dot com" -> email: "john@gmail.com"
- "my email is test.user@company.org" -> email: "test.user@company.org"
"""

    return client.chat.completions.create(
        model=model,
        response_model=EmailResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_phone(user_input: str, model: str = "gpt-4o-mini") -> PhoneResponse:
    """Parse user input when collecting phone number."""
    client = get_instructor_client()

    prompt = f"""We asked the user for their phone number to text order confirmation.
The user said: "{user_input}"

Extract the phone number from their response. Return just the digits (10 digits for US numbers).
Examples:
- "555-123-4567" -> phone: "5551234567"
- "it's 732 555 1234" -> phone: "7325551234"
- "(908) 555-9999" -> phone: "9085559999"
- "my number is 201.555.0000" -> phone: "2015550000"
"""

    return client.chat.completions.create(
        model=model,
        response_model=PhoneResponse,
        messages=[{"role": "user", "content": prompt}],
    )
