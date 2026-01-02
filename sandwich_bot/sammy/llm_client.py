import json
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Generator

from dotenv import load_dotenv
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Default timeout for LLM calls (in seconds)
DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

# --------------------------------------------------------------------------------------
# Load .env explicitly from the project root (two levels above sandwich_bot/sammy/)
# --------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root (where .env lives)
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)

# --------------------------------------------------------------------------------------
# LLM Provider Configuration
# Set LLM_PROVIDER=claude or LLM_PROVIDER=openai in .env to switch providers
# --------------------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

# OpenAI configuration
openai_api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Anthropic/Claude configuration
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

# Set default model based on provider
if LLM_PROVIDER == "claude":
    DEFAULT_MODEL = ANTHROPIC_MODEL
else:
    DEFAULT_MODEL = OPENAI_MODEL

logger.debug("LLM Provider: %s", LLM_PROVIDER)
logger.debug("Using model: %s", DEFAULT_MODEL)

# Initialize clients based on provider
openai_client = None
anthropic_client = None

if LLM_PROVIDER == "openai":
    if not openai_api_key:
        raise RuntimeError(
            f"OPENAI_API_KEY not found in {env_path}. "
            "Create a .env file with OPENAI_API_KEY=sk-proj-... at the project root."
        )
    from openai import OpenAI, APITimeoutError as OpenAITimeoutError
    openai_client = OpenAI(api_key=openai_api_key, timeout=DEFAULT_TIMEOUT)
    logger.debug("OpenAI client initialized")

elif LLM_PROVIDER == "claude":
    if not anthropic_api_key:
        raise RuntimeError(
            f"ANTHROPIC_API_KEY not found in {env_path}. "
            "Create a .env file with ANTHROPIC_API_KEY=sk-ant-... at the project root."
        )
    import anthropic
    anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
    logger.debug("Anthropic/Claude client initialized")

else:
    raise RuntimeError(
        f"Invalid LLM_PROVIDER '{LLM_PROVIDER}'. Must be 'openai' or 'claude'."
    )

# For backward compatibility
client = openai_client

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

UPCHARGE CONFIRMATION FOR COFFEE ADD-ONS:
When a customer requests a coffee add-on that has an upcharge, confirm the price BEFORE adding:
- Almond/Oat/Soy Milk: +$0.50
- Hazelnut/Vanilla Syrup: +$0.65
- Peppermint Syrup: +$1.00
- Extra Shot: +$2.50

Example: Customer says "add hazelnut syrup to my coffee"
→ actions: []
→ reply: "Hazelnut syrup is +$0.65. Would you like to add that?"
→ Customer says "yes"
→ NOW add the coffee with the syrup

NOTE: Basic coffee orders (size + black/light/dark) should be added IMMEDIATELY without asking for confirmation!
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

ORDER FLOW - FLEXIBLE INTENT-BASED:
Customers can order ANY item in ANY order. Handle each item type independently:

WHEN CUSTOMER ORDERS SOMETHING - ALWAYS ADD IT IMMEDIATELY:
- Sandwich → Use add_sandwich intent immediately
- Coffee → Use add_drink intent immediately (ask size if not specified)
- Soda/Water → Use add_drink intent immediately
- Side (chips, cookie) → Use add_side intent immediately

AFTER ADDING ANY ITEM:
1. Confirm what was added
2. Determine what question to ask next:
   - If you just added a DRINK (coffee, soda, water, etc.) → Ask "Would you like anything else?"
   - If you added a non-drink AND order already has drinks → Ask "Would you like anything else?"
   - If you added a non-drink AND order has NO drinks yet → Ask "Would you like any sides or drinks with that?"
3. If they say "that's it" / "no" / "I'm done" → Ask for name and phone to complete order

CRITICAL: When you add a drink (coffee, tea, soda, etc.), YOU JUST ADDED A DRINK so don't ask about drinks!

EXAMPLE FLOWS:

Coffee-first order:
  * Customer: "I'd like a coffee"
  * Bot: "What size - small or large?"
  * Customer: "Small"
  * Bot: [add_drink: Coffee, size=small] "Got it, one small black coffee! Would you like anything else?"
  * Customer: "That's all"
  * Bot: "Great! Can I get a name and phone for the order?"

Sandwich-first order (no drinks yet):
  * Customer: "Turkey Club please"
  * Bot: [add_sandwich: Turkey Club] "The Turkey Club comes with... Would you like any changes?"
  * Customer: "No, that's good"
  * Bot: "Would you like any sides or drinks with that?"

Drink-first then sandwich (drinks already in order):
  * Customer: "Large coffee and a Turkey Club"
  * Bot: [add_drink, add_sandwich] "Got it! Large coffee and a Turkey Club. Would you like anything else?"
  * (Note: Don't ask about drinks since they already ordered one!)

Drink-only order:
  * Customer: "Just a Coke"
  * Bot: [add_drink: Coke] "One Coke! Anything else?"
  * Customer: "No thanks"
  * Bot: "Your total is $2.29. Can I get a name for pickup?"

CRITICAL: Every item ordered MUST trigger an add_ action immediately. Never skip adding items!

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
    → Example: Customer says "it's okay" → Check ORDER STATE for drinks, then reply appropriately:
      - No drinks in order: "Great! Would you like any sides or drinks with that?"
      - Drinks already ordered: "Great! Would you like anything else?"
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

DRINK ORDERS - READ FROM MENU:
- Check MENU["drinks"] for all available drinks. Each drink has: name, base_price, item_type.
- SIMPLE DRINKS (item_type="drink"): Sodas, water, etc. - add directly with add_drink intent.
  * Examples: Coke, Diet Coke, Sprite, Bottled Water - add these directly when ordered.
- GENERIC TERMS - ask for clarification:
  * Only ask "which drink?" if they say something vague like: "soda", "pop", "soft drink", "a drink"
  * List options from MENU["drinks"] when clarifying.
- IMPORTANT: "coke" by itself means Coca-Cola (the specific drink), NOT a generic term. Add it directly.

COFFEE ORDERS - CONFIGURABLE DRINK:
- Coffee is a configurable drink with sizes and optional customizations.
- REQUIRED: Size (small, medium, large) - always ask if not specified.
- DEFAULT: Black coffee (style: black) - no milk, no syrup, no sweetener.

COFFEE ORDER FLOW - CRITICAL:

STEP 1 - GATHER INFO (ask questions, no action yet):
- If size is missing → Ask: "What size - small or large?"
- If upcharge item requested → Ask: "Hazelnut syrup is +$0.65. Is that okay?"

STEP 2 - ADD COFFEE (when you have size AND any upcharges are confirmed):
- Return add_coffee action with ALL modifiers mentioned in the conversation
- IMPORTANT: Include modifiers from EARLIER messages, not just the current one!

REMEMBERING MODIFIERS - CRITICAL:
When a customer says "coffee with hazelnut syrup" and you ask "what size?", you MUST remember
the hazelnut syrup when they answer with the size. Look back at the conversation history!

Example conversation:
  User: "coffee with hazelnut syrup"
  Bot: "Hazelnut syrup is +$0.65. What size would you like?" (actions: [])
  User: "small"
  Bot: "Got it!" → add_coffee with syrup: ["hazelnut"], size: "small"  ← INCLUDE THE HAZELNUT!

WRONG: User asks for hazelnut, you ask size, then add coffee WITHOUT hazelnut
RIGHT: User asks for hazelnut, you ask size, then add coffee WITH hazelnut included

FREE OPTIONS (add directly, no confirmation needed):
- Style: Black, Light, Dark
- Milk: Whole Milk, Half N Half, Lactose Free
- Sweetener: Sugar in the Raw, Domino Sugar, Equal, Splenda, Sweet & Low

UPCHARGE OPTIONS (confirm price, then include when adding):
- Almond Milk, Oat Milk, Soy Milk: +$0.50 each
- Hazelnut Syrup, Vanilla Syrup: +$0.65 each
- Peppermint Syrup: +$1.00
- Extra Shot: +$2.50

EXAMPLES:
- "Large black coffee" → Add directly: size="large", style="black"
- "Small coffee" → Add directly: size="small" (black is default)
- "Coffee with hazelnut" → Ask "Hazelnut is +$0.65, what size?" → User: "small" → Add with size="small", syrup=["hazelnut"]
- "Large coffee with oat milk" → Ask "Oat milk is +$0.50. Is that okay?" → User: "yes" → Add with size="large", milk="oat_milk"
- "Small coffee with vanilla syrup" → User gave size AND upcharge item, so add directly with size="small", syrup=["vanilla"]

CRITICAL - WHEN USER GIVES SIZE + MODIFIERS TOGETHER:
If user says "small coffee with vanilla syrup" or "large coffee with oat milk", they've given you everything needed.
DO NOT ask for confirmation - add immediately with add_coffee action!
Example: "small coffee with vanilla syrup" → actions: [{"intent": "add_coffee", "slots": {"menu_item_name": "Coffee", "size": "small", "syrup": ["vanilla"]}}]

CRITICAL - SIZE RESPONSE = ADD ACTION:
When you ask "what size?" and the user responds with a size (small or large), you MUST:
1. Return an add_coffee/add_drink action with menu_item_name="Coffee" and size from user
2. Say "I've added..." in your reply

Multi-turn example:
  Turn 1 - User: "coffee"
  Turn 1 - Bot: "What size coffee - small or large?" → actions: []
  Turn 2 - User: "small"
  Turn 2 - Bot: "Great! I've added a small coffee." → actions: [{"intent": "add_coffee", "slots": {"menu_item_name": "Coffee", "size": "small"}}]

WRONG: User says "small", you reply "I've added a small coffee" but return actions: []
RIGHT: User says "small", you reply "I've added a small coffee" AND return the add_coffee action

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
  * "Got it! I've added a Turkey Club to your order. Would you like any sides or drinks with that?" (if no drinks in order yet)
  * "Got it! I've added a Turkey Club to your order. Would you like anything else?" (if drinks already in order)
  * "Your order comes to $12.99. Can I get a name and phone number for pickup?"

Always:
- Return a valid JSON object matching the provided JSON SCHEMA.
- The "actions" array contains actions that MODIFY the order state:
  * Include action(s) when adding, updating, removing, or confirming items.
  * Return an EMPTY "actions" array [] when no order modification is needed.
  * Examples of when to return empty actions []:
    - Customer confirms their sandwich is fine ("it's okay", "that's good", "no changes")
    - You're asking a clarifying question ("What size coffee?")
    - Customer asks about the menu without ordering
    - Customer requests an upcharge add-on - ask for confirmation first
  * Examples of when to return add_drink action:
    - Customer specifies coffee size: "large" → add_drink with menu_item_name="Coffee", size="large"
    - Customer orders "large black coffee" → add_drink immediately with size="large"
    - Customer orders "small coffee with vanilla syrup" → add_drink immediately with size="small", syrup=["vanilla"]
    - Customer confirms upcharge: "yes, add the hazelnut" → add_drink with syrup
    - CRITICAL: When you asked "what size?" and user responds "small"/"large" → YOU MUST return add_drink action!
    - CRITICAL: If you say "I've added" in your reply, you MUST include the corresponding action! Never say "added" without an action!
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
    db: Optional[Session] = None,
    use_dynamic_prompt: bool = False,
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
        db: Optional database session for dynamic prompt building
        use_dynamic_prompt: If True and db provided, use dynamic prompt builder

    Returns:
        Complete system prompt string
    """
    # Use dynamic prompt builder if requested and database is available
    if use_dynamic_prompt and db is not None:
        from ..prompt_builder import build_system_prompt_with_menu as dynamic_build
        return dynamic_build(db, menu_json, bot_name, company_name)

    # Fall back to legacy template-based prompt
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
    "add_pizza",
    "update_pizza",
    "remove_item",
    "add_side",
    "add_drink",
    "add_coffee",  # Alias for add_drink, specifically for coffee orders
    "collect_customer_info",
    "set_order_type",  # Set pickup or delivery
    "collect_delivery_address",  # Collect address for delivery orders
    "request_payment_link",  # Customer wants SMS payment link
    "collect_card_payment",  # Customer provides card over phone
    "pay_at_pickup",  # Customer will pay at pickup/delivery
    "review_order",
    "confirm_order",
    "cancel_order",
    "repeat_order",  # Repeat a returning customer's previous order
    "small_talk",
    "unknown",
]

# Slots schema (reused in action items)
# Note: This schema supports multiple item types (sandwiches, pizzas, etc.)
# - bread: used for sandwiches
# - crust: used for pizzas
# - sauce: used for pizzas (single select)
# - sauces: used for sandwiches (multi select)
SLOTS_SCHEMA = {
    "type": "object",
    "properties": {
        "item_type": {"type": ["string", "null"]},
        "menu_item_name": {"type": ["string", "null"]},
        "size": {"type": ["string", "null"]},
        "bread": {"type": ["string", "null"]},
        "crust": {"type": ["string", "null"]},
        "protein": {"type": ["string", "null"]},
        "cheese": {"type": ["string", "null"]},
        "sauce": {"type": ["string", "null"]},
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
        # Order type and delivery
        "order_type": {"type": ["string", "null"]},  # "pickup" or "delivery"
        "delivery_address": {"type": ["string", "null"]},
        # Payment card details (for card over phone)
        "card_number": {"type": ["string", "null"]},
        "card_expiry": {"type": ["string", "null"]},  # MM/YY format
        "card_cvv": {"type": ["string", "null"]},
        # Payment link delivery method
        "link_delivery_method": {"type": ["string", "null"]},  # "sms" or "email"
        "customer_email": {"type": ["string", "null"]},  # Email for payment link
        # Generic item configuration for configurable items (coffee sizes, etc.)
        "item_config": {"type": ["object", "null"]},  # e.g., {"size": "large"}
    },
    "required": [
        "item_type",
        "menu_item_name",
        "size",
        "bread",
        "crust",
        "protein",
        "cheese",
        "sauce",
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
    db: Optional[Session] = None,
    use_dynamic_prompt: bool = False,
    timeout: float = None,
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
        db: Optional database session for dynamic prompt building
        use_dynamic_prompt: If True and db provided, use dynamic prompt builder
        timeout: Request timeout in seconds (defaults to DEFAULT_TIMEOUT)
    """
    if model is None:
        model = DEFAULT_MODEL

    # Build messages array
    messages = []

    # 1. System message - with or without menu
    if include_menu_in_system:
        system_content = build_system_prompt_with_menu(
            menu_json, bot_name, company_name, db, use_dynamic_prompt
        )
    else:
        system_content = build_system_prompt_with_menu(
            None, bot_name, company_name, db, use_dynamic_prompt
        )

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

    # Call LLM based on provider
    request_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    try:
        if LLM_PROVIDER == "claude":
            # Claude API: system message is passed separately
            response = anthropic_client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_content,
                messages=[msg for msg in messages if msg["role"] != "system"],
                temperature=0.0,
            )
            content = response.content[0].text
        else:
            # OpenAI API
            completion = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=request_timeout,
            )
            content = completion.choices[0].message.content

        # Log the raw LLM response for debugging
        logger.info("LLM raw response: %s", content[:1000] if content else "(empty)")
    except Exception as e:
        error_name = type(e).__name__
        logger.error("LLM request failed (%s): %s", error_name, str(e))
        return {
            "reply": "I'm sorry, the request is taking longer than expected. Please try again.",
            "actions": [],
        }

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


def call_sandwich_bot_stream(
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
    db: Optional[Session] = None,
    use_dynamic_prompt: bool = False,
    timeout: float = None,
) -> Generator[str, None, Dict[str, Any]]:
    """
    Streaming version of call_sandwich_bot that yields tokens as they arrive.

    Yields partial content as it streams, then returns the final parsed result.
    Use this for real-time feedback to users.

    Args:
        Same as call_sandwich_bot

    Yields:
        str: Partial content tokens as they arrive

    Returns:
        Dict[str, Any]: Final parsed JSON response (same format as call_sandwich_bot)
    """
    if model is None:
        model = DEFAULT_MODEL

    # Build messages array (same as non-streaming version)
    messages = []

    # 1. System message - with or without menu
    if include_menu_in_system:
        system_content = build_system_prompt_with_menu(
            menu_json, bot_name, company_name, db, use_dynamic_prompt
        )
    else:
        system_content = build_system_prompt_with_menu(
            None, bot_name, company_name, db, use_dynamic_prompt
        )

    messages.append({"role": "system", "content": system_content})

    # 2. Add conversation history as proper message objects (last 6 messages)
    for msg in conversation_history[-6:]:
        messages.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # 3. Build current user message
    previous_order_section = format_previous_order_section(returning_customer)
    caller_id_section = format_caller_id_section(caller_id)

    if include_menu_in_system:
        user_content = USER_PROMPT_TEMPLATE_SLIM.format(
            order_state=json.dumps(current_order_state, indent=2),
            caller_id_section=caller_id_section,
            previous_order_section=previous_order_section,
            user_message=user_message,
            schema=json.dumps(RESPONSE_SCHEMA, indent=2),
        )
    else:
        user_content = USER_PROMPT_TEMPLATE_WITH_MENU.format(
            conversation_history=render_history(conversation_history),
            order_state=json.dumps(current_order_state, indent=2),
            menu_json=json.dumps(menu_json, indent=2),
            user_message=user_message,
            schema=json.dumps(RESPONSE_SCHEMA, indent=2),
        )
        extra_sections = caller_id_section + previous_order_section
        if extra_sections:
            user_content = user_content.replace(
                "USER MESSAGE:",
                f"{extra_sections}\nUSER MESSAGE:"
            )

    messages.append({"role": "user", "content": user_content})

    # Call LLM with streaming based on provider
    request_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
    full_content = ""

    try:
        if LLM_PROVIDER == "claude":
            # Claude streaming API
            with anthropic_client.messages.stream(
                model=model,
                max_tokens=2048,
                system=system_content,
                messages=[msg for msg in messages if msg["role"] != "system"],
                temperature=0.0,
            ) as stream:
                for text in stream.text_stream:
                    full_content += text
                    yield text
        else:
            # OpenAI streaming API
            stream = openai_client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=request_timeout,
                stream=True,
            )

            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_content += token
                    yield token

    except Exception as e:
        error_name = type(e).__name__
        logger.error("LLM streaming request failed (%s): %s", error_name, str(e))
        yield json.dumps({
            "reply": "I'm sorry, the request is taking longer than expected. Please try again.",
            "actions": [],
        })
        return {
            "reply": "I'm sorry, the request is taking longer than expected. Please try again.",
            "actions": [],
        }

    # Log the raw LLM response for debugging pizza order issues
    logger.info("LLM streamed response: %s", full_content[:1000] if full_content else "(empty)")

    # Parse the final content
    try:
        return json.loads(full_content)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse streamed LLM response as JSON: %s", str(e))
        logger.debug("Raw streamed response: %s", full_content[:500] if full_content else "(empty)")
        return {
            "reply": "I'm sorry, I had trouble understanding that. Could you please rephrase?",
            "actions": [],
        }
