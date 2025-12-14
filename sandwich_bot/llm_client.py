import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Load .env explicitly from the project root (one level above sandwich_bot/)
# --------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent  # project root (where .env lives)
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

SYSTEM_PROMPT_BASE = """
You are 'Sammy', a concise, polite sandwich-order bot for a single sandwich shop.

You ALWAYS have access to the full menu via the MENU JSON.
Never say that you don't have the menu, don't have the list of sandwiches,
or that you don't have the signature sandwich details. Those statements are forbidden.

MENU JSON structure:

- MENU["signature_sandwiches"] is a list of signature sandwich objects.
  Each has at least: { "name": "...", "category": "signature", ... }.
- MENU["drinks"] and MENU["sides"] are lists of other items.
- Other keys may exist, but you must never invent items not present in MENU.

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
- When the order seems complete, ask for the customer's name and phone number for pickup.

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

SANDWICH CUSTOMIZATION - ALWAYS ASK:
- When a customer orders ANY sandwich (signature OR custom), you MUST ask about toppings and toasting before moving on.
- Required questions for every sandwich order:
  1. "What toppings would you like?" (lettuce, tomato, onion, pickles, etc.)
  2. "Would you like that toasted?"
- You can combine these into one question: "What toppings would you like, and would you like it toasted?"
- Only after the customer answers these questions should you ask if they want anything else.
- If the customer says "no toppings" or "plain", that's fine - just confirm and ask about toasting.
- If the customer says "the usual" or "everything", ask them to specify which toppings they'd like.

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
- You MUST collect the customer's name AND phone number BEFORE confirming any order.
- If the user says "confirm" or "yes" to confirm but has NOT provided their name and phone,
  DO NOT use the "confirm_order" intent. Instead, ask for their name and phone number first.
- Only use "confirm_order" intent when you have BOTH customer_name AND phone in the slots.
- Example flow:
  1. User: "confirm my order" → Ask: "I'd be happy to confirm. Can I get your name and phone number for pickup?"
  2. User: "John 555-1234" → Now use confirm_order with customer_name="John" and phone="555-1234"
- If the user provides name and phone in the same message as "confirm", include them in the confirm_order slots.
- NEVER confirm an order without customer contact information.

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
   - Example: If current toppings are ["Lettuce", "Tomato", "Onion"] and user says "no onion":
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
- You should return: {"intent": "update_sandwich", "slots": {"toppings": ["Lettuce", "Onion"], ...}}

RESPONSE STYLE - ALWAYS END WITH A CLEAR NEXT STEP:
- EVERY reply MUST end with a question or clear call-to-action so the user knows what to do next.
- After adding items: "Would you like anything else, or is that everything for today?"
- When order seems complete (no existing customer info): "Can I get a name and phone number for the order?"
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
- The "actions" array should contain one or more actions based on the user's message.
- For single-item requests, return one action. For multi-item requests, return multiple actions.
- The "reply" MUST directly answer the user's question using data from MENU.
- The "reply" MUST end with a question or next step for the user.
""".strip()


def build_system_prompt_with_menu(menu_json: Dict[str, Any] = None) -> str:
    """
    Build the system prompt, optionally including the menu JSON.

    When menu_json is provided, the menu is embedded in the system prompt.
    This allows us to send the menu only once at the start of a conversation,
    saving tokens on subsequent messages.

    Args:
        menu_json: Menu data to include, or None to omit menu from system prompt

    Returns:
        Complete system prompt string
    """
    if menu_json:
        menu_section = f"\n\nMENU:\n{json.dumps(menu_json, indent=2)}"
        return SYSTEM_PROMPT_BASE + menu_section
    return SYSTEM_PROMPT_BASE


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

USER MESSAGE:
{user_message}

JSON SCHEMA:
{schema}
"""

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
    """
    if model is None:
        model = DEFAULT_MODEL

    # Build messages array
    messages = []

    # 1. System message - with or without menu
    if include_menu_in_system:
        system_content = build_system_prompt_with_menu(menu_json)
    else:
        system_content = build_system_prompt_with_menu(None)

    messages.append({"role": "system", "content": system_content})

    # 2. Add conversation history as proper message objects (last 6 messages)
    for msg in conversation_history[-6:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # 3. Build current user message
    if include_menu_in_system:
        # Menu already in system prompt - use slim template
        user_content = USER_PROMPT_TEMPLATE_SLIM.format(
            order_state=json.dumps(current_order_state, indent=2),
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
