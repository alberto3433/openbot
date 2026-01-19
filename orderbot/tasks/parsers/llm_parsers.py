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
    ConfirmationResponse,
    DeliveryChoiceResponse,
    EmailResponse,
    NameResponse,
    OpenInputResponse,
    PaymentMethodResponse,
    PhoneResponse,
    SideChoiceResponse,
)
from .deterministic import (
    parse_open_input_deterministic,
    _parse_multi_item_order,
    _parse_configurable_item,
)

logger = logging.getLogger(__name__)


def get_instructor_client():
    """Get instructor-wrapped OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return instructor.from_openai(OpenAI(api_key=api_key))


def parse_side_choice(
    user_input: str,
    item_name: str,
    valid_options: list[dict] | None = None,
    question_text: str | None = None,
    model: str = "gpt-4o-mini",
) -> SideChoiceResponse:
    """Parse user input when waiting for side choice selection.

    This is a generic, data-driven parser that works with any side choice options
    loaded from the database. It only determines which option was chosen - any
    further configuration of the chosen option is handled by standard item
    configuration handlers.

    Args:
        user_input: The user's response
        item_name: The parent item name (e.g., "Western Omelette")
        valid_options: List of option dicts from DB with keys:
            - slug: option identifier (e.g., "bagel", "fruit_salad")
            - display_name: human-readable name (e.g., "Bagel", "Fruit Salad")
            - aliases: optional list of alternative names
        question_text: The question that was asked (for context in prompt)
        model: OpenAI model to use

    Returns:
        SideChoiceResponse with:
            - value: the chosen option slug (or "unclear" if not determined)
            - wants_cancel: True if user wants to cancel the item
    """
    client = get_instructor_client()

    # Build options description from database data
    if valid_options:
        options_list = []
        for opt in valid_options:
            slug = opt.get("slug", "")
            display = opt.get("display_name", slug)
            aliases = opt.get("aliases", [])
            if aliases:
                alias_str = ", ".join(aliases[:3])  # Limit to 3 aliases
                options_list.append(f"- {display} (slug: {slug}, also known as: {alias_str})")
            else:
                options_list.append(f"- {display} (slug: {slug})")
        options_desc = "\n".join(options_list)
    else:
        options_desc = "- (options not specified)"

    # Use provided question or build generic one
    if not question_text:
        question_text = f"Would you like a side with your {item_name}?"

    prompt = f"""The user ordered "{item_name}" which comes with a choice of side.
We asked: "{question_text}"

Available options:
{options_desc}

The user said: "{user_input}"

Determine which option they chose. Return the slug of the chosen option.
If the user wants to cancel or remove the item, set wants_cancel to true.
If you cannot determine their choice, set value to "unclear".

IMPORTANT: Only return the option slug - do NOT try to extract additional details
like specific types or modifications. Those will be asked separately.
"""

    return client.chat.completions.create(
        model=model,
        response_model=SideChoiceResponse,
        messages=[{"role": "user", "content": prompt}],
    )


def parse_open_input(
    user_input: str,
    context: str = "",
    model: str = "gpt-4o-mini",
    modifier_category_keywords: dict[str, str] | None = None,
    modifier_item_keywords: dict[str, str] | None = None,
    ingredient_to_items: dict[str, list[dict]] | None = None,
) -> OpenInputResponse:
    """Parse user input when open for new orders.

    Tries deterministic parsing first for speed and consistency.
    Falls back to LLM for complex orders (menu items, multi-config bagels, coffee).

    Spread options are loaded from the database cache.

    Args:
        user_input: The user's input string
        context: Optional context string for LLM fallback
        model: Model to use for LLM fallback
        modifier_category_keywords: Mapping of keywords to category slugs
            (e.g., {"sweetener": "sweeteners", "sugar": "sweeteners"})
        modifier_item_keywords: Mapping of item keywords to item type slugs
            (e.g., {"latte": "coffee", "cappuccino": "coffee"})
        ingredient_to_items: Mapping of ingredient names to menu items containing them
            (e.g., {"chicken": [{"name": "Chicken Salad Sandwich", ...}]})
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

    # If "and" or comma still appears, it might be multi-item OR a single bagel with multiple modifiers
    # Pattern: "bagel with X, Y, and Z" is a single bagel with modifiers, NOT multi-item
    if " and " in cleaned or ", " in cleaned:
        # Check if this looks like a multi-item order with a coffee/drink BEFORE the bagel
        # e.g., "large iced oat milk latte with vanilla and a gluten free everything bagel"
        # In this case, the " with " comes from "latte with vanilla", not "bagel with modifiers"
        coffee_keywords = [
            "latte", "cappuccino", "espresso", "americano", "macchiato", "mocha",
            "coffee", "cold brew", "iced coffee", "drip", "tea", "chai",
            "coke", "coca-cola", "diet coke", "sprite", "soda", "juice",
            "chocolate milk", "milk", "water", "lemonade",
        ]

        # Check if there's a coffee keyword before " and a " or " and an " that precedes "bagel"
        is_multi_item_with_drink_first = False
        bagel_pos = input_lower.find("bagel")
        if bagel_pos > 0:
            # Look for " and a " or " and an " before the bagel
            text_before_bagel = input_lower[:bagel_pos]
            for separator in [" and a ", " and an ", " plus a ", " plus an ", ", a ", ", an "]:
                sep_pos = text_before_bagel.find(separator)
                if sep_pos > 0:
                    # Check if there's a coffee keyword before this separator
                    text_before_sep = text_before_bagel[:sep_pos]
                    for keyword in coffee_keywords:
                        if keyword in text_before_sep:
                            is_multi_item_with_drink_first = True
                            logger.info(
                                "Detected multi-item with drink ('%s') before bagel: %s",
                                keyword, user_input[:50]
                            )
                            break
                    if is_multi_item_with_drink_first:
                        break

        # Check for configurable item patterns first (bagels, coffees, etc.)
        # e.g., "plain bagel with Egg Whites, Swiss, and Spinach", "large iced latte"
        # But SKIP this if we detected a drink keyword before the bagel (multi-item order)
        if not is_multi_item_with_drink_first:
            logger.info("Trying configurable item pattern: %s", user_input[:50])
            result = _parse_configurable_item(user_input)
            if result is not None:
                logger.info("Parsed configurable item: %s", user_input[:50])
                return result

        # Otherwise try multi-item deterministic parsing
        logger.info("Multi-item order detected, trying deterministic parse: %s", user_input[:50])
        result = _parse_multi_item_order(user_input)
        if result is not None:
            logger.info("Parsed multi-item order deterministically: %s", user_input[:50])
            return result

    # Try deterministic parsing for single-item orders
    result = parse_open_input_deterministic(
        user_input,
        modifier_category_keywords=modifier_category_keywords,
        modifier_item_keywords=modifier_item_keywords,
        ingredient_to_items=ingredient_to_items,
    )
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
- If ordering a SIGNATURE ITEM (The Classic, The Leo, The Traditional, The Max Zucker,
  The Classic BEC, The Avocado Toast, The Chelsea Club, The Flatiron Traditional,
  The Old School Tuna Sandwich), use new_signature_item fields (see examples below)
- If ordering a different menu item by name (e.g., "the chipotle egg omelette", omelettes, sandwiches),
  set new_menu_item to the item name and new_menu_item_quantity to the number ordered
- If ordering bagels:
  - Set new_bagel=true
  - Set new_bagel_quantity to the number of bagels (default 1)
  - If ALL bagels are the same, use new_bagel_type, new_bagel_toasted, new_bagel_spread (atomic slug like "scallion_cream_cheese")
  - If bagels have DIFFERENT configurations, populate parsed_items list with ParsedItemEntry objects: {{"item_type": "bagel", "attribute_values": {{"bread": "...", "toasted": true/false/null, "spread": "..."}}}}
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
- "two everything bagels with scallion cream cheese toasted" -> new_bagel: true, new_bagel_quantity: 2, new_bagel_type: "everything", new_bagel_toasted: true, new_bagel_spread: "scallion_cream_cheese"
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

Signature item orders (pre-configured sandwiches):
- These are specific named menu items that come pre-configured: "The Classic", "The Classic BEC",
  "The Traditional", "The Leo", "The Max Zucker", "The Avocado Toast", "The Chelsea Club",
  "The Flatiron Traditional", "The Old School Tuna Sandwich"
- "bacon egg and cheese" / "BEC" / "bacon egg cheese" are ALL "The Classic BEC"
- "ham egg and cheese" / "HEC" are The Classic with ham instead of bacon
- When user orders these by name, set new_signature_item=true and new_signature_item_name to the item name
- "3 Classics" -> new_signature_item: true, new_signature_item_name: "The Classic", new_signature_item_quantity: 3
- "The Leo please" -> new_signature_item: true, new_signature_item_name: "The Leo"
- "two Traditionals toasted" -> new_signature_item: true, new_signature_item_name: "The Traditional", new_signature_item_quantity: 2, new_signature_item_toasted: true
- "a Max Zucker" -> new_signature_item: true, new_signature_item_name: "The Max Zucker"
- "Classic BEC" -> new_signature_item: true, new_signature_item_name: "The Classic BEC"
- "bacon egg and cheese bagel" -> new_signature_item: true, new_signature_item_name: "The Classic BEC" (DO NOT set bagel_choice to "egg" - the "egg" is part of the item name, not the bagel type!)
- "bacon egg and cheese on everything" -> new_signature_item: true, new_signature_item_name: "The Classic BEC", new_signature_item_bagel_choice: "everything"
- "ham egg and cheese bagel" -> new_signature_item: true, new_signature_item_name: "The Classic BEC" (ham variant, but map to BEC)
- "the avocado toast" -> new_signature_item: true, new_signature_item_name: "The Avocado Toast"
- "Chelsea Club toasted" -> new_signature_item: true, new_signature_item_name: "The Chelsea Club", new_signature_item_toasted: true

MULTI-ITEM ORDERS (IMPORTANT - extract ALL items!):
- When user orders MULTIPLE different items in one message, you MUST extract ALL of them
- If ordering a sandwich/menu item AND a drink together, set BOTH new_menu_item AND new_coffee fields
- "The Lexington and an orange juice" -> new_menu_item: "The Lexington", new_coffee: true, new_coffee_type: "orange juice"
- "Classic BEC with a coffee" -> new_signature_item: true, new_signature_item_name: "The Classic BEC", new_coffee: true, new_coffee_type: "coffee"
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

Signature item inquiries:
- If user asks about signature items, signature menu, or pre-made options -> asking_signature_menu: true
- Also set signature_menu_type to the specific type if mentioned:
  - "what are your signature sandwiches" -> asking_signature_menu: true, signature_menu_type: "signature_items"
  - "what signature sandwiches do you have" -> asking_signature_menu: true, signature_menu_type: "signature_items"
  - "what are your signature bagels" -> asking_signature_menu: true, signature_menu_type: "signature_item"
  - "what signature menu options do you have" -> asking_signature_menu: true (no specific type)
  - "what signature bagels do you have" -> asking_signature_menu: true, signature_menu_type: "signature_item"
  - "what are the signature items" -> asking_signature_menu: true (no specific type)
  - "tell me about the signature menu" -> asking_signature_menu: true (no specific type)
  - "what pre-made bagels do you have" -> asking_signature_menu: true, signature_menu_type: "signature_item"
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
