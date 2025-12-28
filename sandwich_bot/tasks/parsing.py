"""
LLM Parsing for User Messages.

This module uses instructor for structured LLM outputs to parse
user messages into actionable order data.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field
import instructor
from openai import OpenAI
import os


# =============================================================================
# Parsed Schemas
# =============================================================================

class ParsedBagelItem(BaseModel):
    """A parsed bagel item from user input."""

    item_type: Literal["bagel"] = "bagel"
    bagel_type: str | None = Field(
        default=None,
        description="Type of bagel: plain, everything, sesame, poppy, onion, cinnamon raisin, etc."
    )
    quantity: int = Field(
        default=1,
        description="Number of bagels"
    )
    toasted: bool | None = Field(
        default=None,
        description="Whether the bagel should be toasted. None if not mentioned."
    )
    spread: str | None = Field(
        default=None,
        description="Spread type: cream cheese, butter, etc."
    )
    spread_type: str | None = Field(
        default=None,
        description="Specific spread variety: plain, scallion, veggie, lox, etc."
    )
    extras: list[str] = Field(
        default_factory=list,
        description="Additional toppings: lox, bacon, tomato, onion, capers, etc."
    )
    sandwich_protein: str | None = Field(
        default=None,
        description="Sandwich protein if this is a sandwich: egg, bacon, sausage, etc."
    )


class ParsedCoffeeItem(BaseModel):
    """A parsed coffee/drink item from user input."""

    item_type: Literal["coffee"] = "coffee"
    drink_type: str | None = Field(
        default=None,
        description="Type of drink: drip coffee, latte, cappuccino, espresso, tea, etc."
    )
    quantity: int = Field(
        default=1,
        description="Number of drinks"
    )
    size: str | None = Field(
        default=None,
        description="Size: small, medium, large"
    )
    iced: bool | None = Field(
        default=None,
        description="Whether the drink should be iced. None if not mentioned."
    )
    milk: str | None = Field(
        default=None,
        description="Milk type: whole, skim, oat, almond, etc."
    )
    sweetener: str | None = Field(
        default=None,
        description="Sweetener type: sugar, splenda, stevia, honey, etc. Do NOT include syrups here."
    )
    sweetener_quantity: int = Field(
        default=1,
        description="Number of sweetener packets (e.g., '2 splendas' -> 2)"
    )
    flavor_syrup: str | None = Field(
        default=None,
        description="Flavor syrup: vanilla, caramel, hazelnut, mocha, pumpkin spice, etc."
    )
    extra_shots: int = Field(
        default=0,
        description="Number of extra espresso shots"
    )


class ParsedMenuItem(BaseModel):
    """A parsed menu item ordered by name from user input."""

    item_name: str = Field(
        description="The name of the menu item as stated by the user (e.g., 'The Chipotle Egg Omelette', 'The Classic BEC')"
    )
    quantity: int = Field(
        default=1,
        description="Number of this item"
    )
    modifications: list[str] = Field(
        default_factory=list,
        description="Any modifications mentioned (e.g., 'no onions', 'extra cheese', 'on an everything bagel')"
    )


class ItemModification(BaseModel):
    """A modification to an existing order item."""

    item_index: int | None = Field(
        default=None,
        description="Index of item to modify (0-based). None = current/last item."
    )
    item_type: str | None = Field(
        default=None,
        description="Type of item to modify if index not specified"
    )
    field: str = Field(
        description="Which field to change: toasted, spread, size, iced, etc."
    )
    new_value: Any = Field(
        description="New value for the field"
    )


class ParsedInput(BaseModel):
    """
    Structured output from LLM parsing of user message.

    This captures all the relevant information from a user's message
    including new items, modifications, answers to pending questions,
    and intents like checkout or cancellation.
    """

    # New items mentioned in the message
    new_bagels: list[ParsedBagelItem] = Field(
        default_factory=list,
        description="New bagel items mentioned by the user"
    )
    new_coffees: list[ParsedCoffeeItem] = Field(
        default_factory=list,
        description="New coffee/drink items mentioned by the user"
    )
    new_menu_items: list[ParsedMenuItem] = Field(
        default_factory=list,
        description="Menu items ordered by name (e.g., 'The Chipotle Egg Omelette', 'The Leo', 'Nova Scotia Salmon on Bagel')"
    )

    # Modifications to existing items
    modifications: list[ItemModification] = Field(
        default_factory=list,
        description="Changes to existing order items"
    )

    # Answers to pending questions (field name -> value)
    answers: dict[str, Any] = Field(
        default_factory=dict,
        description="Answers to pending questions: e.g., {'toasted': True, 'spread': 'cream cheese'}"
    )

    # Split answers for multi-quantity items (e.g., "butter on one, cream cheese on the other")
    # Each dict in the list is an answer set for one of the split items
    split_item_answers: list[dict[str, Any]] = Field(
        default_factory=list,
        description="For multi-quantity items with different values: e.g., [{'spread': 'butter'}, {'spread': 'cream cheese'}] for 'butter on one, cream cheese on the other'"
    )

    # Intents
    wants_checkout: bool = Field(
        default=False,
        description="User wants to proceed to checkout/payment"
    )
    wants_cancel_order: bool = Field(
        default=False,
        description="User wants to cancel the entire order"
    )
    cancel_item_index: int | None = Field(
        default=None,
        description="Index of specific item to cancel (0-based)"
    )
    cancel_item_description: str | None = Field(
        default=None,
        description="Description of item to cancel if index not clear"
    )
    wants_to_add_more: bool = Field(
        default=False,
        description="User explicitly wants to add more items"
    )
    no_more_items: bool = Field(
        default=False,
        description="User indicates they don't want anything else"
    )

    # Delivery/Pickup
    order_type: Literal["pickup", "delivery"] | None = Field(
        default=None,
        description="Whether this is for pickup or delivery"
    )
    delivery_address: str | None = Field(
        default=None,
        description="Delivery address if mentioned"
    )

    # Customer info
    customer_name: str | None = Field(
        default=None,
        description="Customer's name for the order"
    )
    customer_phone: str | None = Field(
        default=None,
        description="Customer's phone number"
    )
    customer_email: str | None = Field(
        default=None,
        description="Customer's email address"
    )

    # Payment
    payment_method: Literal["in_store", "cash_delivery", "card_link"] | None = Field(
        default=None,
        description="How the customer wants to pay"
    )

    # Order confirmation and payment link
    confirms_order: bool = Field(
        default=False,
        description="User confirms the order looks correct (e.g., 'yes', 'looks good', 'that's right')"
    )
    wants_payment_link: bool | None = Field(
        default=None,
        description="User wants payment link sent via email/text (True), or will pay in person (False). None if not asked yet."
    )

    # Menu queries
    menu_query: bool = Field(
        default=False,
        description="User is asking about menu items (e.g., 'what egg sandwiches do you have?', 'what fish sandwiches do you have?', 'what bagels do you have?')"
    )
    menu_query_type: str | None = Field(
        default=None,
        description="The type of item being queried: 'egg_sandwich', 'fish_sandwich', 'sandwich', 'bagel', 'drink', 'side', 'signature_sandwich', etc."
    )

    # Options inquiry - asking about available customization options
    options_inquiry: bool = Field(
        default=False,
        description="User is asking about available OPTIONS for customizing an item (e.g., 'what cheese can I have?', 'what are my bagel choices?', 'what fillings do you have?')"
    )
    options_inquiry_item_type: str | None = Field(
        default=None,
        description="The item type they're asking about options for: 'omelette', 'bagel', 'coffee', etc."
    )
    options_inquiry_attribute: str | None = Field(
        default=None,
        description="The specific attribute/option being asked about: 'cheese', 'filling', 'bagel_choice', 'side_choice', 'spread', 'extras', etc."
    )

    # General
    is_greeting: bool = Field(
        default=False,
        description="Message is just a greeting with no order content"
    )
    needs_clarification: bool = Field(
        default=False,
        description="Message is unclear and needs clarification. ONLY set to true for gibberish or contradictory requests."
    )
    clarification_needed: str | None = Field(
        default=None,
        description="A simple clarification question to ask the user, e.g. 'Did you want a bagel or a coffee?'. NEVER put reasoning or explanations here."
    )


# =============================================================================
# Parsing System Prompt
# =============================================================================

PARSING_SYSTEM_PROMPT = """You are a parser for a bagel shop order-taking system.
Your job is to extract structured information from customer messages.

IMPORTANT RULES:
1. Only extract information that is EXPLICITLY stated in the message
2. Use None/null for fields that are not mentioned
3. Be precise about item types (bagel types, drink types)
4. Handle multiple items in a single message
5. Recognize corrections/modifications to previous items
6. Identify intents like checkout, cancellation, adding more

CRITICAL - WHEN TO CREATE ITEMS:
- If user says "I want a bagel" or "I'd like to order a bagel" -> CREATE a new_bagels entry with bagel_type=null
- If user says "I want a coffee" or "give me a coffee" -> CREATE a new_coffees entry with drink_type=null
- If user orders a specific menu item by name (e.g., "I'll have the Chipotle Egg Omelette", "can I get the Leo?", "give me the Classic BEC") -> CREATE a new_menu_items entry with item_name
- DO NOT set needs_clarification=true just because the user didn't specify bagel type or drink type
- The system has defaults for unspecified fields - your job is just to capture what was said
- Only set needs_clarification=true for genuinely unclear messages (gibberish, contradictory requests)

ORDERING MENU ITEMS BY NAME - CRITICAL:
When a user orders a specific menu item by name, use new_menu_items:
- "can I get the chipotle egg omelette?" -> new_menu_items: [{item_name: "The Chipotle Egg Omelette", quantity: 1}]
- "I'll have the Leo" -> new_menu_items: [{item_name: "The Leo", quantity: 1}]
- "give me the classic BEC" -> new_menu_items: [{item_name: "The Classic BEC", quantity: 1}]
- "two Delancey omelettes please" -> new_menu_items: [{item_name: "The Delancey Omelette", quantity: 2}]
- "the health nut with extra avocado" -> new_menu_items: [{item_name: "The Health Nut", modifications: ["extra avocado"]}]
- "Nova Scotia Salmon on Bagel" -> new_menu_items: [{item_name: "Nova Scotia Salmon on Bagel", quantity: 1}]
Key phrases that indicate ordering a specific menu item:
- "can I get the [item name]"
- "I'll have the [item name]"
- "give me the [item name]"
- "I want the [item name]"
- "[item name] please"
Capitalize menu item names properly (e.g., "The Chipotle Egg Omelette" not "chipotle egg omelette")

COMMON MAPPINGS:
- "everything bagel" -> bagel_type: "everything"
- "plain bagel" -> bagel_type: "plain"
- "sesame bagel" -> bagel_type: "sesame"
- "coffee" without qualifiers -> drink_type: "drip coffee"
- "latte" -> drink_type: "latte"
- "iced coffee" -> drink_type: "drip coffee", iced: true
- "hot" for drinks -> iced: false
- "cream cheese" -> spread: "cream cheese"
- "butter" -> spread: "butter"
- "lox" or "salmon" -> extras: ["lox"]

COFFEE MILK - CRITICAL:
- "with milk" without specifying type -> milk: "whole" (default to whole milk)
- "oat milk", "almond milk", "soy milk", "skim" -> use that milk type
- "black" -> milk: "none"
- "coffee with milk" -> milk: "whole"
- "latte with oat milk" -> milk: "oat"

COFFEE SWEETENERS AND SYRUPS - CRITICAL:
- Sweeteners are packets (sugar, splenda, stevia, equal, honey): sweetener field
- Syrups are flavored liquids (vanilla, caramel, hazelnut, mocha): flavor_syrup field
- "2 splendas" -> sweetener: "splenda", sweetener_quantity: 2
- "3 sugars" -> sweetener: "sugar", sweetener_quantity: 3
- "vanilla syrup" or "with vanilla" -> flavor_syrup: "vanilla"
- "caramel latte" -> drink_type: "latte", flavor_syrup: "caramel"
- "hazelnut" -> flavor_syrup: "hazelnut"
- "latte with vanilla and 2 splendas" -> flavor_syrup: "vanilla", sweetener: "splenda", sweetener_quantity: 2

ANSWER RECOGNITION:
When parsing answers to questions, map common responses:
- "yes", "yeah", "sure", "please" for boolean questions -> true
- "no", "nope", "no thanks" for boolean questions -> false
- "that's all", "nothing else", "I'm good" -> no_more_items: true
- "actually", "wait", "change" signals a modification

MODIFICATIONS VS NEW ITEMS - CRITICAL:
When user wants to CHANGE an existing item, use modifications[] ONLY, do NOT create new items:
- "make it a large" -> modifications: [{field: "size", new_value: "large"}], new_coffees: []
- "change it to iced" -> modifications: [{field: "iced", new_value: true}], new_coffees: []
- "actually make that toasted" -> modifications: [{field: "toasted", new_value: true}], new_bagels: []
- "make it a large coffee" -> modifications to size, NOT a new coffee
- "change the size to small" -> modifications to size, NOT a new item
Key phrases that indicate MODIFICATION (never create new items for these):
- "make it", "change it", "actually", "instead", "switch to", "can you make that"
- ONLY use modifications[], set new_bagels: [] and new_coffees: []

SPLIT ITEM ANSWERS - For multi-quantity items with different values:
When current item has quantity > 1 and user specifies DIFFERENT values for each:
- "butter on one and cream cheese on the other" -> split_item_answers: [{"spread": "butter"}, {"spread": "cream cheese"}]
- "one toasted, one not" -> split_item_answers: [{"toasted": true}, {"toasted": false}]
- "make one iced and one hot" -> split_item_answers: [{"iced": true}, {"iced": false}]
Key phrases that indicate SPLITTING (use split_item_answers, NOT modifications):
- "one ... and one ...", "one ... the other ...", "first one ... second one ..."
- DO NOT use modifications for these - use split_item_answers instead
- DO NOT create new items for these - the system will split the existing multi-quantity item

ZIP CODE AND ADDRESS FIELDS:
- If pending question asks for zip code (e.g., "And the zip code?"), a 5-digit number like "10001" -> answers: {"zip_code": "10001"}
- If pending question asks for address, the response is the delivery_address
- DO NOT create new items when answering zip code or address questions

CRITICAL - ANSWERS VS NEW ITEMS:
When there is a pending question, short responses like "yes", "no", "cream cheese",
"toasted", "hot", "iced", "pickup", "delivery" are ANSWERS to that question - NOT new orders.
- If pending question is "Would you like that toasted?" and user says "yes" -> answers: {"toasted": true}, DO NOT create new_bagels
- If pending question is "cream cheese or butter?" and user says "cream cheese" -> answers: {"spread": "cream cheese"}, DO NOT create new_bagels
- If pending question is "Hot or iced?" and user says "iced" -> answers: {"iced": true}, DO NOT create new_coffees
- If pending question is "pickup or delivery?" and user says "pickup" -> order_type: "pickup", DO NOT create new_bagels or new_coffees
- If pending question asks for name and user says "John" -> customer_name: "John", DO NOT create new items
- If pending question asks for zip code and user says "10001" -> answers: {"zip_code": "10001"}, DO NOT create new items
- If pending question asks for address and user provides one -> delivery_address: "the address", DO NOT create new items
- ONLY create new_bagels or new_coffees when user explicitly asks for a NEW item (e.g., "I want another bagel", "add a coffee", "can I also get...")

OMELETTE SIDE CHOICE AND BAGEL CHOICE - CRITICAL:
When a user ORDERS an omelette (e.g., "can I get the chipotle egg omelette?"):
- DO NOT set side_choice or bagel_choice - leave them unset!
- The system will ask about the side choice in a follow-up question
- Example: "can I get the chipotle egg omelette?" -> new_menu_items: [{item_name: "The Chipotle Egg Omelette"}], answers: {} (EMPTY!)

ONLY set side_choice/bagel_choice when the user is ANSWERING a pending question:
- If pending question asks "Would you like a bagel or fruit salad with your [omelette]?" and user says:
  - "bagel" -> answers: {"side_choice": "bagel"}, DO NOT create new_bagels
  - "fruit salad" -> answers: {"side_choice": "fruit_salad"}, DO NOT create new_bagels
- If pending question asks "What kind of bagel would you like?" (after choosing bagel as side):
  - "pumpernickel" -> answers: {"bagel_choice": "pumpernickel"}, DO NOT create new_bagels
  - "everything bagel" -> answers: {"bagel_choice": "everything"}, DO NOT create new_bagels
  - "plain" -> answers: {"bagel_choice": "plain"}, DO NOT create new_bagels
- These are answers about the SIDE for the omelette, NOT separate bagel orders!
- Key pattern: If pending question is about side/bagel choice, it's for the omelette's side.
- User saying "give me the pumpernickel bagel" after being asked about bagel choice = answers: {"bagel_choice": "pumpernickel"}

CONTEXT CLUES FOR OMELETTE SIDES:
- If context has "omelette_pending: true" or "pending_customization: side_choice" or "pending_customization: bagel_choice":
  - ANY mention of "bagel" = answers: {"side_choice": "bagel"}, NOT a new bagel order
  - ANY bagel type like "plain", "everything", "pumpernickel" = answers: {"bagel_choice": "..."}, NOT a new bagel
  - "fruit salad" = answers: {"side_choice": "fruit_salad"}
- The word "bagel" in response to an omelette side question is NEVER a new bagel order!

CRITICAL: When user ORDERS an omelette, DO NOT pre-fill side_choice or bagel_choice!

ORDER CONFIRMATION:
- ONLY set confirms_order when the pending question is SPECIFICALLY asking about the order summary (e.g., "Does that look right?", "Is that correct?")
- "that's all", "nothing else", "I'm done" are NOT order confirmations - they mean no_more_items: true
- If pending question asks "Does that look right?" and user says:
  - "yes", "looks good", "that's right", "correct", "perfect" -> confirms_order: true
  - "no", "wait", "change", "actually" -> confirms_order: false (user wants to make changes)
- DO NOT set confirms_order: true for "that's all" or similar - that means no_more_items: true, NOT order confirmation

PAYMENT LINK:
- If pending question asks about payment link (e.g., "Do you want me to email you or text you a payment link?"):
  - "yes", "yes please", "email", "text", "send it" -> wants_payment_link: true
  - If user provides an email address (e.g., "john@example.com") -> wants_payment_link: true AND customer_email: "john@example.com"
  - If user provides a phone number -> wants_payment_link: true AND customer_phone: the phone number
  - "no", "no thanks", "I'll pay there", "pay in store", "pay on delivery" -> wants_payment_link: false

CONTEXT: The user may be answering a pending question about their order.
If the message seems like an answer to a question (e.g., "yes", "plain", "small"),
put it in the 'answers' field with the likely field name as key.

MENU QUERIES - CRITICAL:
When user asks about what items are available, set menu_query: true and menu_query_type:
- "what egg sandwiches do you have?" -> menu_query: true, menu_query_type: "egg_sandwich"
- "what fish sandwiches do you have?" -> menu_query: true, menu_query_type: "fish_sandwich"
- "what sandwiches do you have?" -> menu_query: true, menu_query_type: "sandwich"
- "what bagels do you have?" -> menu_query: true, menu_query_type: "bagel"
- "what drinks do you have?" -> menu_query: true, menu_query_type: "drink"
- "what's on the menu?" -> menu_query: true, menu_query_type: "all"
- "what signature sandwiches do you have?" -> menu_query: true, menu_query_type: "signature_sandwich"
- "what sides do you have?" -> menu_query: true, menu_query_type: "side"
- "what type of X do you have?" -> menu_query: true, menu_query_type based on X
Key patterns that indicate menu queries:
- "what ... do you have"
- "what kind of ... do you have"
- "what type of ... do you have"
- "what's on the menu"
- "show me the menu"
- "do you have any ..."
DO NOT set needs_clarification for menu queries - set menu_query instead!

OPTIONS INQUIRY - CRITICAL (Different from menu queries!):
When user asks about CUSTOMIZATION OPTIONS for an item they ordered (or are ordering), use options_inquiry:
- "what cheese can I have on the omelette?" -> options_inquiry: true, options_inquiry_item_type: "omelette", options_inquiry_attribute: "cheese"
- "what are my bagel choices?" -> options_inquiry: true, options_inquiry_item_type: "omelette", options_inquiry_attribute: "bagel_choice"
- "what fillings do you have?" -> options_inquiry: true, options_inquiry_item_type: "omelette", options_inquiry_attribute: "filling"
- "what spreads can I get?" -> options_inquiry: true, options_inquiry_item_type: "bagel", options_inquiry_attribute: "spread"
- "what extras can I add?" -> options_inquiry: true, options_inquiry_item_type: "omelette", options_inquiry_attribute: "extras"
- "can I get different cheese?" -> options_inquiry: true, options_inquiry_attribute: "cheese"
- "what milk options do you have?" -> options_inquiry: true, options_inquiry_item_type: "coffee", options_inquiry_attribute: "milk"

Key difference between menu_query and options_inquiry:
- menu_query: "What omelettes do you have?" (asking about menu ITEMS to order)
- options_inquiry: "What cheese can I have on the omelette?" (asking about OPTIONS for customizing an item)

Common attribute names for options_inquiry_attribute:
- Omelettes: "cheese", "filling", "bagel_choice", "side_choice", "egg_style", "extras"
- Bagels: "spread", "extras", "toasted"
- Coffee: "milk", "sweetener", "size", "flavor_syrup"

DO NOT set menu_query for options inquiries - they are different!

CRITICAL - CLARIFICATION RULES:
- needs_clarification should RARELY be true - only for truly unintelligible messages
- DO NOT set needs_clarification for:
  * Menu items the user orders (even if not on your known list)
  * Answers that seem reasonable in context
  * Requests that can be interpreted (err on the side of interpreting them)
  * Menu queries (use menu_query instead)
- If needs_clarification is true, clarification_needed MUST be a SHORT QUESTION like:
  * "Did you want a bagel or coffee?"
  * "Could you repeat that?"
  * "I didn't catch that, could you try again?"
- NEVER put reasoning, explanations, or interpretations in clarification_needed
- NEVER put the user's order back in clarification_needed
- Example of WRONG: "plain bagel toasted with cream cheese. User may want to build..."
- Example of RIGHT: "Could you repeat that?"
"""


# =============================================================================
# Parsing Function
# =============================================================================

def create_instructor_client() -> instructor.Instructor:
    """Create an instructor-wrapped OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    client = OpenAI(api_key=api_key)
    return instructor.from_openai(client)


def parse_user_message(
    message: str,
    context: dict | None = None,
    pending_question: str | None = None,
    client: instructor.Instructor | None = None,
    model: str = "gpt-4o-mini",
) -> ParsedInput:
    """
    Parse a user message into structured order data.

    Args:
        message: The user's message text
        context: Optional context about current order state
        pending_question: The question we just asked (helps interpret answers)
        client: Optional pre-created instructor client
        model: The model to use for parsing

    Returns:
        ParsedInput with structured data extracted from the message
    """
    if client is None:
        client = create_instructor_client()

    # Build the user prompt with context
    user_prompt = f"User message: {message}"

    if pending_question:
        user_prompt += f"\n\nPending question that was just asked: {pending_question}"

    if context:
        context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
        user_prompt += f"\n\nCurrent order context:\n{context_str}"

    # Parse with instructor
    result = client.chat.completions.create(
        model=model,
        response_model=ParsedInput,
        messages=[
            {"role": "system", "content": PARSING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_retries=2,
    )

    return result


async def parse_user_message_async(
    message: str,
    context: dict | None = None,
    pending_question: str | None = None,
    client: instructor.Instructor | None = None,
    model: str = "gpt-4o-mini",
) -> ParsedInput:
    """
    Async version of parse_user_message.

    Args:
        message: The user's message text
        context: Optional context about current order state
        pending_question: The question we just asked (helps interpret answers)
        client: Optional pre-created instructor client
        model: The model to use for parsing

    Returns:
        ParsedInput with structured data extracted from the message
    """
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        from openai import AsyncOpenAI
        async_client = AsyncOpenAI(api_key=api_key)
        client = instructor.from_openai(async_client)

    # Build the user prompt with context
    user_prompt = f"User message: {message}"

    if pending_question:
        user_prompt += f"\n\nPending question that was just asked: {pending_question}"

    if context:
        context_str = "\n".join(f"- {k}: {v}" for k, v in context.items())
        user_prompt += f"\n\nCurrent order context:\n{context_str}"

    # Parse with instructor
    result = await client.chat.completions.create(
        model=model,
        response_model=ParsedInput,
        messages=[
            {"role": "system", "content": PARSING_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_retries=2,
    )

    return result
