"""
State Machine for Order Flow.

This module provides a deterministic state machine approach to order capture.
Instead of one large parser trying to interpret everything, each state has
its own focused parser that can only produce valid outputs for that state.

Key insight: When pending_item_id points to an incomplete item, ALL input
is interpreted in the context of that item - no new items can be created.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
import instructor
from openai import OpenAI
import os
import logging
import re

from .models import (
    OrderTask,
    MenuItemTask,
    BagelItemTask,
    CoffeeItemTask,
    ItemTask,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# State Definitions
# =============================================================================

class OrderPhase(str, Enum):
    """High-level phases of the order flow."""
    GREETING = "greeting"
    TAKING_ITEMS = "taking_items"
    CONFIGURING_ITEM = "configuring_item"  # Waiting for specific item input
    CHECKOUT_DELIVERY = "checkout_delivery"
    CHECKOUT_NAME = "checkout_name"
    CHECKOUT_CONFIRM = "checkout_confirm"
    CHECKOUT_PAYMENT_METHOD = "checkout_payment_method"  # Ask text or email
    CHECKOUT_EMAIL = "checkout_email"  # Collect email if they want email receipt
    COMPLETE = "complete"
    CANCELLED = "cancelled"


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
}


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


@dataclass
class FlowState:
    """
    Tracks the current state of the order flow.

    The key innovation: pending_item_ids and pending_field tell us exactly
    what we're waiting for, so the parser can be constrained accordingly.
    """
    phase: OrderPhase = OrderPhase.GREETING
    pending_item_ids: list = field(default_factory=list)  # Which items need input (supports multiple)
    pending_field: str | None = None  # Which field we're asking about
    last_bot_message: str | None = None  # For context

    # Legacy single-item property for backwards compatibility
    @property
    def pending_item_id(self) -> str | None:
        """Get the first pending item ID (backwards compat)."""
        return self.pending_item_ids[0] if self.pending_item_ids else None

    @pending_item_id.setter
    def pending_item_id(self, value: str | None):
        """Set a single pending item ID (backwards compat)."""
        if value is None:
            self.pending_item_ids = []
        else:
            self.pending_item_ids = [value]

    def is_configuring_item(self) -> bool:
        """Check if we're waiting for input on a specific item or menu inquiry."""
        # Also handle by-pound category selection (no item, just pending_field)
        if self.pending_field == "by_pound_category":
            return True
        return len(self.pending_item_ids) > 0 and self.pending_field is not None

    def is_configuring_multiple(self) -> bool:
        """Check if we're configuring multiple items at once."""
        return len(self.pending_item_ids) > 1

    def clear_pending(self):
        """Clear pending item/field when done configuring."""
        self.pending_item_ids = []
        self.pending_field = None
        if self.phase == OrderPhase.CONFIGURING_ITEM:
            self.phase = OrderPhase.TAKING_ITEMS


# =============================================================================
# State-Specific Parser Schemas (Pydantic models for instructor)
# =============================================================================

class SideChoiceResponse(BaseModel):
    """Parser output when waiting for omelette side choice."""
    choice: Literal["bagel", "fruit_salad", "unclear"] = Field(
        description="What side the user chose: 'bagel', 'fruit_salad', or 'unclear' if not understood"
    )
    bagel_type: str | None = Field(
        default=None,
        description="If user specified a bagel type (e.g., 'plain bagel' -> 'plain'), capture it here"
    )
    wants_cancel: bool = Field(
        default=False,
        description="User wants to cancel this item or the order"
    )


class BagelChoiceResponse(BaseModel):
    """Parser output when waiting for bagel type selection."""
    bagel_type: str | None = Field(
        default=None,
        description="The type of bagel: plain, everything, sesame, pumpernickel, etc."
    )
    quantity: int = Field(
        default=1,
        description="How many bagels this applies to (e.g., '2 of them plain' -> 2, 'both plain' -> 2)"
    )
    unclear: bool = Field(
        default=False,
        description="Set to true if the bagel type couldn't be determined"
    )


class MultiBagelChoiceResponse(BaseModel):
    """Parser output when waiting for multiple bagel types."""
    bagel_types: list[str] = Field(
        default_factory=list,
        description="List of bagel types in order mentioned (e.g., ['plain', 'cinnamon raisin'])"
    )
    all_same_type: str | None = Field(
        default=None,
        description="If all bagels are the same type, put it here (e.g., 'both plain' -> 'plain')"
    )
    unclear: bool = Field(
        default=False,
        description="Set to true if the bagel types couldn't be determined"
    )


class MultiToastedResponse(BaseModel):
    """Parser output when asking about toasting multiple bagels."""
    all_toasted: bool | None = Field(
        default=None,
        description="True if ALL bagels should be toasted, False if NONE, None if mixed/unclear"
    )
    toasted_list: list[bool] = Field(
        default_factory=list,
        description="List of toasted preferences in order (e.g., [True, False] for 'toast the first one')"
    )


class MultiSpreadResponse(BaseModel):
    """Parser output when asking about spreads for multiple bagels."""
    spreads: list[dict] = Field(
        default_factory=list,
        description="List of spread info in order: [{'spread': 'butter'}, {'spread': 'cream cheese', 'spread_type': 'scallion'}]"
    )
    all_same_spread: str | None = Field(
        default=None,
        description="If all bagels have the same spread (e.g., 'cream cheese on both' -> 'cream cheese')"
    )
    all_same_spread_type: str | None = Field(
        default=None,
        description="If all bagels have the same spread type"
    )


class SpreadChoiceResponse(BaseModel):
    """Parser output when waiting for spread selection."""
    spread: str | None = Field(
        default=None,
        description="The spread choice: cream cheese, butter, none, etc."
    )
    spread_type: str | None = Field(
        default=None,
        description="Specific spread variety if mentioned: scallion, veggie, plain, etc."
    )
    no_spread: bool = Field(
        default=False,
        description="User explicitly doesn't want spread"
    )


class ToastedChoiceResponse(BaseModel):
    """Parser output when waiting for toasted preference."""
    toasted: bool | None = Field(
        default=None,
        description="True if toasted, False if not toasted, None if unclear"
    )


class CoffeeSizeResponse(BaseModel):
    """Parser output when waiting for coffee size."""
    size: str | None = Field(
        default=None,
        description="Coffee size: small, medium, or large"
    )


class CoffeeStyleResponse(BaseModel):
    """Parser output when waiting for hot/iced preference."""
    iced: bool | None = Field(
        default=None,
        description="True if iced, False if hot, None if unclear"
    )


class BagelOrderDetails(BaseModel):
    """Details for a single bagel in an order."""
    bagel_type: str | None = Field(default=None, description="Bagel type (plain, everything, cinnamon raisin, etc.)")
    toasted: bool | None = Field(default=None, description="Whether toasted")
    spread: str | None = Field(default=None, description="Spread (cream cheese, butter, etc.)")
    spread_type: str | None = Field(default=None, description="Spread variety (scallion, veggie, strawberry, etc.)")


class ByPoundOrderItem(BaseModel):
    """A single by-the-pound item being ordered."""
    item_name: str = Field(description="Name of the item (e.g., 'Muenster', 'Nova', 'Tuna Salad')")
    quantity: str = Field(default="1 lb", description="Quantity ordered (e.g., '1 lb', 'half pound', '2 lbs')")
    category: str | None = Field(default=None, description="Category: 'cheese', 'spread', 'cold_cut', 'fish', 'salad'")


class OpenInputResponse(BaseModel):
    """Parser output when open for new items (not configuring a specific item)."""

    # New item orders
    new_menu_item: str | None = Field(
        default=None,
        description="Name of a menu item ordered (e.g., 'The Chipotle Egg Omelette')"
    )
    new_bagel: bool = Field(
        default=False,
        description="User wants to order a bagel"
    )
    new_bagel_quantity: int = Field(
        default=1,
        description="Number of bagels ordered (e.g., 'two bagels' -> 2)"
    )
    new_bagel_type: str | None = Field(
        default=None,
        description="Bagel type if specified (e.g., 'plain', 'everything', 'pumpernickel')"
    )
    new_bagel_toasted: bool | None = Field(
        default=None,
        description="Whether the bagel should be toasted (True if 'toasted' mentioned, False if 'not toasted', None if not specified)"
    )
    new_bagel_spread: str | None = Field(
        default=None,
        description="Spread for the bagel if specified (e.g., 'cream cheese', 'butter')"
    )
    new_bagel_spread_type: str | None = Field(
        default=None,
        description="Specific spread variety if mentioned (e.g., 'scallion', 'veggie', 'plain')"
    )
    # For multiple bagels with different configs specified upfront
    bagel_details: list[BagelOrderDetails] = Field(
        default_factory=list,
        description="When ordering multiple bagels with different configs, list each one separately"
    )
    new_coffee: bool = Field(
        default=False,
        description="User wants to order coffee/drink"
    )
    new_coffee_type: str | None = Field(
        default=None,
        description="Coffee/drink type if specified (drip coffee, latte, cappuccino, etc.)"
    )
    new_coffee_size: str | None = Field(
        default=None,
        description="Coffee size if specified: small, medium, or large"
    )
    new_coffee_iced: bool | None = Field(
        default=None,
        description="True if user wants iced, False if hot, None if not specified"
    )
    new_coffee_milk: str | None = Field(
        default=None,
        description="Milk preference: whole, skim, oat, almond, none/black. 'black' means no milk."
    )
    new_coffee_sweetener: str | None = Field(
        default=None,
        description="Sweetener type: sugar, splenda, stevia, equal, etc."
    )
    new_coffee_sweetener_quantity: int = Field(
        default=1,
        description="Number of sweetener packets (e.g., 'two sugars' = 2)"
    )
    new_coffee_flavor_syrup: str | None = Field(
        default=None,
        description="Flavor syrup: vanilla, caramel, hazelnut, etc."
    )
    new_coffee_quantity: int = Field(
        default=1,
        description="Number of drinks ordered (e.g., '3 diet cokes' -> 3, 'two coffees' -> 2)"
    )

    # Menu inquiries
    asking_signature_menu: bool = Field(
        default=False,
        description="User is asking about signature/speed menu items (e.g., 'what are your speed menu bagels?', 'what signature items do you have?')"
    )
    asking_by_pound: bool = Field(
        default=False,
        description="User is asking what we sell by the pound"
    )
    by_pound_category: str | None = Field(
        default=None,
        description="Specific by-the-pound category user is interested in: 'cheese', 'spread', 'cold_cut', 'fish', 'salad'"
    )

    # By-the-pound orders
    by_pound_items: list[ByPoundOrderItem] = Field(
        default_factory=list,
        description="Items ordered by the pound (e.g., 'a pound of Muenster', 'half pound of nova')"
    )

    # Flow control
    done_ordering: bool = Field(
        default=False,
        description="User is done adding items ('that's all', 'nothing else')"
    )
    wants_cancel: bool = Field(
        default=False,
        description="User wants to cancel"
    )
    is_greeting: bool = Field(
        default=False,
        description="Just a greeting, no order content"
    )
    unclear: bool = Field(
        default=False,
        description="Message couldn't be understood"
    )


class ByPoundCategoryResponse(BaseModel):
    """Parser output when user is selecting a by-the-pound category."""
    category: str | None = Field(
        default=None,
        description="Category selected: 'cheese', 'spread', 'cold_cut', 'fish', 'salad', or None if unclear"
    )
    wants_to_order: str | None = Field(
        default=None,
        description="Specific item user wants to order (e.g., 'muenster cheese', 'nova lox')"
    )
    unclear: bool = Field(
        default=False,
        description="User's response is unclear"
    )


class DeliveryChoiceResponse(BaseModel):
    """Parser output when waiting for pickup/delivery choice."""
    choice: Literal["pickup", "delivery", "unclear"] = Field(
        description="Pickup, delivery, or unclear"
    )
    address: str | None = Field(
        default=None,
        description="Delivery address if provided"
    )


class NameResponse(BaseModel):
    """Parser output when waiting for customer name."""
    name: str | None = Field(
        default=None,
        description="The customer's name"
    )


class ConfirmationResponse(BaseModel):
    """Parser output when waiting for order confirmation."""
    confirmed: bool = Field(
        default=False,
        description="User confirms the order is correct"
    )
    wants_changes: bool = Field(
        default=False,
        description="User wants to make changes"
    )


class PaymentMethodResponse(BaseModel):
    """Parser output when asking how to send order details (text or email)."""
    choice: Literal["text", "email", "unclear"] = Field(
        description="Whether user wants text or email for order details/payment link"
    )
    phone_number: str | None = Field(
        default=None,
        description="Phone number if user provided one"
    )
    email_address: str | None = Field(
        default=None,
        description="Email address if user provided one"
    )


class EmailResponse(BaseModel):
    """Parser output when collecting email address."""
    email: str | None = Field(
        default=None,
        description="The email address provided by the user"
    )


# =============================================================================
# State-Specific Parsers
# =============================================================================

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

Examples:
- "cream cheese" -> spread: "cream cheese"
- "scallion cream cheese" -> spread: "cream cheese", spread_type: "scallion"
- "butter" -> spread: "butter"
- "nothing" or "plain" or "no spread" -> no_spread: true
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
- "medium" / "regular" -> size: "medium"
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


# =============================================================================
# Deterministic Parsing (no LLM)
# =============================================================================

# Word to number mapping
WORD_TO_NUM = {
    "a": 1, "an": 1, "one": 1,
    "two": 2, "couple": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Known bagel types
BAGEL_TYPES = {
    "plain", "everything", "sesame", "poppy", "onion",
    "cinnamon raisin", "cinnamon", "raisin", "pumpernickel",
    "whole wheat", "wheat", "salt", "garlic", "bialy",
    "egg", "multigrain", "asiago", "jalapeno", "blueberry",
}

# Known spreads
SPREADS = {
    "cream cheese", "butter", "peanut butter", "jelly",
    "jam", "nutella", "hummus", "avocado",
}

# Spread types/varieties (exclude "plain" - too ambiguous with bagel type)
SPREAD_TYPES = {
    "scallion", "veggie", "vegetable", "strawberry",
    "honey walnut", "lox", "chive", "garlic herb", "jalapeno",
}

# By-the-pound items (Zucker's specific)
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

# Prices per pound for by-the-pound items
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
# Bagel Modifier Extraction (keyword-based, no LLM)
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
    "olive": "olive cream cheese",
    "honey walnut": "honey walnut cream cheese",
    "tofu": "tofu cream cheese",
    "jalapeno cream cheese": "jalapeño cream cheese",
}


class ExtractedModifiers:
    """Container for modifiers extracted from user input."""

    def __init__(self):
        self.proteins: list[str] = []
        self.cheeses: list[str] = []
        self.toppings: list[str] = []
        self.spreads: list[str] = []

    def has_modifiers(self) -> bool:
        """Check if any modifiers were extracted."""
        return bool(self.proteins or self.cheeses or self.toppings or self.spreads)

    def __repr__(self):
        parts = []
        if self.proteins:
            parts.append(f"proteins={self.proteins}")
        if self.cheeses:
            parts.append(f"cheeses={self.cheeses}")
        if self.toppings:
            parts.append(f"toppings={self.toppings}")
        if self.spreads:
            parts.append(f"spreads={self.spreads}")
        return f"ExtractedModifiers({', '.join(parts)})"


def extract_modifiers_from_input(user_input: str) -> ExtractedModifiers:
    """
    Extract bagel modifiers from user input using keyword matching.

    This is a deterministic, non-LLM approach that scans the input for
    known modifier keywords and extracts them by category.

    Args:
        user_input: The raw user input string

    Returns:
        ExtractedModifiers with lists of found proteins, cheeses, toppings, spreads

    Examples:
        "ham, egg and cheese on a wheat bagel"
        -> proteins=[ham, egg], cheeses=[cheese], toppings=[], spreads=[]

        "everything bagel with scallion cream cheese and tomato"
        -> proteins=[], cheeses=[], toppings=[tomato], spreads=[scallion cream cheese]
    """
    result = ExtractedModifiers()
    input_lower = user_input.lower()

    # Helper to check if a word boundary exists (not part of a larger word)
    def is_word_boundary(text: str, start: int, end: int) -> bool:
        """Check if the match is at word boundaries."""
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end >= len(text) or not text[end].isalnum()
        return before_ok and after_ok

    # Track what we've already matched to avoid duplicates
    matched_spans: list[tuple[int, int]] = []

    def find_and_add(modifier_set: set[str], target_list: list[str], category: str):
        """Find modifiers from a set and add to target list."""
        # Sort by length descending to match longer phrases first
        # (e.g., "scallion cream cheese" before "cream cheese")
        sorted_modifiers = sorted(modifier_set, key=len, reverse=True)

        for modifier in sorted_modifiers:
            # Find all occurrences
            start = 0
            while True:
                pos = input_lower.find(modifier, start)
                if pos == -1:
                    break

                end = pos + len(modifier)

                # Check word boundaries
                if is_word_boundary(input_lower, pos, end):
                    # Check if this span overlaps with already matched spans
                    overlaps = any(
                        not (end <= s or pos >= e) for s, e in matched_spans
                    )
                    if not overlaps:
                        matched_spans.append((pos, end))
                        # Normalize the modifier name
                        normalized = MODIFIER_NORMALIZATIONS.get(modifier, modifier)
                        if normalized not in target_list:
                            target_list.append(normalized)
                            logger.debug(f"Extracted {category}: '{modifier}' -> '{normalized}'")

                start = pos + 1

    # Extract in order of specificity (longer matches first within each category)
    # Process spreads first (they often contain "cream cheese" which could conflict)
    find_and_add(BAGEL_SPREADS, result.spreads, "spread")
    find_and_add(BAGEL_PROTEINS, result.proteins, "protein")
    find_and_add(BAGEL_CHEESES, result.cheeses, "cheese")
    find_and_add(BAGEL_TOPPINGS, result.toppings, "topping")

    # Special case: if user just says "cheese" without a specific type, default to american
    if "cheese" in input_lower and not result.cheeses:
        # Check if "cheese" appears as a standalone word (not part of "cream cheese")
        import re
        cheese_match = re.search(r'\bcheese\b', input_lower)
        if cheese_match:
            pos = cheese_match.start()
            # Make sure it's not part of "cream cheese"
            if "cream cheese" not in input_lower[max(0, pos-6):pos+7]:
                result.cheeses.append("american")
                logger.debug("Extracted cheese: 'cheese' -> 'american' (default)")

    return result


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

# Bagel quantity pattern: matches "3 bagels", "three bagels", "two plain bagels", etc.
# Allows optional bagel type/adjectives between quantity and "bagels"
BAGEL_QUANTITY_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"  # "I want", "I'd like", "can I get"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"  # "can I get"
    r"give\s+me|"  # "give me"
    r"let\s*(?:me|'s)\s*(?:get|have)|"  # "let me get"
    r")?\s*"
    r"(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|couple(?:\s+of)?)\s+"
    r"(?:\w+\s+)*"  # Optional words between quantity and "bagel" (e.g., "plain", "everything")
    r"bagels?",
    re.IGNORECASE
)

# Simple bagel mention without quantity (defaults to 1)
SIMPLE_BAGEL_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(?:a\s+)?bagel(?:\s|$|[.,!?])",
    re.IGNORECASE
)


def _extract_quantity(text: str) -> int | None:
    """Extract quantity from text like '3', 'three', 'a couple of'."""
    text = text.lower().strip()
    # Remove "of" suffix for "couple of"
    text = re.sub(r"\s+of$", "", text)

    # Try numeric
    if text.isdigit():
        return int(text)

    # Try word mapping
    return WORD_TO_NUM.get(text)


def _extract_bagel_type(text: str) -> str | None:
    """Extract bagel type from text."""
    text_lower = text.lower()

    # Check for multi-word types first (e.g., "cinnamon raisin")
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


def _extract_spread(text: str) -> tuple[str | None, str | None]:
    """Extract spread and spread type from text. Returns (spread, spread_type)."""
    text_lower = text.lower()

    spread = None
    spread_type = None

    # Check for spreads
    for s in sorted(SPREADS, key=len, reverse=True):
        if s in text_lower:
            spread = s
            break

    # Check for spread types (e.g., "scallion cream cheese")
    for st in sorted(SPREAD_TYPES, key=len, reverse=True):
        if st in text_lower:
            spread_type = st
            break

    # If we found a spread type but no spread, assume cream cheese
    if spread_type and not spread:
        spread = "cream cheese"

    return spread, spread_type


def parse_open_input_deterministic(user_input: str) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.

    Handles:
    - Greetings: "hi", "hello", etc.
    - Done ordering: "that's all", "nothing else", etc.
    - Simple bagel orders: "3 bagels", "I want two bagels", "a plain bagel toasted"

    Falls back to LLM for:
    - Complex multi-item orders with different configs
    - Menu item orders (need to match against menu)
    - Ambiguous input
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

    # Check for bagel order with quantity
    quantity_match = BAGEL_QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity_str = quantity_match.group(1)
        quantity = _extract_quantity(quantity_str)

        if quantity:
            bagel_type = _extract_bagel_type(text)
            toasted = _extract_toasted(text)
            spread, spread_type = _extract_spread(text)

            logger.debug(
                "Deterministic parse: bagel order - qty=%d, type=%s, toasted=%s, spread=%s/%s",
                quantity, bagel_type, toasted, spread, spread_type
            )

            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=quantity,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
            )

    # Check for simple "a bagel" / "bagel please" (quantity = 1)
    if SIMPLE_BAGEL_PATTERN.search(text):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text)

        logger.debug(
            "Deterministic parse: single bagel - type=%s, toasted=%s, spread=%s/%s",
            bagel_type, toasted, spread, spread_type
        )

        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=1,
            new_bagel_type=bagel_type,
            new_bagel_toasted=toasted,
            new_bagel_spread=spread,
            new_bagel_spread_type=spread_type,
        )

    # Check if text contains "bagel" anywhere - might be a bagel order we can't fully parse
    # but we can at least extract some info
    if re.search(r"\bbagels?\b", text, re.IGNORECASE):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text)

        # Only return if we extracted at least something useful
        if bagel_type or toasted is not None or spread:
            logger.debug(
                "Deterministic parse: bagel mention - type=%s, toasted=%s, spread=%s/%s",
                bagel_type, toasted, spread, spread_type
            )
            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=1,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
            )

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None


def parse_open_input(user_input: str, context: str = "", model: str = "gpt-4o-mini") -> OpenInputResponse:
    """Parse user input when open for new orders.

    Tries deterministic parsing first for speed and consistency.
    Falls back to LLM for complex orders (menu items, multi-config bagels, coffee).
    """
    # Try deterministic parsing first
    result = parse_open_input_deterministic(user_input)
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
- If ordering a specific menu item by name (e.g., "the chipotle egg omelette", "The Leo"),
  set new_menu_item to the item name
- If ordering bagels:
  - Set new_bagel=true
  - Set new_bagel_quantity to the number of bagels (default 1)
  - If ALL bagels are the same, use new_bagel_type, new_bagel_toasted, new_bagel_spread, new_bagel_spread_type
  - If bagels have DIFFERENT configurations, populate bagel_details list with each bagel's config
- If ordering coffee/drink:
  - Set new_coffee=true
  - Set new_coffee_quantity to the number of drinks (e.g., "3 diet cokes" -> 3, "two coffees" -> 2, default 1)
  - Set new_coffee_type if specified (e.g., "latte", "cappuccino", "drip coffee", "diet coke", "coke")
  - Set new_coffee_size if specified ("small", "medium", "large")
  - Set new_coffee_iced=true if they want iced, false if they want hot, null if not specified
  - Set new_coffee_milk if specified (e.g., "oat", "almond", "skim", "whole"). "black" means no milk.
  - Set new_coffee_sweetener if specified (e.g., "sugar", "splenda", "stevia")
  - Set new_coffee_sweetener_quantity for number of sweeteners (e.g., "two sugars" = 2)
  - Set new_coffee_flavor_syrup if specified (e.g., "vanilla", "caramel", "hazelnut")
- If they're done ordering ("that's all", "nothing else", "no", "nope", "I'm good"), set done_ordering=true
- If just greeting ("hi", "hello"), set is_greeting=true

IMPORTANT: When parsing quantities, recognize both spelled-out words AND numeric digits:
- "two" / "2" = 2
- "three" / "3" = 3
- "four" / "4" = 4
- "five" / "5" = 5

Examples:
- "can I get the chipotle egg omelette" -> new_menu_item: "The Chipotle Egg Omelette"
- "I'd like a plain bagel" -> new_bagel: true, new_bagel_quantity: 1, new_bagel_type: "plain"
- "two bagels please" -> new_bagel: true, new_bagel_quantity: 2
- "three bagels" -> new_bagel: true, new_bagel_quantity: 3
- "I want three bagels" -> new_bagel: true, new_bagel_quantity: 3
- "3 bagels please" -> new_bagel: true, new_bagel_quantity: 3
- "four bagels" -> new_bagel: true, new_bagel_quantity: 4
- "I'd like 5 bagels" -> new_bagel: true, new_bagel_quantity: 5
- "two plain bagels toasted" -> new_bagel: true, new_bagel_quantity: 2, new_bagel_type: "plain", new_bagel_toasted: true
- "one plain bagel and one everything bagel" -> new_bagel: true, new_bagel_quantity: 2, bagel_details: [{{bagel_type: "plain"}}, {{bagel_type: "everything"}}]
- "plain bagel with butter and cinnamon raisin with cream cheese" -> new_bagel: true, new_bagel_quantity: 2, bagel_details: [{{bagel_type: "plain", spread: "butter"}}, {{bagel_type: "cinnamon raisin", spread: "cream cheese"}}]
- "two everything bagels with scallion cream cheese toasted" -> new_bagel: true, new_bagel_quantity: 2, new_bagel_type: "everything", new_bagel_toasted: true, new_bagel_spread: "cream cheese", new_bagel_spread_type: "scallion"
- "coffee please" -> new_coffee: true
- "a large latte" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "large"
- "medium iced coffee" -> new_coffee: true, new_coffee_size: "medium", new_coffee_iced: true
- "small hot latte" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "small", new_coffee_iced: false
- "iced cappuccino" -> new_coffee: true, new_coffee_type: "cappuccino", new_coffee_iced: true
- "small coffee black with two sugars" -> new_coffee: true, new_coffee_size: "small", new_coffee_milk: "none", new_coffee_sweetener: "sugar", new_coffee_sweetener_quantity: 2
- "large latte with oat milk" -> new_coffee: true, new_coffee_type: "latte", new_coffee_size: "large", new_coffee_milk: "oat"
- "medium coffee with vanilla syrup" -> new_coffee: true, new_coffee_size: "medium", new_coffee_flavor_syrup: "vanilla"
- "small coffee black with two sugars and vanilla syrup" -> new_coffee: true, new_coffee_size: "small", new_coffee_milk: "none", new_coffee_sweetener: "sugar", new_coffee_sweetener_quantity: 2, new_coffee_flavor_syrup: "vanilla"
- "iced latte with almond milk and caramel" -> new_coffee: true, new_coffee_type: "latte", new_coffee_iced: true, new_coffee_milk: "almond", new_coffee_flavor_syrup: "caramel"
- "3 diet cokes" -> new_coffee: true, new_coffee_type: "diet coke", new_coffee_quantity: 3
- "two coffees" -> new_coffee: true, new_coffee_quantity: 2
- "three lattes" -> new_coffee: true, new_coffee_type: "latte", new_coffee_quantity: 3
- "2 iced coffees" -> new_coffee: true, new_coffee_iced: true, new_coffee_quantity: 2
- "a coke" -> new_coffee: true, new_coffee_type: "coke", new_coffee_quantity: 1
- "that's all" -> done_ordering: true

Signature/Speed menu inquiries:
- If user asks about signature items, speed menu, or pre-made options -> asking_signature_menu: true
  - "what are your speed menu bagels" -> asking_signature_menu: true
  - "what speed menu options do you have" -> asking_signature_menu: true
  - "what signature bagels do you have" -> asking_signature_menu: true
  - "what are the signature items" -> asking_signature_menu: true
  - "tell me about the speed menu" -> asking_signature_menu: true
  - "what pre-made bagels do you have" -> asking_signature_menu: true

By-the-pound inquiries:
- If user asks "what do you sell by the pound" or "do you have anything by the pound" -> asking_by_pound: true
- If user asks about a specific category by the pound, also set by_pound_category:
  - "what cheeses do you have" or "I'm interested in cheese" -> asking_by_pound: true, by_pound_category: "cheese"
  - "what spreads do you sell by the pound" -> asking_by_pound: true, by_pound_category: "spread"
  - "what cold cuts do you have" -> asking_by_pound: true, by_pound_category: "cold_cut"
  - "what fish do you sell" or "what smoked fish" -> asking_by_pound: true, by_pound_category: "fish"
  - "what salads do you have by the pound" -> asking_by_pound: true, by_pound_category: "salad"

By-the-pound ORDERS (user is ordering, not asking):
- If user orders items by the pound, populate by_pound_items list with each item:
  - "give me a pound of Muenster" -> by_pound_items: [{{item_name: "Muenster", quantity: "1 lb", category: "cheese"}}]
  - "a pound of Muenster and a pound of Provolone" -> by_pound_items: [{{item_name: "Muenster", quantity: "1 lb", category: "cheese"}}, {{item_name: "Provolone", quantity: "1 lb", category: "cheese"}}]
  - "half pound of nova" -> by_pound_items: [{{item_name: "Nova", quantity: "half lb", category: "fish"}}]
  - "two pounds of turkey" -> by_pound_items: [{{item_name: "Turkey", quantity: "2 lbs", category: "cold_cut"}}]
  - "I'll take the muenster and the swiss" -> by_pound_items: [{{item_name: "Muenster", quantity: "1 lb", category: "cheese"}}, {{item_name: "Swiss", quantity: "1 lb", category: "cheese"}}]
  - "give me a pound of tuna salad" -> by_pound_items: [{{item_name: "Tuna Salad", quantity: "1 lb", category: "salad"}}]
  - "a quarter pound of lox" -> by_pound_items: [{{item_name: "Lox", quantity: "quarter lb", category: "fish"}}]
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

    prompt = f"""We asked the user if they want their order details sent by text or email.
The user said: "{user_input}"

Examples:
- "text" / "text me" / "sms" -> choice: "text"
- "email" / "email me" / "send me an email" -> choice: "email"
- "text me at 555-1234" -> choice: "text", phone_number: "555-1234"
- "email it to john@example.com" -> choice: "email", email_address: "john@example.com"
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


# =============================================================================
# State Machine
# =============================================================================

@dataclass
class StateMachineResult:
    """Result from state machine processing."""
    message: str
    state: FlowState
    order: OrderTask
    is_complete: bool = False


class OrderStateMachine:
    """
    State machine for order capture.

    The key principle: when we're waiting for input on a specific item
    (pending_item_id is set), we use a constrained parser that can ONLY
    interpret input as answers for that item. No new items can be created.
    """

    def __init__(self, menu_data: dict | None = None, model: str = "gpt-4o-mini"):
        self.menu_data = menu_data or {}
        self.model = model

    def process(
        self,
        user_input: str,
        state: FlowState | None = None,
        order: OrderTask | None = None,
    ) -> StateMachineResult:
        """
        Process user input through the state machine.

        Args:
            user_input: What the user said
            state: Current flow state (None for new conversation)
            order: Current order (None for new conversation)

        Returns:
            StateMachineResult with response message, updated state, and order
        """
        if state is None:
            state = FlowState()
        if order is None:
            order = OrderTask()

        # Add user message to history
        order.add_message("user", user_input)

        # Route to appropriate handler based on state
        if state.is_configuring_item():
            result = self._handle_configuring_item(user_input, state, order)
        elif state.phase == OrderPhase.GREETING:
            result = self._handle_greeting(user_input, state, order)
        elif state.phase == OrderPhase.TAKING_ITEMS:
            result = self._handle_taking_items(user_input, state, order)
        elif state.phase == OrderPhase.CHECKOUT_DELIVERY:
            result = self._handle_delivery(user_input, state, order)
        elif state.phase == OrderPhase.CHECKOUT_NAME:
            result = self._handle_name(user_input, state, order)
        elif state.phase == OrderPhase.CHECKOUT_CONFIRM:
            result = self._handle_confirmation(user_input, state, order)
        elif state.phase == OrderPhase.CHECKOUT_PAYMENT_METHOD:
            result = self._handle_payment_method(user_input, state, order)
        elif state.phase == OrderPhase.CHECKOUT_EMAIL:
            result = self._handle_email(user_input, state, order)
        else:
            result = StateMachineResult(
                message="I'm not sure what to do. Can you try again?",
                state=state,
                order=order,
            )

        # Add bot message to history
        order.add_message("assistant", result.message)

        return result

    def _handle_greeting(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(user_input, model=self.model)

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, new_bagel=%s, quantity=%d",
            parsed.is_greeting,
            parsed.unclear,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
        )

        if parsed.is_greeting or parsed.unclear:
            state.phase = OrderPhase.TAKING_ITEMS
            return StateMachineResult(
                message="Hi! Welcome to Zucker's. What can I get for you today?",
                state=state,
                order=order,
            )

        # User might have ordered something directly - pass the already parsed result
        # Also extract modifiers from the raw input
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from greeting input: %s", extracted_modifiers)

        state.phase = OrderPhase.TAKING_ITEMS
        return self._handle_taking_items_with_parsed(parsed, state, order, extracted_modifiers)

    def _handle_taking_items(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle taking new item orders."""
        parsed = parse_open_input(user_input, model=self.model)

        # Extract modifiers from raw input (keyword-based, no LLM)
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from input: %s", extracted_modifiers)

        return self._handle_taking_items_with_parsed(parsed, state, order, extracted_modifiers)

    def _handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        state: FlowState,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """Handle taking new item orders with already-parsed input."""
        logger.info(
            "Parsed open input: new_menu_item='%s', new_bagel=%s, quantity=%d, bagel_details=%d, done_ordering=%s",
            parsed.new_menu_item,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
            len(parsed.bagel_details),
            parsed.done_ordering,
        )

        if parsed.done_ordering:
            return self._transition_to_checkout(state, order)

        if parsed.new_menu_item:
            return self._add_menu_item(parsed.new_menu_item, state, order)

        if parsed.new_bagel:
            # Check if we have multiple bagels with different configs
            if parsed.bagel_details and len(parsed.bagel_details) > 0:
                # Multiple bagels with different configurations
                # Pass extracted_modifiers to apply to the first bagel
                return self._add_bagels_from_details(
                    parsed.bagel_details, state, order, extracted_modifiers
                )
            elif parsed.new_bagel_quantity > 1:
                # Multiple bagels with same (or no) configuration
                # Pass extracted_modifiers to apply to the first bagel
                return self._add_bagels(
                    quantity=parsed.new_bagel_quantity,
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    state=state,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            else:
                # Single bagel
                return self._add_bagel(
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    state=state,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )

        if parsed.new_coffee:
            return self._add_coffee(
                parsed.new_coffee_type,
                parsed.new_coffee_size,
                parsed.new_coffee_iced,
                parsed.new_coffee_milk,
                parsed.new_coffee_sweetener,
                parsed.new_coffee_sweetener_quantity,
                parsed.new_coffee_flavor_syrup,
                parsed.new_coffee_quantity,
                state,
                order,
            )

        if parsed.asking_signature_menu:
            return self._handle_signature_menu_inquiry(state, order)

        if parsed.asking_by_pound:
            return self._handle_by_pound_inquiry(parsed.by_pound_category, state, order)

        if parsed.by_pound_items:
            return self._add_by_pound_items(parsed.by_pound_items, state, order)

        if parsed.unclear or parsed.is_greeting:
            return StateMachineResult(
                message="What can I get for you?",
                state=state,
                order=order,
            )

        return StateMachineResult(
            message="I didn't catch that. What would you like to order?",
            state=state,
            order=order,
        )

    def _handle_configuring_item(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Handle input when configuring a specific item.

        THIS IS THE KEY: we use state-specific parsers that can ONLY
        interpret input as answers for the pending field. No new items.
        """
        # Handle by-pound category selection (no item required)
        if state.pending_field == "by_pound_category":
            return self._handle_by_pound_category_selection(user_input, state, order)

        item = self._get_item_by_id(order, state.pending_item_id)
        if item is None:
            state.clear_pending()
            return StateMachineResult(
                message="Something went wrong. What would you like to order?",
                state=state,
                order=order,
            )

        # Route to field-specific handler
        if state.pending_field == "side_choice":
            return self._handle_side_choice(user_input, item, state, order)
        elif state.pending_field == "bagel_choice":
            return self._handle_bagel_choice(user_input, item, state, order)
        elif state.pending_field == "spread":
            return self._handle_spread_choice(user_input, item, state, order)
        elif state.pending_field == "toasted":
            return self._handle_toasted_choice(user_input, item, state, order)
        elif state.pending_field == "coffee_size":
            return self._handle_coffee_size(user_input, item, state, order)
        elif state.pending_field == "coffee_style":
            return self._handle_coffee_style(user_input, item, state, order)
        else:
            state.clear_pending()
            return self._get_next_question(state, order)

    def _handle_side_choice(
        self,
        user_input: str,
        item: MenuItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle side choice for omelette - uses constrained parser."""
        # This parser can ONLY return side choice - no new items possible!
        parsed = parse_side_choice(user_input, item.menu_item_name, model=self.model)

        if parsed.wants_cancel:
            item.mark_skipped()
            state.clear_pending()
            return StateMachineResult(
                message="No problem, I've removed that. Anything else?",
                state=state,
                order=order,
            )

        if parsed.choice == "unclear":
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {item.menu_item_name}?",
                state=state,
                order=order,
            )

        # Apply the choice
        item.side_choice = parsed.choice

        if parsed.choice == "bagel":
            if parsed.bagel_type:
                # User specified bagel type upfront (e.g., "plain bagel")
                item.bagel_choice = parsed.bagel_type
                state.clear_pending()
                item.mark_complete()
                return self._get_next_question(state, order)
            else:
                # Need to ask for bagel type
                state.pending_field = "bagel_choice"
                return StateMachineResult(
                    message="What kind of bagel would you like?",
                    state=state,
                    order=order,
                )
        else:
            # Fruit salad - omelette is complete
            state.clear_pending()
            item.mark_complete()
            return self._get_next_question(state, order)

    def _handle_bagel_choice(
        self,
        user_input: str,
        item: ItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle bagel type selection - uses constrained parser."""
        # Count how many bagels still need a type
        bagels_needing_type = [
            b for b in order.items.items
            if isinstance(b, BagelItemTask) and b.status == TaskStatus.IN_PROGRESS and not b.bagel_type
        ]
        num_pending = len(bagels_needing_type)

        parsed = parse_bagel_choice(user_input, num_pending_bagels=num_pending, model=self.model)

        if parsed.unclear or not parsed.bagel_type:
            return StateMachineResult(
                message="What kind of bagel? We have plain, everything, sesame, and more.",
                state=state,
                order=order,
            )

        # Apply to the item (could be omelette's bagel_choice or bagel's bagel_type)
        if isinstance(item, MenuItemTask):
            item.bagel_choice = parsed.bagel_type
            item.mark_complete()
            state.clear_pending()
            return self._get_next_question(state, order)

        elif isinstance(item, BagelItemTask):
            # Look up price for this bagel type
            price = self._lookup_bagel_price(parsed.bagel_type)

            # How many bagels to apply this type to?
            quantity_to_apply = min(parsed.quantity, num_pending)

            logger.info(
                "Applying bagel type '%s' to %d bagel(s) (parsed quantity: %d, pending: %d)",
                parsed.bagel_type, quantity_to_apply, parsed.quantity, num_pending
            )

            # Apply to the specified number of bagels
            applied_count = 0
            for bagel in bagels_needing_type:
                if applied_count >= quantity_to_apply:
                    break
                bagel.bagel_type = parsed.bagel_type
                bagel.unit_price = price
                applied_count += 1

            # Clear pending state - we'll reconfigure from scratch
            state.clear_pending()

            # Now configure the next incomplete bagel (could be one we just typed, needing toasted)
            return self._configure_next_incomplete_bagel(state, order)

        return self._get_next_question(state, order)

    def _handle_spread_choice(
        self,
        user_input: str,
        item: BagelItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle spread selection for bagel."""
        parsed = parse_spread_choice(user_input, model=self.model)

        if parsed.no_spread:
            item.spread = "none"  # Mark as explicitly no spread
        elif parsed.spread:
            item.spread = parsed.spread
            item.spread_type = parsed.spread_type
        else:
            return StateMachineResult(
                message="Would you like cream cheese, butter, or nothing on that?",
                state=state,
                order=order,
            )

        # Recalculate price to include spread modifier
        self.recalculate_bagel_price(item)

        # This bagel is complete
        item.mark_complete()
        state.clear_pending()

        # Check for more incomplete bagels
        return self._configure_next_incomplete_bagel(state, order)

    def _handle_toasted_choice(
        self,
        user_input: str,
        item: BagelItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for bagel."""
        parsed = parse_toasted_choice(user_input, model=self.model)

        if parsed.toasted is None:
            return StateMachineResult(
                message="Would you like that toasted? Yes or no?",
                state=state,
                order=order,
            )

        item.toasted = parsed.toasted

        # Move to spread question
        state.pending_field = "spread"
        return StateMachineResult(
            message="Would you like cream cheese or butter on that?",
            state=state,
            order=order,
        )

    def _handle_delivery(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle pickup/delivery selection."""
        parsed = parse_delivery_choice(user_input, model=self.model)

        if parsed.choice == "unclear":
            return StateMachineResult(
                message="Is this for pickup or delivery?",
                state=state,
                order=order,
            )

        order.delivery_method.order_type = parsed.choice
        if parsed.address:
            order.delivery_method.address.street = parsed.address

        state.phase = OrderPhase.CHECKOUT_NAME
        return StateMachineResult(
            message="Can I get a name for the order?",
            state=state,
            order=order,
        )

    def _handle_name(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle customer name."""
        parsed = parse_name(user_input, model=self.model)

        if not parsed.name:
            return StateMachineResult(
                message="What name should I put on the order?",
                state=state,
                order=order,
            )

        order.customer_info.name = parsed.name
        state.phase = OrderPhase.CHECKOUT_CONFIRM

        # Build order summary
        summary = self._build_order_summary(order)
        return StateMachineResult(
            message=f"{summary}\n\nDoes that look right?",
            state=state,
            order=order,
        )

    def _handle_confirmation(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle order confirmation."""
        parsed = parse_confirmation(user_input, model=self.model)

        if parsed.wants_changes:
            state.phase = OrderPhase.TAKING_ITEMS
            return StateMachineResult(
                message="No problem. What would you like to change?",
                state=state,
                order=order,
            )

        if parsed.confirmed:
            # Mark order as reviewed but not yet fully confirmed
            # (confirmed=True is set only when order is complete with email/text choice)
            order.checkout.order_reviewed = True
            state.phase = OrderPhase.CHECKOUT_PAYMENT_METHOD
            return StateMachineResult(
                message="Would you like your order details sent by text or email?",
                state=state,
                order=order,
            )

        return StateMachineResult(
            message="Does the order look correct?",
            state=state,
            order=order,
        )

    def _handle_payment_method(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle text or email choice for order details."""
        parsed = parse_payment_method(user_input, model=self.model)

        if parsed.choice == "unclear":
            return StateMachineResult(
                message="Would you like your order confirmation sent by text message or email?",
                state=state,
                order=order,
            )

        if parsed.choice == "text":
            # Text selected - generate order number and complete
            order.payment.payment_link_destination = parsed.phone_number or order.customer_info.phone
            order.checkout.generate_order_number()
            order.checkout.confirmed = True  # Now fully confirmed
            state.phase = OrderPhase.COMPLETE
            return StateMachineResult(
                message=f"Your order number is {order.checkout.short_order_number}. "
                       f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
                state=state,
                order=order,
                is_complete=True,
            )

        if parsed.choice == "email":
            # Email selected - check if we got email with the response
            if parsed.email_address:
                order.customer_info.email = parsed.email_address
                order.payment.payment_link_destination = parsed.email_address
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                state.phase = OrderPhase.COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll send the confirmation to {parsed.email_address}. "
                           f"Thank you, {order.customer_info.name}!",
                    state=state,
                    order=order,
                    is_complete=True,
                )
            else:
                # Need to ask for email
                state.phase = OrderPhase.CHECKOUT_EMAIL
                return StateMachineResult(
                    message="What email address should I send it to?",
                    state=state,
                    order=order,
                )

        return StateMachineResult(
            message="Would you like that sent by text or email?",
            state=state,
            order=order,
        )

    def _handle_email(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle email address collection."""
        parsed = parse_email(user_input, model=self.model)

        if not parsed.email:
            return StateMachineResult(
                message="What's the best email address to send the order confirmation to?",
                state=state,
                order=order,
            )

        # Store email and complete the order
        order.customer_info.email = parsed.email
        order.payment.payment_link_destination = parsed.email
        order.checkout.generate_order_number()
        order.checkout.confirmed = True  # Now fully confirmed
        state.phase = OrderPhase.COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll send the confirmation to {parsed.email}. "
                   f"Thank you, {order.customer_info.name}!",
            state=state,
            order=order,
            is_complete=True,
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _add_menu_item(
        self,
        item_name: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add a menu item and determine next question."""
        # Look up item in menu to get price and other details
        menu_item = self._lookup_menu_item(item_name)

        # Log omelette items in menu for debugging
        omelette_items = self.menu_data.get("items_by_type", {}).get("omelette", [])
        logger.info(
            "Menu lookup for '%s': found=%s, omelette_items=%s",
            item_name,
            menu_item is not None,
            [i.get("name") for i in omelette_items],
        )

        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name) if menu_item else item_name
        price = menu_item.get("base_price", 0.0) if menu_item else 0.0
        menu_item_id = menu_item.get("id") if menu_item else None

        # Check if it's an omelette (requires side choice)
        is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()

        logger.info(
            "Omelette check: canonical_name='%s', is_omelette=%s",
            canonical_name,
            is_omelette,
        )

        item = MenuItemTask(
            menu_item_name=canonical_name,
            menu_item_id=menu_item_id,
            unit_price=price,
            requires_side_choice=is_omelette,
            menu_item_type="omelette" if is_omelette else None,
        )
        item.mark_in_progress()
        order.items.add_item(item)

        logger.info("Added menu item: %s (price: $%.2f, id: %s)", canonical_name, price, menu_item_id)

        if is_omelette:
            # Set state to wait for side choice
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = item.id
            state.pending_field = "side_choice"
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {item_name}?",
                state=state,
                order=order,
            )
        else:
            item.mark_complete()
            return self._get_next_question(state, order)

    def _add_bagel(
        self,
        bagel_type: str | None,
        state: FlowState,
        order: OrderTask,
        toasted: bool | None = None,
        spread: str | None = None,
        spread_type: str | None = None,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """Add a bagel and start configuration, pre-filling any provided details."""
        # Look up base bagel price from menu
        base_price = self._lookup_bagel_price(bagel_type)

        # Build extras list from extracted modifiers
        extras: list[str] = []
        sandwich_protein: str | None = None

        if extracted_modifiers and extracted_modifiers.has_modifiers():
            # First protein goes to sandwich_protein field
            if extracted_modifiers.proteins:
                sandwich_protein = extracted_modifiers.proteins[0]
                # Additional proteins go to extras
                extras.extend(extracted_modifiers.proteins[1:])

            # Cheeses go to extras
            extras.extend(extracted_modifiers.cheeses)

            # Toppings go to extras
            extras.extend(extracted_modifiers.toppings)

            # If modifiers include a spread, use it (unless already specified)
            if not spread and extracted_modifiers.spreads:
                spread = extracted_modifiers.spreads[0]

            logger.info(
                "Extracted modifiers: protein=%s, extras=%s, spread=%s",
                sandwich_protein, extras, spread
            )

        # Calculate total price including modifiers
        price = self._calculate_bagel_price_with_modifiers(
            base_price, sandwich_protein, extras, spread
        )
        logger.info(
            "Bagel price: base=$%.2f, total=$%.2f (with modifiers)",
            base_price, price
        )

        # Create bagel with all provided details
        bagel = BagelItemTask(
            bagel_type=bagel_type,
            toasted=toasted,
            spread=spread,
            spread_type=spread_type,
            sandwich_protein=sandwich_protein,
            extras=extras,
            unit_price=price,
        )
        bagel.mark_in_progress()
        order.items.add_item(bagel)

        logger.info(
            "Adding bagel: type=%s, toasted=%s, spread=%s, spread_type=%s, protein=%s, extras=%s",
            bagel_type, toasted, spread, spread_type, sandwich_protein, extras
        )

        # Determine what question to ask based on what's missing
        # Flow: bagel_type -> toasted -> spread

        if not bagel_type:
            # Need bagel type
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = bagel.id
            state.pending_field = "bagel_choice"
            return StateMachineResult(
                message="What kind of bagel would you like?",
                state=state,
                order=order,
            )

        if toasted is None:
            # Need toasted preference
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = bagel.id
            state.pending_field = "toasted"
            return StateMachineResult(
                message="Would you like that toasted?",
                state=state,
                order=order,
            )

        if spread is None:
            # Need spread choice
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = bagel.id
            state.pending_field = "spread"
            return StateMachineResult(
                message="Would you like cream cheese or butter on that?",
                state=state,
                order=order,
            )

        # All details provided - bagel is complete!
        bagel.mark_complete()
        return self._get_next_question(state, order)

    def _add_bagels(
        self,
        quantity: int,
        bagel_type: str | None,
        toasted: bool | None,
        spread: str | None,
        spread_type: str | None,
        state: FlowState,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with the same configuration.

        Creates all bagels upfront, then configures them one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info(
            "Adding %d bagels: type=%s, toasted=%s, spread=%s, spread_type=%s",
            quantity, bagel_type, toasted, spread, spread_type
        )

        # Look up base bagel price from menu
        base_price = self._lookup_bagel_price(bagel_type)

        # Create all the bagels
        for i in range(quantity):
            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            bagel_spread = spread

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not bagel_spread and extracted_modifiers.spreads:
                    bagel_spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, bagel_spread
                )

            # Calculate total price including modifiers (for first bagel with modifiers)
            price = self._calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, bagel_spread
            )

            bagel = BagelItemTask(
                bagel_type=bagel_type,
                toasted=toasted,
                spread=bagel_spread,
                spread_type=spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
            )
            # Mark complete if all fields provided, otherwise in_progress
            if bagel_type and toasted is not None and bagel_spread is not None:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()
            order.items.add_item(bagel)

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(state, order)

    def _add_bagels_from_details(
        self,
        bagel_details: list[BagelOrderDetails],
        state: FlowState,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
    ) -> StateMachineResult:
        """
        Add multiple bagels with different configurations.

        Creates all bagels upfront, then configures incomplete ones one at a time.
        Extracted modifiers are applied to the first bagel.
        """
        logger.info("Adding %d bagels from details", len(bagel_details))

        for i, details in enumerate(bagel_details):
            # Look up base price
            base_price = 2.50
            if details.bagel_type:
                bagel_name = f"{details.bagel_type.title()} Bagel" if "bagel" not in details.bagel_type.lower() else details.bagel_type
                menu_item = self._lookup_menu_item(bagel_name)
                if menu_item:
                    base_price = menu_item.get("base_price", 2.50)

            # Build extras list from extracted modifiers (apply to first bagel only)
            extras: list[str] = []
            sandwich_protein: str | None = None
            spread = details.spread

            if i == 0 and extracted_modifiers and extracted_modifiers.has_modifiers():
                # First protein goes to sandwich_protein field
                if extracted_modifiers.proteins:
                    sandwich_protein = extracted_modifiers.proteins[0]
                    # Additional proteins go to extras
                    extras.extend(extracted_modifiers.proteins[1:])

                # Cheeses go to extras
                extras.extend(extracted_modifiers.cheeses)

                # Toppings go to extras
                extras.extend(extracted_modifiers.toppings)

                # If modifiers include a spread, use it (unless already specified)
                if not spread and extracted_modifiers.spreads:
                    spread = extracted_modifiers.spreads[0]

                logger.info(
                    "Applying extracted modifiers to first bagel: protein=%s, extras=%s, spread=%s",
                    sandwich_protein, extras, spread
                )

            # Calculate total price including modifiers
            price = self._calculate_bagel_price_with_modifiers(
                base_price, sandwich_protein, extras, spread
            )

            bagel = BagelItemTask(
                bagel_type=details.bagel_type,
                toasted=details.toasted,
                spread=spread,
                spread_type=details.spread_type,
                sandwich_protein=sandwich_protein,
                extras=extras,
                unit_price=price,
            )

            # Mark complete if all fields provided
            if details.bagel_type and details.toasted is not None and details.spread is not None:
                bagel.mark_complete()
            else:
                bagel.mark_in_progress()

            order.items.add_item(bagel)

            logger.info(
                "Bagel %d: type=%s, toasted=%s, spread=%s (status=%s)",
                i + 1, details.bagel_type, details.toasted, details.spread,
                bagel.status.value
            )

        # Find first incomplete bagel and start configuring it
        return self._configure_next_incomplete_bagel(state, order)

    def _get_bagel_descriptions(self, order: OrderTask, bagel_ids: list[str]) -> list[str]:
        """Get descriptions for a list of bagel IDs (e.g., ['plain bagel', 'everything bagel'])."""
        descriptions = []
        for bagel_id in bagel_ids:
            bagel = self._get_item_by_id(order, bagel_id)
            if bagel and isinstance(bagel, BagelItemTask):
                if bagel.bagel_type:
                    descriptions.append(f"{bagel.bagel_type} bagel")
                else:
                    descriptions.append("bagel")
        return descriptions

    def _configure_next_incomplete_bagel(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """
        Find the next incomplete bagel and configure it fully before moving on.

        This enables one-at-a-time configuration for multiple bagels.
        Each bagel is fully configured (type → toasted → spread) before
        moving to the next bagel.
        """
        # Count bagels and find incomplete ones
        all_bagels = [item for item in order.items.items if isinstance(item, BagelItemTask)]
        total_bagels = len(all_bagels)

        # Find the first incomplete bagel and ask about its next missing field
        for idx, item in enumerate(all_bagels):
            if item.status != TaskStatus.IN_PROGRESS:
                continue

            bagel = item
            bagel_num = idx + 1

            # Build ordinal descriptor if multiple bagels
            if total_bagels > 1:
                ordinal = self._get_ordinal(bagel_num)
                bagel_desc = f"the {ordinal} bagel"
                your_bagel_desc = f"your {ordinal} bagel"
            else:
                bagel_desc = "your bagel"
                your_bagel_desc = "your bagel"

            # Ask about type first
            if not bagel.bagel_type:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = bagel.id
                state.pending_field = "bagel_choice"
                return StateMachineResult(
                    message=f"What kind of bagel for {bagel_desc}?",
                    state=state,
                    order=order,
                )

            # Then ask about toasted
            if bagel.toasted is None:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = bagel.id
                state.pending_field = "toasted"
                return StateMachineResult(
                    message=f"Would you like {your_bagel_desc} toasted?",
                    state=state,
                    order=order,
                )

            # Then ask about spread
            if bagel.spread is None:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = bagel.id
                state.pending_field = "spread"
                return StateMachineResult(
                    message=f"Would you like cream cheese or butter on {your_bagel_desc}?",
                    state=state,
                    order=order,
                )

            # This bagel is complete, mark it and continue to next
            bagel.mark_complete()

        # No incomplete bagels, ask if they want anything else
        return self._get_next_question(state, order)

    def _get_ordinal(self, n: int) -> str:
        """Convert number to ordinal (1 -> 'first', 2 -> 'second', etc.)."""
        ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return ordinals.get(n, f"#{n}")

    def _add_coffee(
        self,
        coffee_type: str | None,
        size: str | None,
        iced: bool | None,
        milk: str | None,
        sweetener: str | None,
        sweetener_quantity: int,
        flavor_syrup: str | None,
        quantity: int,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add coffee/drink(s) and start configuration flow if needed."""
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item from menu to get price and skip_config flag
        menu_item = self._lookup_menu_item(coffee_type) if coffee_type else None
        price = menu_item.get("base_price", 2.50) if menu_item else self._lookup_coffee_price(coffee_type)

        # Check if this drink should skip configuration questions
        # Priority: 1) skip_config flag from database, 2) hardcoded soda list fallback
        should_skip_config = False
        if menu_item and menu_item.get("skip_config"):
            should_skip_config = True
        elif is_soda_drink(coffee_type):
            # Fallback for items not in database
            should_skip_config = True

        if should_skip_config:
            # This drink doesn't need size or hot/iced questions - add directly as complete
            # Create the requested quantity of drinks
            for _ in range(quantity):
                drink = CoffeeItemTask(
                    drink_type=coffee_type,
                    size=None,  # No size options for skip_config drinks
                    iced=None,  # No hot/iced label needed for sodas/bottled drinks
                    milk=None,
                    sweetener=None,
                    sweetener_quantity=0,
                    flavor_syrup=None,
                    unit_price=price,
                )
                drink.mark_complete()  # No configuration needed
                order.items.add_item(drink)

            # Return to taking items
            state.clear_pending()
            return self._get_next_question(state, order)

        # Regular coffee/tea - needs configuration
        # Create the requested quantity of drinks
        for _ in range(quantity):
            coffee = CoffeeItemTask(
                drink_type=coffee_type or "coffee",
                size=size,
                iced=iced,
                milk=milk,
                sweetener=sweetener,
                sweetener_quantity=sweetener_quantity,
                flavor_syrup=flavor_syrup,
                unit_price=price,
            )
            coffee.mark_in_progress()
            order.items.add_item(coffee)

        # Start configuration flow
        return self._configure_next_incomplete_coffee(state, order)

    def _configure_next_incomplete_coffee(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete coffee item."""
        # Find incomplete coffee items
        all_coffees = [
            item for item in order.items.items
            if isinstance(item, CoffeeItemTask) and item.status == TaskStatus.IN_PROGRESS
        ]

        if not all_coffees:
            state.clear_pending()
            return self._get_next_question(state, order)

        # Configure coffees one at a time (fully configure each before moving to next)
        for coffee in all_coffees:
            # Ask about size first
            if not coffee.size:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = coffee.id
                state.pending_field = "coffee_size"
                return StateMachineResult(
                    message="What size would you like? Small, medium, or large?",
                    state=state,
                    order=order,
                )

            # Then ask about hot/iced
            if coffee.iced is None:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = coffee.id
                state.pending_field = "coffee_style"
                return StateMachineResult(
                    message="Would you like that hot or iced?",
                    state=state,
                    order=order,
                )

            # This coffee is complete
            coffee.mark_complete()

        # All coffees configured
        state.clear_pending()
        return self._get_next_question(state, order)

    def _handle_coffee_size(
        self,
        user_input: str,
        item: CoffeeItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle coffee size selection."""
        parsed = parse_coffee_size(user_input, model=self.model)

        if not parsed.size:
            return StateMachineResult(
                message="What size would you like? Small, medium, or large?",
                state=state,
                order=order,
            )

        item.size = parsed.size

        # Move to hot/iced question
        state.pending_field = "coffee_style"
        return StateMachineResult(
            message="Would you like that hot or iced?",
            state=state,
            order=order,
        )

    def _handle_coffee_style(
        self,
        user_input: str,
        item: CoffeeItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle hot/iced preference for coffee."""
        parsed = parse_coffee_style(user_input, model=self.model)

        if parsed.iced is None:
            return StateMachineResult(
                message="Would you like that hot or iced?",
                state=state,
                order=order,
            )

        item.iced = parsed.iced

        # Coffee is now complete
        item.mark_complete()
        state.clear_pending()

        return self._get_next_question(state, order)

    def _lookup_coffee_price(self, coffee_type: str | None) -> float:
        """Look up price for a coffee type."""
        if not coffee_type:
            return 2.50  # Default drip coffee price

        # Look up from menu
        menu_item = self._lookup_menu_item(coffee_type)
        if menu_item:
            return menu_item.get("base_price", 2.50)

        # Default prices by type
        coffee_type_lower = coffee_type.lower()
        if "latte" in coffee_type_lower or "cappuccino" in coffee_type_lower:
            return 4.50
        if "espresso" in coffee_type_lower:
            return 3.00

        return 2.50  # Default

    # =========================================================================
    # Signature/Speed Menu Handlers
    # =========================================================================

    def _handle_signature_menu_inquiry(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about signature/speed menu items."""
        # Find signature items from menu_data
        # The key is dynamically named based on the primary item type (e.g., signature_bagels, signature_sandwiches)
        signature_items = []

        if self.menu_data:
            # Look for signature items in any signature_* key
            for key, items in self.menu_data.items():
                if key.startswith("signature_") and isinstance(items, list):
                    signature_items.extend(items)

        if not signature_items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                state=state,
                order=order,
            )

        # Build a nice list of signature items with prices
        item_descriptions = []
        for item in signature_items:
            name = item.get("name", "Unknown")
            price = item.get("base_price", 0)
            item_descriptions.append(f"{name} for ${price:.2f}")

        # Format the response
        if len(item_descriptions) == 1:
            items_list = item_descriptions[0]
        elif len(item_descriptions) == 2:
            items_list = f"{item_descriptions[0]} and {item_descriptions[1]}"
        else:
            items_list = ", ".join(item_descriptions[:-1]) + f", and {item_descriptions[-1]}"

        message = f"Our speed menu options are: {items_list}. Would you like any of these?"

        return StateMachineResult(
            message=message,
            state=state,
            order=order,
        )

    # =========================================================================
    # By-the-Pound Handlers
    # =========================================================================

    def _handle_by_pound_inquiry(
        self,
        category: str | None,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle initial by-the-pound inquiry."""
        if category:
            # User asked about a specific category directly
            return self._list_by_pound_category(category, state, order)

        # General inquiry - list all categories and ask which they're interested in
        state.phase = OrderPhase.CONFIGURING_ITEM
        state.pending_field = "by_pound_category"
        return StateMachineResult(
            message="We sell cheeses, spreads, cold cuts, fish, and salads by the pound. Which are you interested in?",
            state=state,
            order=order,
        )

    def _handle_by_pound_category_selection(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle user selecting a by-the-pound category."""
        parsed = parse_by_pound_category(user_input, model=self.model)

        if parsed.unclear:
            return StateMachineResult(
                message="Which would you like to hear about? Cheeses, spreads, cold cuts, fish, or salads?",
                state=state,
                order=order,
            )

        if not parsed.category:
            # User declined or said never mind
            state.clear_pending()
            state.phase = OrderPhase.TAKING_ITEMS
            return StateMachineResult(
                message="No problem! What else can I get for you?",
                state=state,
                order=order,
            )

        # List the items in the selected category
        return self._list_by_pound_category(parsed.category, state, order)

    def _list_by_pound_category(
        self,
        category: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """List items in a specific by-the-pound category."""
        items = BY_POUND_ITEMS.get(category, [])
        category_name = BY_POUND_CATEGORY_NAMES.get(category, category)

        if not items:
            state.clear_pending()
            state.phase = OrderPhase.TAKING_ITEMS
            return StateMachineResult(
                message=f"I don't have information on {category_name} right now. What else can I get for you?",
                state=state,
                order=order,
            )

        # Format the items list nicely for voice
        if len(items) <= 3:
            items_list = ", ".join(items)
        else:
            items_list = ", ".join(items[:-1]) + f", and {items[-1]}"

        state.clear_pending()
        state.phase = OrderPhase.TAKING_ITEMS
        return StateMachineResult(
            message=f"Our {category_name} by the pound include: {items_list}. Would you like any of these, or something else?",
            state=state,
            order=order,
        )

    def _parse_quantity_to_pounds(self, quantity_str: str) -> float:
        """Parse a quantity string to pounds.

        Examples:
            "1 lb" -> 1.0
            "2 lbs" -> 2.0
            "half lb" -> 0.5
            "half pound" -> 0.5
            "quarter lb" -> 0.25
            "1/2 lb" -> 0.5
            "1/4 lb" -> 0.25
            "3/4 lb" -> 0.75
        """
        quantity_lower = quantity_str.lower().strip()

        # Handle fractional words
        if "half" in quantity_lower:
            return 0.5
        if "quarter" in quantity_lower:
            return 0.25
        if "three quarter" in quantity_lower or "3/4" in quantity_lower:
            return 0.75
        if "1/2" in quantity_lower:
            return 0.5
        if "1/4" in quantity_lower:
            return 0.25

        # Try to extract a number
        import re
        match = re.search(r"(\d+(?:\.\d+)?)", quantity_lower)
        if match:
            return float(match.group(1))

        # Default to 1 pound
        return 1.0

    def _lookup_by_pound_price(self, item_name: str) -> float:
        """Look up the per-pound price for a by-the-pound item.

        Args:
            item_name: Name of the item (e.g., "Muenster", "Nova", "Tuna Salad")

        Returns:
            Price per pound, or 0.0 if not found
        """
        item_lower = item_name.lower().strip()

        # Direct lookup
        if item_lower in BY_POUND_PRICES:
            return BY_POUND_PRICES[item_lower]

        # Try partial matching for items like "Nova" -> "nova scotia salmon"
        for price_key, price in BY_POUND_PRICES.items():
            if item_lower in price_key or price_key in item_lower:
                return price

        # Not found
        logger.warning(f"No price found for by-pound item: {item_name}")
        return 0.0

    def _add_by_pound_items(
        self,
        by_pound_items: list[ByPoundOrderItem],
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add by-the-pound items to the order."""
        from sandwich_bot.tasks.models import MenuItemTask

        added_items = []
        for item in by_pound_items:
            # Format the item name with quantity (e.g., "1 lb Muenster Cheese")
            category_name = BY_POUND_CATEGORY_NAMES.get(item.category, "")
            if category_name:
                # Use singular form for category (remove trailing 's' if present)
                category_singular = category_name.rstrip("s") if category_name.endswith("s") else category_name
                item_name = f"{item.quantity} {item.item_name} {category_singular}"
            else:
                item_name = f"{item.quantity} {item.item_name}"

            # Calculate price based on quantity and per-pound price
            pounds = self._parse_quantity_to_pounds(item.quantity)
            per_pound_price = self._lookup_by_pound_price(item.item_name)
            total_price = round(pounds * per_pound_price, 2)

            # Create menu item task with price
            menu_item = MenuItemTask(
                menu_item_name=item_name.strip(),
                menu_item_type="by_pound",
                unit_price=total_price,
            )
            menu_item.mark_in_progress()
            menu_item.mark_complete()  # By-pound items don't need configuration
            order.items.add_item(menu_item)
            added_items.append(item_name.strip())

        # Format confirmation message
        if len(added_items) == 1:
            confirmation = f"Got it, {added_items[0]}."
        elif len(added_items) == 2:
            confirmation = f"Got it, {added_items[0]} and {added_items[1]}."
        else:
            items_list = ", ".join(added_items[:-1]) + f", and {added_items[-1]}"
            confirmation = f"Got it, {items_list}."

        state.clear_pending()
        state.phase = OrderPhase.TAKING_ITEMS
        return StateMachineResult(
            message=f"{confirmation} Anything else?",
            state=state,
            order=order,
        )

    def _get_next_question(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Determine the next question to ask."""
        # Check for incomplete items
        for item in order.items.items:
            if item.status == TaskStatus.IN_PROGRESS:
                # This shouldn't happen if we're tracking state correctly
                logger.warning(f"Found in-progress item without pending state: {item}")

        # Ask if they want anything else
        items = order.items.get_active_items()
        if items:
            last_item = items[-1]
            summary = last_item.get_summary()
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                state=state,
                order=order,
            )

        return StateMachineResult(
            message="What can I get for you?",
            state=state,
            order=order,
        )

    def _transition_to_checkout(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Transition to checkout phase."""
        state.phase = OrderPhase.CHECKOUT_DELIVERY
        state.clear_pending()
        return StateMachineResult(
            message="Is this for pickup or delivery?",
            state=state,
            order=order,
        )

    def _get_item_by_id(self, order: OrderTask, item_id: str) -> ItemTask | None:
        """Find an item by its ID."""
        for item in order.items.items:
            if item.id == item_id:
                return item
        return None

    def _build_order_summary(self, order: OrderTask) -> str:
        """Build order summary string with consolidated identical items."""
        lines = ["Here's your order:"]

        # Group items by their summary string to consolidate identical items
        from collections import Counter
        item_counts: Counter[str] = Counter()
        for item in order.items.get_active_items():
            summary = item.get_summary()
            item_counts[summary] += 1

        # Build consolidated lines
        for summary, count in item_counts.items():
            if count > 1:
                lines.append(f"  - {count}× {summary}")
            else:
                lines.append(f"  - {summary}")

        return "\n".join(lines)

    def _lookup_bagel_price(self, bagel_type: str | None) -> float:
        """
        Look up price for a bagel type.

        For regular bagel types (plain, everything, sesame, etc.), returns the
        generic "Bagel" price from the menu. Only specialty bagels like
        "Gluten Free" get their specific price.

        Args:
            bagel_type: The bagel type (e.g., "plain", "everything", "gluten free")

        Returns:
            Price for the bagel (defaults to 2.50 if not found)
        """
        if not bagel_type:
            return 2.50

        bagel_type_lower = bagel_type.lower()

        # Specialty bagels that have their own menu items
        specialty_bagels = ["gluten free", "gluten-free"]

        if any(specialty in bagel_type_lower for specialty in specialty_bagels):
            # Look for specific specialty bagel
            bagel_name = f"{bagel_type.title()} Bagel" if "bagel" not in bagel_type_lower else bagel_type
            menu_item = self._lookup_menu_item(bagel_name)
            if menu_item:
                logger.info("Found specialty bagel: %s ($%.2f)", menu_item.get("name"), menu_item.get("base_price"))
                return menu_item.get("base_price", 2.50)

        # For regular bagels, look for the generic "Bagel" item
        menu_item = self._lookup_menu_item("Bagel")
        if menu_item:
            logger.info("Using generic bagel price: $%.2f", menu_item.get("base_price"))
            return menu_item.get("base_price", 2.50)

        # Default fallback
        return 2.50

    def _lookup_menu_item(self, item_name: str) -> dict | None:
        """
        Look up a menu item by name from the menu data.

        Args:
            item_name: Name of the item to find (case-insensitive fuzzy match)

        Returns:
            Menu item dict with id, name, base_price, etc. or None if not found
        """
        if not self.menu_data:
            return None

        item_name_lower = item_name.lower()

        # Collect all items from all categories
        all_items = []
        categories_to_search = [
            "signature_sandwiches", "signature_bagels", "signature_omelettes",
            "sides", "drinks", "desserts", "other",
            "custom_sandwiches", "custom_bagels",
        ]

        for category in categories_to_search:
            all_items.extend(self.menu_data.get(category, []))

        # Also include items_by_type
        items_by_type = self.menu_data.get("items_by_type", {})
        for type_slug, items in items_by_type.items():
            all_items.extend(items)

        # Pass 1: Exact match (highest priority)
        for item in all_items:
            if item.get("name", "").lower() == item_name_lower:
                return item

        # Pass 2: Search term is contained in item name (e.g., searching "chipotle" finds "The Chipotle Egg Omelette")
        # Prefer shorter item names (more specific match)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_lower in item_name_db:
                matches.append(item)
        if matches:
            # Return the shortest matching name (most specific)
            return min(matches, key=lambda x: len(x.get("name", "")))

        # Pass 3: Item name is contained in search term (e.g., searching "The Chipotle Egg Omelette" finds item named "Chipotle Egg Omelette")
        # Prefer LONGER item names (more complete match)
        matches = []
        for item in all_items:
            item_name_db = item.get("name", "").lower()
            if item_name_db in item_name_lower:
                matches.append(item)
        if matches:
            # Return the longest matching name (most complete)
            return max(matches, key=lambda x: len(x.get("name", "")))

        return None

    # Default modifier prices - used as fallback when menu_data lookup fails
    DEFAULT_MODIFIER_PRICES = {
        # Proteins
        "ham": 2.00,
        "bacon": 2.00,
        "egg": 1.50,
        "lox": 5.00,
        "turkey": 2.50,
        "pastrami": 3.00,
        "sausage": 2.00,
        # Cheeses
        "american": 0.75,
        "swiss": 0.75,
        "cheddar": 0.75,
        "muenster": 0.75,
        "provolone": 0.75,
        # Spreads
        "cream cheese": 1.50,
        "butter": 0.50,
        "scallion cream cheese": 1.75,
        "vegetable cream cheese": 1.75,
        # Extras
        "avocado": 2.00,
        "tomato": 0.50,
        "onion": 0.50,
        "capers": 0.75,
    }

    def _lookup_modifier_price(self, modifier_name: str, item_type: str = "bagel") -> float:
        """
        Look up price modifier for a bagel add-on (protein, cheese, topping).

        Searches the item_types attribute options for matching modifier prices.
        Falls back to DEFAULT_MODIFIER_PRICES if not found in menu_data.

        Args:
            modifier_name: Name of the modifier (e.g., "ham", "egg", "american")
            item_type: Item type to look up (default "bagel", falls back to "sandwich")

        Returns:
            Price modifier (e.g., 2.00 for ham) or 0.0 if not found
        """
        modifier_lower = modifier_name.lower()

        # Try menu_data first if available
        if self.menu_data:
            item_types = self.menu_data.get("item_types", {})

            # Try the specified item type first, then fall back to sandwich
            types_to_check = [item_type, "sandwich"] if item_type != "sandwich" else ["sandwich"]

            for type_slug in types_to_check:
                type_data = item_types.get(type_slug, {})
                attributes = type_data.get("attributes", [])

                # Search through all attributes (protein, cheese, toppings, etc.)
                for attr in attributes:
                    options = attr.get("options", [])
                    for opt in options:
                        # Match by slug or display_name
                        if opt.get("slug", "").lower() == modifier_lower or \
                           opt.get("display_name", "").lower() == modifier_lower:
                            price = opt.get("price_modifier", 0.0)
                            if price > 0:
                                logger.debug(
                                    "Found modifier price: %s = $%.2f (from %s.%s)",
                                    modifier_name, price, type_slug, attr.get("slug")
                                )
                                return price

        # Fall back to default prices
        default_price = self.DEFAULT_MODIFIER_PRICES.get(modifier_lower, 0.0)
        if default_price > 0:
            logger.debug(
                "Using default modifier price: %s = $%.2f",
                modifier_name, default_price
            )
        return default_price

    def _calculate_bagel_price_with_modifiers(
        self,
        base_price: float,
        sandwich_protein: str | None,
        extras: list[str] | None,
        spread: str | None,
    ) -> float:
        """
        Calculate total bagel price including modifiers.

        Args:
            base_price: Base bagel price
            sandwich_protein: Primary protein (e.g., "ham")
            extras: Additional modifiers (e.g., ["egg", "american"])
            spread: Spread choice (e.g., "cream cheese")

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add protein price
        if sandwich_protein:
            total += self._lookup_modifier_price(sandwich_protein)

        # Add extras prices
        if extras:
            for extra in extras:
                total += self._lookup_modifier_price(extra)

        # Add spread price (if not "none")
        if spread and spread.lower() != "none":
            total += self._lookup_modifier_price(spread)

        return round(total, 2)

    def recalculate_bagel_price(self, item: BagelItemTask) -> float:
        """
        Recalculate and update a bagel item's price based on its current modifiers.

        This should be called whenever a bagel's modifiers change (spread, protein, extras)
        to ensure price is always in sync with the item's state.

        Args:
            item: The bagel item to update

        Returns:
            The new calculated price
        """
        # Get base price from bagel type
        base_price = self._lookup_bagel_price(item.bagel_type)

        # Calculate total with all current modifiers
        new_price = self._calculate_bagel_price_with_modifiers(
            base_price,
            item.sandwich_protein,
            item.extras,
            item.spread,
        )

        # Update the item's price
        item.unit_price = new_price

        logger.debug(
            "Recalculated bagel price: base=%.2f, protein=%s, extras=%s, spread=%s -> total=%.2f",
            base_price, item.sandwich_protein, item.extras, item.spread, new_price
        )

        return new_price
