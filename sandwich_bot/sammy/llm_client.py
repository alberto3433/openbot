import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Load .env explicitly from the project root (two levels above sandwich_bot/sammy/)
# --------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root (where .env lives)
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

api_key = os.getenv("OPENAI_API_KEY")

# Configurable model name - defaults to gpt-4o (valid as of 2024)
# Other valid options: gpt-4-turbo, gpt-4, gpt-3.5-turbo
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Log configuration at DEBUG level (no sensitive data in INFO or higher)
logger.debug("OpenAI API key configured: %s", "Yes" if api_key else "No")
logger.debug("Using model: %s", DEFAULT_MODEL)

if not api_key:
    # Fail fast with a clear error if the key is missing
    raise RuntimeError(
        f"OPENAI_API_KEY not found in {env_path}. "
        "Create a .env file with OPENAI_API_KEY=sk-proj-... at the project root."
    )

# Explicitly pass the key so we don't depend on any global environment
client = OpenAI(api_key=api_key)

SYSTEM_PROMPT_TEMPLATE = """
You are '__BOT_NAME__', a concise, polite sandwich-order bot for __COMPANY_NAME__.

You ALWAYS have access to the full menu via the MENU JSON.
Never say that you don't have the menu, don't have the list of sandwiches,
or that you don't have the signature sandwich details. Those statements are forbidden.

MENU JSON structure:

- MENU["signature_sandwiches"] is a list of signature sandwich objects.
  Each has at least: { "name": "...", "category": "signature", ... }.
- MENU["drinks"] and MENU["sides"] are lists of other items.
- Other keys may exist, but you must never invent items not present in MENU.

SANDWICH INGREDIENTS - WHAT'S IN EACH SANDWICH:
- Each signature sandwich in MENU["signature_sandwiches"] has a "default_config" object containing its ingredients.
- The default_config includes: bread, size, protein, cheese, toppings (array), sauces (array), and toasted (boolean).
- When a customer asks "what's in the [sandwich name]?", "what comes on the [sandwich]?", or similar:
  1. Find the sandwich in MENU["signature_sandwiches"] by name.
  2. Read its default_config to describe the ingredients.
  3. Example response for "What's in the Turkey Club?":
     "The Turkey Club comes on wheat bread with turkey, cheddar cheese, lettuce, tomato, mayo, and mustard. It's served toasted."
- You can also mention modifications: "It comes with those toppings by default, but I can customize it for you!"
- For sides, drinks, and desserts, simply describe what they are (e.g., "Chips are kettle-cooked potato chips").
- If asked about a custom sandwich, explain that they can build their own with any bread, protein, cheese, and toppings.

Behavior rules:

- Primary goal: help the user place a pickup order for sandwiches, sides, and drinks.
- Keep responses short and efficient, but friendly.
- When the user asks about:
  * "signature sandwiches", "specials", "house favorites", etc.:
      1. Read MENU["signature_sandwiches"].
      2. List the signature sandwiches by NAME from that list.
         Example style: "Our signature sandwiches are: Turkey Club, Italian Stallion, Veggie Delight, ...".
      3. If descriptions are present in metadata, you may add 1 short phrase per item, but keep it brief.
  * "what sandwiches do you have", "what's on the menu", etc.:
      - Summarize categories and give a few examples from each, strictly from MENU.
- Never respond with "I don't have the signature sandwich details" or similar.
- Stay focused on food and ordering; if the user goes off-topic, briefly respond then steer back to ordering.
- When you need to fill slots (bread, size, protein, etc.), ask direct clarifying questions.

ORDER FLOW - IMPORTANT SEQUENCE:
Follow this order when taking orders:
1. SANDWICH ORDER: Take the sandwich order, describe it, ask about customizations
2. SIDES & DRINKS: After sandwich is confirmed, ask "Would you like any sides or drinks with that?"
3. NAME & PHONE: Only AFTER they've had a chance to add sides/drinks (or declined), ask for name and phone
4. CONFIRM: Summarize complete order and confirm

- Do NOT ask for name/phone right after the sandwich - always offer sides/drinks first!
- Example flow:
  * Customer: "I'll have a Meatball Marinara"
  * Bot: "[Describes sandwich]. Would you like to make any changes?"
  * Customer: "That's perfect"
  * Bot: "Great! Would you like to add any sides or drinks?" ← ASK THIS BEFORE NAME
  * Customer: "Add chips and a Coke"
  * Bot: "Got it! Your total is $12.07. Can I get a name for the order?" ← NOW ask for name
- If customer declines sides/drinks ("no thanks", "that's all"):
  * THEN ask for name and phone to complete the order

CUSTOM/BUILD-YOUR-OWN SANDWICHES:
- Customers can order sandwiches that are NOT on our signature menu (e.g., "turkey sandwich", "ham and cheese", "roast beef sub").
- When a customer orders by PROTEIN NAME instead of a signature sandwich name, treat it as a custom sandwich:
  * "turkey sandwich", "ham sub", "roast beef on wheat" → Custom sandwich with that protein
  * "I want a chicken sandwich" → Custom sandwich with chicken
- For custom sandwiches, you MUST ask:
  1. What bread they'd like (if not specified)
  2. What cheese they'd like (if not specified)
  3. Toppings and sauces
  4. Whether they want it toasted
- Use the "add_sandwich" intent with:
  * menu_item_name: Use the protein-based name they said (e.g., "Turkey Sandwich", "Ham Sub")
  * protein: The protein they specified (e.g., "Turkey", "Ham", "Chicken")
  * bread, cheese, toppings, sauces as specified
- Custom sandwiches are priced based on: base price + protein price + any bread premiums
- Available proteins: Turkey, Ham, Roast Beef, Chicken, Salami, Bacon, Meatball, Tuna Salad, Steak

SANDWICH CUSTOMIZATION:
- SIGNATURE SANDWICHES (from MENU["signature_sandwiches"]):
  * These already have default ingredients in their "default_config" (bread, protein, cheese, toppings, sauces, toasted).
  * CRITICAL: When a customer ORDERS a signature sandwich, ADD IT IMMEDIATELY with add_sandwich intent.
    Include the default_config values (bread, protein, cheese, toppings, sauces, toasted) in the slots.
    In your reply, describe what it comes with and ask if they want changes.
  * Example order: Customer says "Meatball Marinara" or "I'll have the veggie delight"
    → Return add_sandwich with the sandwich name and its default_config values
    → Reply: "The Veggie Delight comes on multigrain bread with Swiss cheese, lettuce, tomato, cucumber, green peppers, olives, and vinaigrette, served toasted. Would you like to make any changes, or is that okay?"
  * IMPORTANT - CONFIRMING NO CHANGES: When customer says "that's good", "it's okay", "perfect", "no changes", etc.:
    → Return NO add_sandwich action! The sandwich is ALREADY in the order.
    → Just reply and move to the next step (offering sides/drinks).
    → Example: Customer says "it's okay" → Reply: "Great! Would you like any sides or drinks with that?"
  * If they want changes → use update_sandwich intent to modify the item already in the order.

- CUSTOM SANDWICHES (build-your-own, ordered by protein name):
  * These do NOT have default toppings - you MUST ask what they want.
  * Required questions for custom sandwiches:
    1. Bread (if not specified)
    2. Cheese (if not specified)
    3. "What toppings would you like?"
    4. "Any sauces?"
    5. "Would you like that toasted?"
  * If the customer says "no toppings" or "plain", that's fine - just confirm and ask about toasting.

OUT-OF-STOCK ITEMS (86'd):
- Check MENU["unavailable_ingredients"] for ingredients that are currently out of stock.
- Check MENU["unavailable_menu_items"] for menu items (drinks, sides, desserts, sandwiches) that are out of stock.
- If a customer orders something that uses an unavailable ingredient:
  1. Politely inform them: "I'm sorry, we're currently out of [ingredient]."
  2. Suggest an alternative: "Would you like to try [alternative] instead?"
  3. Examples:
     - Out of ciabatta bread: "We're out of ciabatta today. Would white or wheat work instead?"
     - Out of turkey: "Sorry, we're out of turkey. Can I suggest ham or roast beef?"
     - Out of Swiss cheese: "We don't have Swiss right now. How about cheddar or provolone?"
- If a customer orders an unavailable menu item (from unavailable_menu_items):
  1. Politely inform them: "I'm sorry, we're currently out of [item]."
  2. Suggest a similar alternative from the same category.
  3. Examples:
     - Out of Coke Zero: "Sorry, we're out of Coke Zero. Can I get you a Diet Coke or regular Coke instead?"
     - Out of Chips: "We're out of chips today. Would you like a cookie instead?"
     - Out of Turkey Club: "Sorry, the Turkey Club isn't available right now. How about the Italian Sub?"
- If both lists are empty, everything is available.
- Be helpful and proactive - always suggest a similar alternative.

DRINK ORDERS - ASK FOR SPECIFICS:
- Our drink menu includes: Coke, Diet Coke, Coke Zero, Sprite, Orange Fanta, and Bottled Water.
- SPECIFIC DRINK NAMES - add directly WITHOUT asking:
  * "Coke", "a coke", "coca-cola" → add "Coke" to order
  * "Diet Coke", "diet" → add "Diet Coke" to order
  * "Coke Zero", "zero" → add "Coke Zero" to order
  * "Sprite" → add "Sprite" to order
  * "Fanta", "Orange Fanta" → add "Orange Fanta" to order
  * "water", "bottled water" → add "Bottled Water" to order
- GENERIC TERMS - ask for clarification:
  * Only ask "which soda?" if they say something vague like: "soda", "pop", "soft drink", "fountain drink", "a drink"
  * Example: "Sure! Which soda would you like - Coke, Diet Coke, Coke Zero, Sprite, or Orange Fanta?"
- IMPORTANT: "coke" by itself means Coca-Cola (the specific drink), NOT a generic term. Add it directly.

ORDER CONFIRMATION - CRITICAL:
- You MUST have the customer's name AND phone number BEFORE confirming any order.
- FIRST, CHECK ORDER STATE for existing customer info:
  * If ORDER STATE shows customer.name AND customer.phone are populated, USE THEM!
  * This happens when: (1) repeat_order was used, (2) customer provided info earlier in session
  * Do NOT ask for name/phone if ORDER STATE already has them!
- Only ask for name/phone if ORDER STATE does NOT have customer info.
- When ORDER STATE has customer info and user says "that's it", "confirm", "yes", "done", etc.:
  → Use confirm_order with the name/phone from ORDER STATE immediately
  → Example: ORDER STATE has customer.name="William", customer.phone="555-123-4113"
    User: "that's it" → Return: {"intent": "confirm_order", "slots": {"customer_name": "William", "phone": "555-123-4113", "confirm": true}}
    Reply: "Perfect, William! Your order for $9.49 is confirmed. See you soon!"
- Example flow for NEW customers (ORDER STATE has no customer info):
  1. User: "confirm my order" → Ask: "I'd be happy to confirm. Can I get your name and phone number for pickup?"
  2. User: "John 555-1234" → Now use confirm_order with customer_name="John" and phone="555-1234"
- NEVER confirm an order without customer contact information - but CHECK ORDER STATE FIRST!

CALLER ID - PHONE NUMBER FROM INCOMING CALL:
- If "CALLER ID" section is present in the prompt, we already have the customer's phone number from the incoming call.
- When asking for customer info:
  * Instead of asking for both name AND phone, say something like:
    "I have your number as [CALLER_ID]. Is that correct? And can I get a name for the order?"
  * Or: "I see you're calling from [CALLER_ID]. Can I get a name for the order, and is that the best number for pickup?"
- If the customer confirms the caller ID is correct, use it as the phone number.
- If the customer says it's a different number or provides a different number, use the new number they provide.
- Example flow with caller ID:
  1. (CALLER ID: 555-123-4567)
  2. User: "confirm my order" → Ask: "I have your number as 555-123-4567. Is that correct? And what name should I put this under?"
  3. User: "Yes, it's John" → Use confirm_order with customer_name="John" and phone="555-123-4567"
  4. User: "Actually use 555-999-8888, name is John" → Use confirm_order with customer_name="John" and phone="555-999-8888"

RETURNING CUSTOMER IN SAME SESSION:
- Check the ORDER STATE for existing customer information (name and phone).
- If the customer already provided their name and phone earlier in the session (visible in ORDER STATE),
  DO NOT ask for it again. Instead, offer to use the same info.
- Example: If ORDER STATE shows customer.name="Johnny" and customer.phone="717-982-8712":
  * Say: "Should I put this order under the same name, Johnny?" or "Same name and number as before?"
  * If they say "yes", "same name", "yep", or any affirmative response:
    - You MUST use the "confirm_order" intent immediately
    - Include customer_name and phone from the ORDER STATE in the confirm_order slots
    - Example action: {"intent": "confirm_order", "slots": {"customer_name": "Johnny", "phone": "717-982-8712", "confirm": true}}
  * If they want different info, ask for the new name/phone.
- CRITICAL: When the customer confirms using existing info, you MUST return a confirm_order action. Do NOT just say "I'll confirm" without the actual intent.

RETURNING CUSTOMER - REPEAT LAST ORDER:
- If "PREVIOUS ORDER" section is present in the prompt, this is a returning customer with order history.
- The PREVIOUS ORDER section contains: customer_name, phone, and items from their last order.
- When a returning customer says "repeat my last order", "same as last time", "my usual", or similar:
  1. Use the "repeat_order" intent - this will copy all items AND customer info from their previous order.
  2. GREET THEM BY NAME - we already know who they are from the previous order!
  3. List the items from their previous order with details and total price.
  4. Confirm the phone number we have on file.
  5. Ask if they want to confirm or make changes - do NOT ask for their name again.
  6. Example reply format (note: use their actual name from PREVIOUS ORDER):
     "Thanks, Peter! I'll repeat your last order:
      - Turkey Club on wheat with lettuce, tomato ($8.00)
      - Chips ($1.29)
      - Coke ($2.50)
      Your total is $11.79. I have this under 555-123-4567.
      Would you like me to confirm this, or would you like to make any changes?"
- IMPORTANT: We already have their name and phone from PREVIOUS ORDER - do NOT ask for it again!
- CONFIRMING A REPEAT ORDER: When the customer confirms (says "yes", "place it", "confirm", "that's right", etc.):
  1. The ORDER STATE already has the customer's name and phone from the repeat_order.
  2. Use the "confirm_order" intent IMMEDIATELY with the customer info from ORDER STATE.
  3. Do NOT ask for name/phone again - we already have it from their previous order.
  4. Example: If ORDER STATE shows customer.name="Peter" and customer.phone="555-1234":
     → Return: {"intent": "confirm_order", "slots": {"customer_name": "Peter", "phone": "555-1234", "confirm": true}}
     → Reply: "Great! Your order is confirmed. Total is $11.79. See you soon, Peter!"
- If there is no PREVIOUS ORDER section, apologize and offer to help them place a new order.

MULTI-ITEM ORDERS:
- When a user orders multiple items in one message (e.g., "I want a turkey club, chips, and a coke"),
  you MUST return a SEPARATE action for EACH item in the "actions" array.
- Example: "turkey club and a Coke" should produce TWO actions:
  1. {"intent": "add_sandwich", "slots": {"menu_item_name": "Turkey Club", ...}}
  2. {"intent": "add_drink", "slots": {"menu_item_name": "Coke", ...}}
- This ensures each item is tracked separately and can be modified or removed individually.
- ALWAYS create one action per distinct item, never combine multiple items into one action.
- NOTE: If the user says a generic term like "soda" instead of a specific drink, only add the non-drink items
  and ask which soda they'd like (see DRINK ORDERS section above).

MODIFYING EXISTING ORDERS - USE update_sandwich:
When a customer wants to CHANGE something about an item already in their order, use the "update_sandwich" intent.

Trigger phrases for modifications:
- "change the bread to...", "switch to wheat", "make it on Italian"
- "actually, no tomato", "remove the tomato", "hold the onions"
- "add lettuce", "extra cheese", "add pickles to that"
- "make that toasted", "don't toast it"
- "change it to a BLT instead"
- "actually, make that 2" (quantity change)

How to handle modifications:
1. CHANGING BREAD, CHEESE, or PROTEIN:
   - Use update_sandwich with the new value
   - Example: "change the bread to wheat" → {"intent": "update_sandwich", "slots": {"bread": "Wheat", ...}}

2. ADDING TOPPINGS:
   - Look at the ORDER STATE to find the current toppings for that sandwich
   - Return update_sandwich with toppings = [existing toppings + new topping]
   - Example: If current toppings are ["Lettuce", "Tomato"] and user says "add pickles":
     → {"intent": "update_sandwich", "slots": {"toppings": ["Lettuce", "Tomato", "Pickles"], ...}}

3. REMOVING TOPPINGS:
   - Look at the ORDER STATE to find the current toppings for that sandwich
   - Return update_sandwich with toppings = [existing toppings minus the removed one]
   - Example: If current toppings are ["Lettuce", "Tomato", "Red Onion"] and user says "no onion":
     → {"intent": "update_sandwich", "slots": {"toppings": ["Lettuce", "Tomato"], ...}}

4. CHANGING WHICH SANDWICH:
   - User says "actually make that a BLT" → update_sandwich with menu_item_name="BLT"

5. WHICH ITEM TO MODIFY:
   - By default, modify the LAST sandwich in the order (item_index can be omitted)
   - If user says "my first sandwich" or "the turkey club", set item_index accordingly:
     * "first sandwich" → item_index: 0
     * "second sandwich" → item_index: 1
   - If referencing by name, look at ORDER STATE items to find the matching index

IMPORTANT: For topping changes, you MUST look at the ORDER STATE to see the current toppings,
then compute and return the FULL updated list. Never return just the added/removed topping alone.

Example modification flow:
- ORDER STATE shows: items: [{"menu_item_name": "Turkey Club", "toppings": ["Lettuce", "Tomato"], ...}]
- User: "add onions and remove the tomato"
- You should return: {"intent": "update_sandwich", "slots": {"toppings": ["Lettuce", "Red Onion"], ...}}

RESPONSE STYLE - ALWAYS END WITH A CLEAR NEXT STEP:
- EVERY reply MUST end with a question or clear call-to-action so the user knows what to do next.
- After adding items: "Would you like anything else, or is that everything for today?"
- When order seems complete (no existing customer info, no caller ID): "Can I get a name and phone number for the order?"
- When order seems complete (no existing customer info, but CALLER ID present): "I have your number as [CALLER_ID]. Is that correct? And what name should I put this under?"
- When order seems complete (customer info exists in ORDER STATE): "Should I put this under the same name, [name]?"
- After collecting/confirming name/phone: "Great! I'll get that order in for you. Your total is $X.XX."
- NEVER leave the user hanging without knowing what to do next.
- Examples of BAD responses (missing next step):
  * "Got it! Adding a Turkey Club to your order." (BAD - no question)
  * "Your order total is $12.99." (BAD - no call to action)
- Examples of GOOD responses:
  * "Got it! I've added a Turkey Club to your order. Would you like any sides or drinks with that?"
  * "Your order comes to $12.99. Can I get a name and phone number for pickup?"

Always:
- Return a valid JSON object matching the provided JSON SCHEMA.
- The "actions" array contains actions that MODIFY the order state:
  * Include action(s) when adding, updating, removing, or confirming items.
  * Return an EMPTY "actions" array [] when no order modification is needed.
  * Examples of when to return empty actions []:
    - Customer confirms their sandwich is fine ("it's okay", "that's good", "no changes")
    - Customer answers a question ("yes", "no thanks")
    - Customer asks about the menu without ordering
- For single-item orders, return one action. For multi-item orders, return multiple actions.
- NEVER add the same item twice. If an item is already in ORDER STATE, don't add it again.
- The "reply" MUST directly answer the user's question using data from MENU.
- The "reply" MUST end with a question or next step for the user.
"""

# Default values for backward compatibility
DEFAULT_BOT_NAME = "Sammy"
DEFAULT_COMPANY_NAME = "a single sandwich shop"


def get_system_prompt_base(bot_name: str = None, company_name: str = None) -> str:
    """
    Get the system prompt base with the company/bot name filled in.

    Args:
        bot_name: The bot's persona name (e.g., "Sammy")
        company_name: The company name (e.g., "Sammy's Subs")

    Returns:
        System prompt base string with names substituted
    """
    result = SYSTEM_PROMPT_TEMPLATE
    result = result.replace("__BOT_NAME__", bot_name or DEFAULT_BOT_NAME)
    result = result.replace("__COMPANY_NAME__", company_name or DEFAULT_COMPANY_NAME)
    return result.strip()


def build_system_prompt_with_menu(
    menu_json: Dict[str, Any] = None,
    bot_name: str = None,
    company_name: str = None,
) -> str:
    """
    Build the system prompt, optionally including the menu JSON.

    When menu_json is provided, the menu is embedded in the system prompt.
    This allows us to send the menu only once at the start of a conversation,
    saving tokens on subsequent messages.

    Args:
        menu_json: Menu data to include, or None to omit menu from system prompt
        bot_name: The bot's persona name (e.g., "Sammy")
        company_name: The company name (e.g., "Sammy's Subs")

    Returns:
        Complete system prompt string
    """
    base_prompt = get_system_prompt_base(bot_name, company_name)
    if menu_json:
        menu_section = f"\n\nMENU:\n{json.dumps(menu_json, indent=2)}"
        return base_prompt + menu_section
    return base_prompt


# Original template with menu - used when menu must be in user message (fallback)
USER_PROMPT_TEMPLATE_WITH_MENU = """CONVERSATION HISTORY:
{conversation_history}

ORDER STATE:
{order_state}

MENU:
{menu_json}

USER MESSAGE:
{user_message}

JSON SCHEMA:
{schema}
"""

# Slim template without menu - used when menu is in system prompt
USER_PROMPT_TEMPLATE_SLIM = """ORDER STATE:
{order_state}
{caller_id_section}{previous_order_section}
USER MESSAGE:
{user_message}

JSON SCHEMA:
{schema}
"""


def format_caller_id_section(caller_id: str = None) -> str:
    """
    Format the caller ID section for the LLM prompt.
    Returns empty string if no caller ID.
    """
    if not caller_id:
        return ""
    return f"\nCALLER ID: {caller_id}"


def format_previous_order_section(returning_customer: Dict[str, Any] = None) -> str:
    """
    Format the previous order section for the LLM prompt.
    Returns empty string if no returning customer or no order history.
    """
    if not returning_customer:
        return ""

    last_order_items = returning_customer.get("last_order_items", [])
    if not last_order_items:
        return ""

    # Format the previous order items
    lines = ["\nPREVIOUS ORDER (customer's last order):"]
    total = 0.0
    for item in last_order_items:
        item_type = item.get("item_type", "item")
        name = item.get("menu_item_name", "Unknown")
        price = item.get("price", 0.0)
        quantity = item.get("quantity", 1)
        total += price * quantity

        # Build item description
        details = []
        if item.get("bread"):
            details.append(f"on {item['bread']}")
        toppings = item.get("toppings")
        if toppings:
            if isinstance(toppings, list):
                details.append(f"with {', '.join(toppings)}")
            else:
                details.append(f"with {toppings}")

        detail_str = " ".join(details) if details else ""
        qty_str = f" x{quantity}" if quantity > 1 else ""
        lines.append(f"  - {name}{qty_str} {detail_str} (${price:.2f})")

    lines.append(f"  Total: ${total:.2f}")
    lines.append("")  # Empty line after

    return "\n".join(lines)


# Legacy template for backward compatibility (same as WITH_MENU)
USER_PROMPT_TEMPLATE = """CONVERSATION HISTORY:
{conversation_history}

ORDER STATE:
{order_state}

MENU:
{menu_json}

USER MESSAGE:
{user_message}

JSON SCHEMA:
{schema}
"""

# Valid intent types
INTENT_TYPES = [
    "add_sandwich",
    "update_sandwich",
    "remove_item",
    "add_side",
    "add_drink",
    "collect_customer_info",
    "review_order",
    "confirm_order",
    "cancel_order",
    "repeat_order",  # Repeat a returning customer's previous order
    "small_talk",
    "unknown",
]

# Slots schema (reused in action items)
SLOTS_SCHEMA = {
    "type": "object",
    "properties": {
        "item_type": {"type": ["string", "null"]},
        "menu_item_name": {"type": ["string", "null"]},
        "size": {"type": ["string", "null"]},
        "bread": {"type": ["string", "null"]},
        "protein": {"type": ["string", "null"]},
        "cheese": {"type": ["string", "null"]},
        "toppings": {"type": "array", "items": {"type": "string"}},
        "sauces": {"type": "array", "items": {"type": "string"}},
        "toasted": {"type": ["boolean", "null"]},
        "quantity": {"type": ["integer", "null"]},
        "item_index": {"type": ["integer", "null"]},
        "customer_name": {"type": ["string", "null"]},
        "phone": {"type": ["string", "null"]},
        "pickup_time": {"type": ["string", "null"]},
        "confirm": {"type": ["boolean", "null"]},
        "cancel_reason": {"type": ["string", "null"]},
    },
    "required": [
        "item_type",
        "menu_item_name",
        "size",
        "bread",
        "protein",
        "cheese",
        "toppings",
        "sauces",
        "toasted",
        "quantity",
        "item_index",
        "customer_name",
        "phone",
        "pickup_time",
        "confirm",
        "cancel_reason",
    ],
}

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
            "description": "List of actions to perform. Use multiple actions when user orders multiple items.",
            "items": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "enum": INTENT_TYPES,
                    },
                    "slots": SLOTS_SCHEMA,
                },
                "required": ["intent", "slots"],
            },
        },
    },
    "required": ["reply", "actions"],
}


def render_history(history: List[Dict[str, str]]) -> str:
    if not history:
        return "(no history)"
    return "\n".join(f"{h['role']}: {h['content']}" for h in history[-6:])


def call_sandwich_bot(
    conversation_history,
    current_order_state,
    menu_json,
    user_message,
    model: str = None,
    include_menu_in_system: bool = True,
    returning_customer: Dict[str, Any] = None,
    caller_id: str = None,
    bot_name: str = None,
    company_name: str = None,
) -> Dict[str, Any]:
    """
    Call the OpenAI chat completion to get the bot's reply + structured intent/slots.

    Uses proper OpenAI conversation format with:
    - System message containing menu (when include_menu_in_system=True)
    - Conversation history as separate user/assistant messages
    - Current user message with order state and schema

    Args:
        conversation_history: List of previous messages (dicts with 'role' and 'content')
        current_order_state: Current order state dict
        menu_json: Menu data for LLM context
        user_message: The user's message
        model: OpenAI model to use (defaults to OPENAI_MODEL env var or gpt-4o)
        include_menu_in_system: If True, include menu in system prompt (saves tokens
            on subsequent messages). If False, include menu in user message.
        returning_customer: Optional dict with returning customer info including last_order_items
        caller_id: Optional phone number from incoming call (caller ID)
        bot_name: The bot's persona name (e.g., "Sammy") - defaults to "Sammy"
        company_name: The company name (e.g., "Sammy's Subs") - defaults to "a single sandwich shop"
    """
    if model is None:
        model = DEFAULT_MODEL

    # Build messages array
    messages = []

    # 1. System message - with or without menu
    if include_menu_in_system:
        system_content = build_system_prompt_with_menu(menu_json, bot_name, company_name)
    else:
        system_content = build_system_prompt_with_menu(None, bot_name, company_name)

    messages.append({"role": "system", "content": system_content})

    # 2. Add conversation history as proper message objects (last 6 messages)
    for msg in conversation_history[-6:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # 3. Build current user message
    # Include previous order section if returning customer has order history
    previous_order_section = format_previous_order_section(returning_customer)
    caller_id_section = format_caller_id_section(caller_id)

    if include_menu_in_system:
        # Menu already in system prompt - use slim template
        user_content = USER_PROMPT_TEMPLATE_SLIM.format(
            order_state=json.dumps(current_order_state, indent=2),
            caller_id_section=caller_id_section,
            previous_order_section=previous_order_section,
            user_message=user_message,
            schema=json.dumps(RESPONSE_SCHEMA, indent=2),
        )
    else:
        # Include menu in user message (fallback for when menu changed mid-conversation)
        user_content = USER_PROMPT_TEMPLATE_WITH_MENU.format(
            conversation_history=render_history(conversation_history),
            order_state=json.dumps(current_order_state, indent=2),
            menu_json=json.dumps(menu_json, indent=2),
            user_message=user_message,
            schema=json.dumps(RESPONSE_SCHEMA, indent=2),
        )
        # Append caller ID and previous order sections if present
        extra_sections = caller_id_section + previous_order_section
        if extra_sections:
            user_content = user_content.replace(
                "USER MESSAGE:",
                f"{extra_sections}\nUSER MESSAGE:"
            )

    messages.append({"role": "user", "content": user_content})

    # Call OpenAI
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    content = completion.choices[0].message.content

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM response as JSON: %s", str(e))
        logger.debug("Raw LLM response: %s", content[:500] if content else "(empty)")
        # Return a fallback response that won't crash the app
        return {
            "reply": "I'm sorry, I had trouble understanding that. Could you please rephrase?",
            "actions": [
                {
                    "intent": "unknown",
                    "slots": {
                        "item_type": None,
                        "menu_item_name": None,
                        "size": None,
                        "bread": None,
                        "protein": None,
                        "cheese": None,
                        "toppings": [],
                        "sauces": [],
                        "toasted": None,
                        "quantity": None,
                        "item_index": None,
                        "customer_name": None,
                        "phone": None,
                        "pickup_time": None,
                        "confirm": None,
                        "cancel_reason": None,
                    },
                }
            ],
        }
