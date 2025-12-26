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
from typing import Any, Literal, Union
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
    SpeedMenuBagelItemTask,
    ItemTask,
    TaskStatus,
)
from .slot_orchestrator import SlotOrchestrator, SlotCategory

logger = logging.getLogger(__name__)

# Logger for slot orchestrator comparison (can be enabled/disabled independently)
slot_logger = logging.getLogger(__name__ + ".slot_comparison")


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
    CHECKOUT_PHONE = "checkout_phone"  # Collect phone if they want text confirmation
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
        description="Name of a menu item ordered (e.g., 'The Chipotle Egg Omelette', 'Tuna Salad Sandwich')"
    )
    new_menu_item_quantity: int = Field(
        default=1,
        description="Number of menu items ordered (e.g., '3 omelettes' -> 3, 'two sandwiches' -> 2)"
    )
    new_side_item: str | None = Field(
        default=None,
        description="Side item ordered (e.g., 'Side of Sausage', 'Side of Bacon', 'Side of Turkey Bacon'). Use when user says 'with a side of X' or 'side of X'"
    )
    new_side_item_quantity: int = Field(
        default=1,
        description="Number of side items ordered"
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

    # Speed menu bagel orders (pre-configured sandwiches like "The Classic", "The Leo")
    new_speed_menu_bagel: bool = Field(
        default=False,
        description="User wants to order a speed menu bagel (e.g., 'The Classic', 'The Leo', 'The Traditional')"
    )
    new_speed_menu_bagel_name: str | None = Field(
        default=None,
        description="Name of the speed menu bagel (e.g., 'The Classic', 'The Leo', 'The Max Zucker')"
    )
    new_speed_menu_bagel_quantity: int = Field(
        default=1,
        description="Number of speed menu bagels ordered (e.g., '3 Classics' -> 3)"
    )
    new_speed_menu_bagel_toasted: bool | None = Field(
        default=None,
        description="Whether the speed menu bagel should be toasted (True/False/None)"
    )

    # Clarifications needed
    needs_soda_clarification: bool = Field(
        default=False,
        description="User ordered a generic 'soda' without specifying type - need to ask what kind"
    )

    # Menu inquiries
    menu_query: bool = Field(
        default=False,
        description="User is asking what items are available (e.g., 'what sodas do you have?', 'what drinks do you have?', 'what bagels do you have?')"
    )
    menu_query_type: str | None = Field(
        default=None,
        description="The type of item being queried: 'soda', 'juice', 'coffee', 'tea', 'drink', 'beverage', 'bagel', 'egg_sandwich', 'fish_sandwich', 'sandwich', 'spread_sandwich', 'salad_sandwich', 'omelette', 'side', 'snack', etc."
    )
    asking_signature_menu: bool = Field(
        default=False,
        description="User is asking about signature/speed menu items (e.g., 'what are your speed menu bagels?', 'what signature items do you have?')"
    )
    signature_menu_type: str | None = Field(
        default=None,
        description="The specific type of signature items being asked about: 'signature_sandwich', 'speed_menu_bagel', or None for all signature items"
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


class PhoneResponse(BaseModel):
    """Parser output when collecting phone number."""
    phone: str | None = Field(
        default=None,
        description="The phone number provided by the user (digits only, 10 digits for US)"
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
    "gluten free", "gluten-free",
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
    "tofu", "olive",
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

        "onion bagel" -> no toppings (onion is the bagel type, not a topping)
    """
    result = ExtractedModifiers()
    input_lower = user_input.lower()

    # Pre-mark "side of X" patterns to exclude them from modifier extraction
    # This prevents "side of turkey sausage" from extracting "turkey" and "sausage" as bagel modifiers
    side_of_spans: list[tuple[int, int]] = []
    side_of_pattern = re.compile(r'\bside\s+of\s+\w+(?:\s+\w+)?', re.IGNORECASE)
    for match in side_of_pattern.finditer(input_lower):
        side_of_spans.append((match.start(), match.end()))
        logger.debug(f"Excluding 'side of' pattern from modifiers: '{match.group()}'")

    # Pre-mark bagel type patterns to exclude them from topping extraction
    # This prevents "onion bagel" from extracting "onion" as a topping
    # The bagel type word should only be a topping if explicitly added (e.g., "onion bagel with onion")
    bagel_type_spans: list[tuple[int, int]] = []
    for bagel_type in sorted(BAGEL_TYPES, key=len, reverse=True):
        # Match "<type> bagel" pattern
        pattern = re.compile(rf'\b{re.escape(bagel_type)}\s+bagels?\b', re.IGNORECASE)
        for match in pattern.finditer(input_lower):
            # Only exclude the bagel type portion, not the whole match
            type_end = match.start() + len(bagel_type)
            bagel_type_spans.append((match.start(), type_end))
            logger.debug(f"Excluding bagel type from modifiers: '{bagel_type}'")

    # Helper to check if a word boundary exists (not part of a larger word)
    def is_word_boundary(text: str, start: int, end: int) -> bool:
        """Check if the match is at word boundaries."""
        before_ok = start == 0 or not text[start - 1].isalnum()
        after_ok = end >= len(text) or not text[end].isalnum()
        return before_ok and after_ok

    # Track what we've already matched to avoid duplicates
    # Start with side_of_spans and bagel_type_spans to exclude those regions from modifier extraction
    matched_spans: list[tuple[int, int]] = side_of_spans.copy() + bagel_type_spans.copy()

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
        cheese_match = re.search(r'\bcheese\b', input_lower)
        if cheese_match:
            pos = cheese_match.start()
            # Make sure it's not part of "cream cheese"
            if "cream cheese" not in input_lower[max(0, pos-6):pos+7]:
                result.cheeses.append("american")
                logger.debug("Extracted cheese: 'cheese' -> 'american' (default)")

    return result


@dataclass
class ExtractedCoffeeModifiers:
    """Container for coffee modifiers extracted from user input."""
    sweetener: str | None = None
    sweetener_quantity: int = 1
    flavor_syrup: str | None = None


def extract_coffee_modifiers_from_input(user_input: str) -> ExtractedCoffeeModifiers:
    """
    Extract coffee modifiers from user input using keyword matching.

    This is a deterministic, non-LLM approach that scans the input for
    known sweetener and flavor syrup keywords.

    Args:
        user_input: The raw user input string

    Returns:
        ExtractedCoffeeModifiers with sweetener and flavor_syrup if found
    """
    result = ExtractedCoffeeModifiers()
    input_lower = user_input.lower()

    # Known sweeteners
    sweeteners = ["splenda", "sugar", "stevia", "equal", "sweet n low", "sweet'n low", "honey"]

    # Known flavor syrups
    syrups = ["vanilla", "caramel", "hazelnut", "mocha", "pumpkin spice", "cinnamon", "lavender", "almond"]

    # Extract sweetener with quantity
    # Pattern: "2 splenda", "two sugars", "splenda", etc.
    for sweetener in sweeteners:
        # Check for quantity + sweetener pattern
        qty_pattern = re.compile(
            rf'(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+{sweetener}s?',
            re.IGNORECASE
        )
        qty_match = qty_pattern.search(input_lower)
        if qty_match:
            qty_str = qty_match.group(1)
            if qty_str.isdigit():
                result.sweetener_quantity = int(qty_str)
            else:
                result.sweetener_quantity = WORD_TO_NUM.get(qty_str.lower(), 1)
            result.sweetener = sweetener
            logger.debug(f"Extracted coffee sweetener: {result.sweetener_quantity} {sweetener}")
            break
        # Check for just sweetener (no quantity)
        elif re.search(rf'\b{sweetener}s?\b', input_lower):
            result.sweetener = sweetener
            result.sweetener_quantity = 1
            logger.debug(f"Extracted coffee sweetener: {sweetener}")
            break

    # Extract flavor syrup
    for syrup in syrups:
        if re.search(rf'\b{syrup}\b', input_lower):
            result.flavor_syrup = syrup
            logger.debug(f"Extracted coffee flavor syrup: {syrup}")
            break

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


def _build_spread_types_from_menu(cheese_types: list[str]) -> set[str]:
    """Build spread type keywords from database cheese_types.

    Extracts the flavor/type prefix from ingredient names like:
    - "Tofu Cream Cheese" -> "tofu"
    - "Scallion Cream Cheese" -> "scallion"
    - "Sun-Dried Tomato Cream Cheese" -> "sun-dried tomato"
    - "Maple Raisin Walnut Cream Cheese" -> "maple raisin walnut"
    """
    spread_types = set()
    for name in cheese_types:
        name_lower = name.lower()
        # Extract type by removing common suffixes
        for suffix in ["cream cheese", "spread"]:
            if suffix in name_lower:
                prefix = name_lower.replace(suffix, "").strip()
                if prefix and prefix not in ("plain", "regular"):
                    spread_types.add(prefix)
                break
    return spread_types


def _extract_spread(text: str, extra_spread_types: set[str] | None = None) -> tuple[str | None, str | None]:
    """Extract spread and spread type from text. Returns (spread, spread_type).

    Args:
        text: User input text
        extra_spread_types: Additional spread types from database (e.g., from menu_data cheese_types)
    """
    text_lower = text.lower()

    spread = None
    spread_type = None

    # Check for spreads
    for s in sorted(SPREADS, key=len, reverse=True):
        if s in text_lower:
            spread = s
            break

    # Combine hardcoded and database spread types
    all_spread_types = SPREAD_TYPES.copy()
    if extra_spread_types:
        all_spread_types.update(extra_spread_types)

    # Check for spread types (e.g., "scallion cream cheese")
    for st in sorted(all_spread_types, key=len, reverse=True):
        if st in text_lower:
            spread_type = st
            break

    # If we found a spread type but no spread, assume cream cheese
    if spread_type and not spread:
        spread = "cream cheese"

    return spread, spread_type


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


def _extract_side_item(text: str) -> tuple[str | None, int]:
    """Extract side item from text. Returns (side_item_name, quantity)."""
    text_lower = text.lower()

    # Look for "side of X" pattern - capture up to 3 words after "side of"
    side_match = re.search(r'\bside\s+of\s+(\w+(?:\s+\w+){0,2})', text_lower)
    if not side_match:
        return None, 1

    side_text = side_match.group(1).strip()

    # Try to match against known side items (longer/more specific matches first)
    for keyword in sorted(SIDE_ITEM_MAP.keys(), key=len, reverse=True):
        # Exact match or the side_text starts with the keyword
        if side_text == keyword or side_text.startswith(keyword + " ") or side_text.startswith(keyword):
            return SIDE_ITEM_MAP[keyword], 1

    # If we found "side of" but can't match it, return the raw text as a side item
    # The lookup function will try to find it in the menu
    return f"Side of {side_text.title()}", 1


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
    "turkey club",
    "hot pastrami sandwich", "pastrami sandwich",
    "nova scotia salmon", "nova salmon",
    # Omelettes
    "chipotle egg omelette", "the chipotle egg omelette", "chipotle omelette",
    "cheese omelette",
    "western omelette",
    "veggie omelette",
    "spinach & feta omelette", "spinach and feta omelette", "spinach feta omelette",
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
    "hummus sandwich", "hummus bagel",
    "avocado spread sandwich", "avocado spread",
    "tofu plain sandwich", "tofu plain", "plain tofu",
    "tofu scallion sandwich", "tofu scallion", "scallion tofu",
    "tofu vegetable sandwich", "tofu veggie", "tofu vegetable", "veggie tofu",
    "tofu nova sandwich", "tofu nova", "nova tofu",
    # Salad Sandwiches
    "tuna salad sandwich", "tuna salad", "tuna sandwich",
    "whitefish salad sandwich", "whitefish salad", "whitefish sandwich",
    "baked salmon salad sandwich", "baked salmon salad", "salmon salad sandwich",
    "egg salad sandwich", "egg salad",
    "chicken salad sandwich", "chicken salad",
    "cranberry pecan chicken salad sandwich", "cranberry pecan chicken salad", "cranberry chicken salad",
    "lemon chicken salad sandwich", "lemon chicken salad",
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
    "hummus sandwich", "hummus bagel",
    "avocado spread sandwich", "avocado spread",
    "tofu plain sandwich", "tofu plain", "plain tofu",
    "tofu scallion sandwich", "tofu scallion", "scallion tofu",
    "tofu vegetable sandwich", "tofu veggie", "tofu vegetable", "veggie tofu",
    "tofu nova sandwich", "tofu nova", "nova tofu",
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
}


def _extract_menu_item_from_text(text: str) -> tuple[str | None, int]:
    """
    Try to extract a known menu item from text.
    Returns (item_name, quantity) or (None, 0) if not found.
    """
    text_lower = text.lower().strip()

    # Remove common prefixes
    text_lower = re.sub(r'^(i\s+want\s+|i\'?d\s+like\s+|can\s+i\s+(get|have)\s+|give\s+me\s+|let\s+me\s+(get|have)\s+)', '', text_lower)
    text_lower = re.sub(r'^(a|an|the)\s+', '', text_lower)

    # Extract quantity
    quantity = 1
    qty_match = re.match(r'^(\d+|one|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        text_lower = text_lower[qty_match.end():]
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # Check for known menu items - sort by length (longest first) for better matching
    for item in sorted(KNOWN_MENU_ITEMS, key=len, reverse=True):
        if item in text_lower or text_lower.startswith(item):
            # Check if we have a canonical name mapping for this item
            if item in MENU_ITEM_CANONICAL_NAMES:
                canonical = MENU_ITEM_CANONICAL_NAMES[item]
            elif item in NO_THE_PREFIX_ITEMS:
                # Items that don't need "The " prefix - just title case
                canonical = " ".join(word.capitalize() for word in item.split())
            else:
                # Signature items get "The " prefix
                canonical = " ".join(word.capitalize() for word in item.split())
                if not canonical.startswith("The "):
                    canonical = "The " + canonical
            return canonical, quantity

    return None, 0


def parse_open_input_deterministic(user_input: str, spread_types: set[str] | None = None) -> OpenInputResponse | None:
    """
    Try to parse user input deterministically without LLM.

    Returns OpenInputResponse if parsing succeeds, None if should fall back to LLM.

    Args:
        user_input: The user's input string
        spread_types: Optional set of spread type keywords from database (e.g., "tofu", "scallion")

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

    # EARLY CHECK: Check for spread/salad sandwiches BEFORE bagel parsing
    # This prevents "scallion cream cheese" from being parsed as a bagel with spread
    # Instead, it should be recognized as a "Scallion Cream Cheese Sandwich" menu item
    # BUT: If they say "bagel with X cream cheese", that's a build-your-own order
    text_lower = text.lower()
    has_bagel_mention = re.search(r"\bbagels?\b", text_lower)
    has_sandwich_mention = "sandwich" in text_lower

    # Only do early menu item matching if:
    # 1. They explicitly said "sandwich", OR
    # 2. They mentioned a spread/salad type WITHOUT mentioning "bagel"
    # This way "plain bagel with scallion cream cheese" → build-your-own bagel
    # But "scallion cream cheese" or "scallion cream cheese sandwich" → menu item
    if (has_sandwich_mention or not has_bagel_mention) and any(term in text_lower for term in [
        "cream cheese sandwich", "cream cheese",
        "salad sandwich", "tuna salad", "whitefish salad", "egg salad",
        "chicken salad", "salmon salad",
        "butter sandwich", "peanut butter", "nutella", "hummus",
        "avocado spread", "tofu"
    ]):
        # Try menu item extraction first
        menu_item, qty = _extract_menu_item_from_text(text)
        if menu_item:
            logger.info("EARLY MENU ITEM: matched '%s' -> %s (qty=%d)", text[:50], menu_item, qty)
            return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty)

    # Check for bagel order with quantity
    quantity_match = BAGEL_QUANTITY_PATTERN.search(text)
    if quantity_match:
        quantity_str = quantity_match.group(1)
        quantity = _extract_quantity(quantity_str)

        if quantity:
            bagel_type = _extract_bagel_type(text)
            toasted = _extract_toasted(text)
            spread, spread_type = _extract_spread(text, spread_types)
            side_item, side_qty = _extract_side_item(text)

            logger.debug(
                "Deterministic parse: bagel order - qty=%d, type=%s, toasted=%s, spread=%s/%s, side=%s",
                quantity, bagel_type, toasted, spread, spread_type, side_item
            )

            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=quantity,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
            )

    # Check for simple "a bagel" / "bagel please" (quantity = 1)
    if SIMPLE_BAGEL_PATTERN.search(text):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        logger.debug(
            "Deterministic parse: single bagel - type=%s, toasted=%s, spread=%s/%s, side=%s",
            bagel_type, toasted, spread, spread_type, side_item
        )

        return OpenInputResponse(
            new_bagel=True,
            new_bagel_quantity=1,
            new_bagel_type=bagel_type,
            new_bagel_toasted=toasted,
            new_bagel_spread=spread,
            new_bagel_spread_type=spread_type,
            new_side_item=side_item,
            new_side_item_quantity=side_qty,
        )

    # Check if text contains "bagel" anywhere - might be a bagel order we can't fully parse
    # but we can at least extract some info
    if re.search(r"\bbagels?\b", text, re.IGNORECASE):
        bagel_type = _extract_bagel_type(text)
        toasted = _extract_toasted(text)
        spread, spread_type = _extract_spread(text, spread_types)
        side_item, side_qty = _extract_side_item(text)

        # Only return if we extracted at least something useful (including side item)
        if bagel_type or toasted is not None or spread or side_item:
            logger.debug(
                "Deterministic parse: bagel mention - type=%s, toasted=%s, spread=%s/%s, side=%s",
                bagel_type, toasted, spread, spread_type, side_item
            )
            return OpenInputResponse(
                new_bagel=True,
                new_bagel_quantity=1,
                new_bagel_type=bagel_type,
                new_bagel_toasted=toasted,
                new_bagel_spread=spread,
                new_bagel_spread_type=spread_type,
                new_side_item=side_item,
                new_side_item_quantity=side_qty,
            )

    # Check for coffee/beverage order (deterministic - no LLM needed)
    coffee_result = _parse_coffee_deterministic(text)
    if coffee_result:
        logger.info("DETERMINISTIC COFFEE: matched '%s' -> type=%s", text[:50], coffee_result.new_coffee_type)
        return coffee_result

    # Check for soda/bottled drink order
    soda_result = _parse_soda_deterministic(text)
    if soda_result:
        return soda_result

    # Check for known menu items (sandwiches, omelettes, etc.)
    menu_item, qty = _extract_menu_item_from_text(text)
    if menu_item:
        logger.info("DETERMINISTIC MENU ITEM: matched '%s' -> %s (qty=%d)", text[:50], menu_item, qty)
        return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=qty)

    # Can't parse deterministically - fall back to LLM
    logger.debug("Deterministic parse: falling back to LLM for '%s'", text[:50])
    return None


# Coffee beverage types that should be parsed as coffee orders
COFFEE_BEVERAGE_TYPES = {
    "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
    "mocha", "cold brew", "tea", "chai", "matcha", "hot chocolate",
}

# Pattern to match coffee orders: "cappuccino", "a latte", "iced coffee", "large latte", etc.
COFFEE_ORDER_PATTERN = re.compile(
    r"(?:i(?:'?d|\s*would)?\s*(?:like|want|need|take|have|get)|"
    r"(?:can|could|may)\s+i\s+(?:get|have)|"
    r"give\s+me|"
    r"let\s*(?:me|'s)\s*(?:get|have)|"
    r")?\s*"
    r"(?:an?\s+)?"
    r"(?:(\d+|two|three|four|five)\s+)?"  # Optional quantity
    r"(?:(small|medium|large)\s+)?"  # Optional size
    r"(?:(iced|hot)\s+)?"  # Optional iced/hot
    r"(" + "|".join(COFFEE_BEVERAGE_TYPES) + r")"  # Coffee type
    r"(?:\s|$|[.,!?])",
    re.IGNORECASE
)


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


def _parse_coffee_deterministic(text: str) -> OpenInputResponse | None:
    """
    Try to parse coffee/beverage orders deterministically.

    Handles orders like:
    - "cappuccino"
    - "a latte"
    - "iced coffee"
    - "large hot latte"
    - "cappuccino with 2 splenda and vanilla syrup"
    """
    text_lower = text.lower()

    # Check if any coffee type is mentioned (exact match first)
    coffee_type = None
    for bev in COFFEE_BEVERAGE_TYPES:
        if re.search(rf'\b{bev}\b', text_lower):
            coffee_type = bev
            break

    # If no exact match, check for common typos
    if not coffee_type:
        for typo, correct in COFFEE_TYPO_MAP.items():
            if re.search(rf'\b{typo}\b', text_lower):
                coffee_type = correct
                logger.debug("Deterministic parse: corrected typo '%s' -> '%s'", typo, correct)
                break

    if not coffee_type:
        return None

    logger.debug("Deterministic parse: detected coffee type '%s'", coffee_type)

    # Extract quantity (default 1)
    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+(?:' + '|'.join(COFFEE_BEVERAGE_TYPES) + r')', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    # Extract size
    size = None
    size_match = re.search(r'\b(small|medium|large)\b', text_lower)
    if size_match:
        size = size_match.group(1)

    # Extract iced/hot
    iced = None
    if re.search(r'\biced\b', text_lower):
        iced = True
    elif re.search(r'\bhot\b', text_lower):
        iced = False

    # Extract milk preference
    milk = None
    milk_patterns = [
        (r'\bwith\s+(oat|almond|soy|skim|whole|coconut)\s*milk\b', 1),
        (r'\b(oat|almond|soy|skim|whole|coconut)\s*milk\b', 1),
        (r'\bblack\b', 'none'),
    ]
    for pattern, group in milk_patterns:
        milk_match = re.search(pattern, text_lower)
        if milk_match:
            milk = milk_match.group(group) if isinstance(group, int) else group
            break

    # Extract sweetener and flavor syrup using existing function
    coffee_mods = extract_coffee_modifiers_from_input(text)

    logger.debug(
        "Deterministic parse: coffee order - type=%s, qty=%d, size=%s, iced=%s, milk=%s, sweetener=%s(%d), syrup=%s",
        coffee_type, quantity, size, iced, milk,
        coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup
    )

    return OpenInputResponse(
        new_coffee=True,
        new_coffee_type=coffee_type,
        new_coffee_quantity=quantity,
        new_coffee_size=size,
        new_coffee_iced=iced,
        new_coffee_milk=milk,
        new_coffee_sweetener=coffee_mods.sweetener,
        new_coffee_sweetener_quantity=coffee_mods.sweetener_quantity,
        new_coffee_flavor_syrup=coffee_mods.flavor_syrup,
    )


def _parse_soda_deterministic(text: str) -> OpenInputResponse | None:
    """
    Try to parse soda/bottled drink orders deterministically.

    Handles orders like:
    - "coke"
    - "a diet coke"
    - "3 sprites"
    - "water"
    - "a soda" (generic - will ask for type)
    """
    text_lower = text.lower()

    # Check if any soda type is mentioned
    # Sort by length (longest first) to match "diet coke" before "coke"
    drink_type = None
    for soda in sorted(SODA_DRINK_TYPES, key=len, reverse=True):
        # Use word boundary match to avoid partial matches
        if re.search(rf'\b{re.escape(soda)}\b', text_lower):
            drink_type = soda
            break

    # Check for generic soda terms that need clarification
    if not drink_type:
        generic_soda_terms = {"soda", "pop", "soft drink", "fountain drink"}
        for term in generic_soda_terms:
            if re.search(rf'\b{re.escape(term)}\b', text_lower):
                logger.info("Deterministic parse: detected generic soda term '%s', needs clarification", term)
                return OpenInputResponse(
                    needs_soda_clarification=True,
                )

    if not drink_type:
        return None

    logger.debug("Deterministic parse: detected soda type '%s'", drink_type)

    # Extract quantity (default 1)
    quantity = 1
    qty_match = re.search(r'(\d+|two|three|four|five)\s+', text_lower)
    if qty_match:
        qty_str = qty_match.group(1)
        if qty_str.isdigit():
            quantity = int(qty_str)
        else:
            quantity = WORD_TO_NUM.get(qty_str, 1)

    logger.debug("Deterministic parse: soda order - type=%s, qty=%d", drink_type, quantity)

    return OpenInputResponse(
        new_coffee=True,  # Use the coffee fields for drinks
        new_coffee_type=drink_type,
        new_coffee_quantity=quantity,
        new_coffee_size=None,  # Sodas don't have sizes
        new_coffee_iced=None,  # Sodas don't need hot/iced
        new_coffee_milk=None,
        new_coffee_sweetener=None,
        new_coffee_sweetener_quantity=1,
        new_coffee_flavor_syrup=None,
    )


SIDE_ITEM_TYPES = {
    "chips", "potato chips", "kettle chips",
    "salad", "side salad", "green salad",
    "fruit", "fresh fruit", "fruit cup",
    "coleslaw", "cole slaw",
    "pickle", "pickles",
    "fries", "french fries",
    "soup", "soup of the day",
}


def _parse_multi_item_order(user_input: str) -> OpenInputResponse | None:
    """
    Parse multi-item orders like "The Lexington and an orange juice".
    Splits on "and" and commas, and parses each component.
    """
    text = user_input.strip()
    text_lower = text.lower()

    # Preserve compound phrases by replacing them with placeholders
    compound_phrases = [
        ("ham and cheese", "HAM_CHEESE_PLACEHOLDER"),
        ("ham and egg", "HAM_EGG_PLACEHOLDER"),
        ("bacon and egg", "BACON_EGG_PLACEHOLDER"),
        ("lox and cream cheese", "LOX_CC_PLACEHOLDER"),
        ("cream cheese and lox", "CC_LOX_PLACEHOLDER"),
        ("salt and pepper", "SALT_PEPPER_PLACEHOLDER"),
        ("eggs and bacon", "EGGS_BACON_PLACEHOLDER"),
        ("black and white", "BLACK_WHITE_PLACEHOLDER"),
        ("spinach and feta", "SPINACH_FETA_PLACEHOLDER"),
    ]

    preserved_text = text_lower
    for phrase, placeholder in compound_phrases:
        preserved_text = preserved_text.replace(phrase, placeholder)

    # Check if there's still an "and" or comma - if not, this isn't a multi-item order
    if " and " not in preserved_text and ", " not in preserved_text:
        return None

    # Replace ", and " with just ", " to avoid empty parts
    preserved_text = preserved_text.replace(", and ", ", ")
    # Replace " and " with ", " to normalize separators
    preserved_text = preserved_text.replace(" and ", ", ")

    # Split on comma
    parts = [p.strip() for p in preserved_text.split(",") if p.strip()]
    if len(parts) < 2:
        return None

    # Restore compound phrases in each part
    restored_parts = []
    for part in parts:
        restored = part.strip()
        for phrase, placeholder in compound_phrases:
            restored = restored.replace(placeholder, phrase)
        if restored:
            restored_parts.append(restored)

    logger.info("Multi-item order split into %d parts: %s", len(restored_parts), restored_parts)

    # Parse each part
    menu_item = None
    menu_item_qty = 1
    coffee_type = None
    coffee_qty = 1
    coffee_size = None
    coffee_iced = None
    bagel = False
    bagel_qty = 1
    bagel_type = None
    side_item = None
    side_item_qty = 1

    for part in restored_parts:
        part = part.strip()
        if not part:
            continue

        # Try to parse as menu item
        item_name, item_qty = _extract_menu_item_from_text(part)
        if item_name:
            menu_item = item_name
            menu_item_qty = item_qty
            logger.info("Multi-item: detected menu item '%s' (qty=%d)", menu_item, menu_item_qty)
            continue

        # Try to parse as coffee/drink
        # Check for soda types first (sorted by length to match "diet coke" before "coke")
        drink_found = False
        for soda in sorted(SODA_DRINK_TYPES, key=len, reverse=True):
            if re.search(rf'\b{re.escape(soda)}\b', part):
                coffee_type = soda
                coffee_qty = 1
                # Check for quantity
                qty_match = re.search(r'(\d+|one|two|three|four|five)\s+', part)
                if qty_match:
                    qty_str = qty_match.group(1)
                    coffee_qty = int(qty_str) if qty_str.isdigit() else WORD_TO_NUM.get(qty_str, 1)
                logger.info("Multi-item: detected drink '%s' (qty=%d)", coffee_type, coffee_qty)
                drink_found = True
                break

        if drink_found:
            continue

        # Check for coffee beverage types
        for bev in COFFEE_BEVERAGE_TYPES:
            if re.search(rf'\b{bev}\b', part):
                coffee_type = bev
                coffee_qty = 1
                # Extract size
                size_match = re.search(r'\b(small|medium|large)\b', part)
                if size_match:
                    coffee_size = size_match.group(1)
                # Extract iced/hot
                if 'iced' in part:
                    coffee_iced = True
                elif 'hot' in part:
                    coffee_iced = False
                # Check for quantity
                qty_match = re.search(r'(\d+|one|two|three|four|five)\s+', part)
                if qty_match:
                    qty_str = qty_match.group(1)
                    coffee_qty = int(qty_str) if qty_str.isdigit() else WORD_TO_NUM.get(qty_str, 1)
                logger.info("Multi-item: detected coffee '%s' (qty=%d)", coffee_type, coffee_qty)
                drink_found = True
                break

        if drink_found:
            continue

        # Try to parse as bagel
        if re.search(r'\bbagels?\b', part):
            bagel = True
            bagel_type = _extract_bagel_type(part)
            qty_match = re.search(r'(\d+|one|two|three|four|five)\s+bagels?', part)
            if qty_match:
                qty_str = qty_match.group(1)
                bagel_qty = int(qty_str) if qty_str.isdigit() else WORD_TO_NUM.get(qty_str, 1)
            logger.info("Multi-item: detected bagel (type=%s, qty=%d)", bagel_type, bagel_qty)
            continue

        # Try to parse as side item
        side_found = False
        for side in SIDE_ITEM_TYPES:
            if re.search(rf'\b{re.escape(side)}\b', part):
                side_item = side
                side_item_qty = 1
                # Check for quantity
                qty_match = re.search(r'(\d+|one|two|three|four|five)\s+', part)
                if qty_match:
                    qty_str = qty_match.group(1)
                    side_item_qty = int(qty_str) if qty_str.isdigit() else WORD_TO_NUM.get(qty_str, 1)
                logger.info("Multi-item: detected side item '%s' (qty=%d)", side_item, side_item_qty)
                side_found = True
                break

        if side_found:
            continue

    # If we found at least two different item types, return a combined response
    items_found = sum([
        menu_item is not None,
        coffee_type is not None,
        bagel,
        side_item is not None,
    ])

    if items_found >= 2:
        logger.info("Multi-item order parsed: menu_item=%s, coffee=%s, bagel=%s, side=%s", menu_item, coffee_type, bagel, side_item)
        return OpenInputResponse(
            new_menu_item=menu_item,
            new_menu_item_quantity=menu_item_qty,
            new_coffee=coffee_type is not None,
            new_coffee_type=coffee_type,
            new_coffee_quantity=coffee_qty,
            new_coffee_size=coffee_size,
            new_coffee_iced=coffee_iced,
            new_bagel=bagel,
            new_bagel_quantity=bagel_qty,
            new_bagel_type=bagel_type,
            new_side_item=side_item,
            new_side_item_quantity=side_item_qty,
        )

    # If only one item found, we can still return it
    if menu_item:
        return OpenInputResponse(new_menu_item=menu_item, new_menu_item_quantity=menu_item_qty)
    if coffee_type:
        return OpenInputResponse(
            new_coffee=True,
            new_coffee_type=coffee_type,
            new_coffee_quantity=coffee_qty,
            new_coffee_size=coffee_size,
            new_coffee_iced=coffee_iced,
        )
    if bagel:
        return OpenInputResponse(new_bagel=True, new_bagel_quantity=bagel_qty, new_bagel_type=bagel_type)
    if side_item:
        return OpenInputResponse(new_side_item=side_item, new_side_item_quantity=side_item_qty)

    return None


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
    cleaned = input_lower
    for phrase in ["ham and cheese", "ham and egg", "bacon and egg", "lox and cream cheese",
                   "salt and pepper", "cream cheese and lox", "eggs and bacon", "black and white",
                   "spinach and feta"]:
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
  - If bagels have DIFFERENT configurations, populate bagel_details list with each bagel's config
- If ordering coffee/drink (IMPORTANT: latte, cappuccino, espresso, americano, macchiato, mocha, drip coffee, cold brew, tea, and similar beverages are ALWAYS coffee orders - use new_coffee fields, NOT new_menu_item):
  - Set new_coffee=true
  - Set new_coffee_quantity to the number of drinks (e.g., "3 diet cokes" -> 3, "two coffees" -> 2, default 1)
  - Set new_coffee_type if specified (e.g., "latte", "cappuccino", "drip coffee", "diet coke", "coke")
  - Set new_coffee_size if specified ("small", "medium", "large") - note: size may not be specified initially
  - Set new_coffee_iced=true if they want iced, false if they want hot, null if not specified
  - Set new_coffee_milk if specified (e.g., "oat", "almond", "skim", "whole"). "black" means no milk.
  - Set new_coffee_sweetener if specified (e.g., "sugar", "splenda", "stevia", "equal")
  - Set new_coffee_sweetener_quantity for number of sweeteners (e.g., "two sugars" = 2, "2 splenda" = 2)
  - Set new_coffee_flavor_syrup if specified (e.g., "vanilla", "caramel", "hazelnut")
- If they're done ordering ("that's all", "nothing else", "no", "nope", "I'm good"), set done_ordering=true
- If just greeting ("hi", "hello"), set is_greeting=true

IMPORTANT: When parsing quantities, recognize both spelled-out words AND numeric digits:
- "two" / "2" = 2
- "three" / "3" = 3
- "four" / "4" = 4
- "five" / "5" = 5

Examples:
- "can I get the chipotle egg omelette" -> new_menu_item: "The Chipotle Egg Omelette", new_menu_item_quantity: 1
- "3 tuna salad sandwiches" -> new_menu_item: "Tuna Salad Sandwich", new_menu_item_quantity: 3
- "two western omelettes" -> new_menu_item: "Western Omelette", new_menu_item_quantity: 2
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

Speed menu bagel orders (pre-configured sandwiches):
- These are specific named menu items that come pre-configured: "The Classic", "The Classic BEC",
  "The Traditional", "The Leo", "The Max Zucker", "The Avocado Toast", "The Chelsea Club",
  "The Flatiron Traditional", "The Old School Tuna Sandwich"
- When user orders these by name, set new_speed_menu_bagel=true and new_speed_menu_bagel_name to the item name
- "3 Classics" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic", new_speed_menu_bagel_quantity: 3
- "The Leo please" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Leo"
- "two Traditionals toasted" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Traditional", new_speed_menu_bagel_quantity: 2, new_speed_menu_bagel_toasted: true
- "a Max Zucker" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Max Zucker"
- "Classic BEC" -> new_speed_menu_bagel: true, new_speed_menu_bagel_name: "The Classic BEC"
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
        self._menu_data = menu_data or {}
        self.model = model
        # Build spread types from database cheese_types
        self._spread_types = _build_spread_types_from_menu(
            self._menu_data.get("cheese_types", [])
        )

    @property
    def menu_data(self) -> dict:
        return self._menu_data

    @menu_data.setter
    def menu_data(self, value: dict) -> None:
        self._menu_data = value or {}
        # Rebuild spread types when menu_data changes
        self._spread_types = _build_spread_types_from_menu(
            self._menu_data.get("cheese_types", [])
        )

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

        # === PHASE 3: Derive phase from OrderTask state ===
        # Phase is now computed from the orchestrator, not manually tracked.
        # This ensures phase always reflects the actual order state.
        # Note: is_configuring_item() takes precedence (based on pending_item_ids)
        if not state.is_configuring_item():
            self._transition_to_next_slot(state, order)

        logger.info("STATE MACHINE: Processing '%s' in phase %s (pending_field=%s, pending_items=%s)",
                   user_input[:50], state.phase.value, state.pending_field, state.pending_item_ids)

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
        elif state.phase == OrderPhase.CHECKOUT_PHONE:
            result = self._handle_phone(user_input, state, order)
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

        # === PHASE 1: Slot Orchestrator Comparison ===
        # Compare FlowState phase with what SlotOrchestrator derives
        # This logging helps validate the slot-filling architecture before migration
        self._log_slot_comparison(result.state, result.order)

        return result

    def _log_slot_comparison(self, state: FlowState, order: OrderTask) -> None:
        """
        Compare FlowState phase with SlotOrchestrator-derived phase.

        This is Phase 1 of the slot orchestrator migration - running both
        systems in parallel and logging any discrepancies.
        """
        try:
            orchestrator = SlotOrchestrator(order)
            orch_phase = orchestrator.get_current_phase()
            flow_phase = state.phase.value

            # Map FlowState phases to orchestrator phases for comparison
            # Some phases don't have direct mappings
            phase_mapping = {
                "greeting": "taking_items",  # Greeting → taking_items after first message
                "taking_items": "taking_items",
                "configuring_item": "configuring_item",
                "checkout_delivery": "checkout_delivery",
                "checkout_name": "checkout_name",
                "checkout_confirm": "checkout_confirm",
                "checkout_payment_method": "checkout_payment_method",
                "checkout_phone": "checkout_notification",  # Phone is part of notification
                "checkout_email": "checkout_notification",  # Email is part of notification
                "complete": "complete",
                "cancelled": "complete",  # Cancelled is a terminal state
            }

            expected_orch_phase = phase_mapping.get(flow_phase, flow_phase)

            # Get next slot for additional context
            next_slot = orchestrator.get_next_slot()
            next_slot_info = f"{next_slot.category.value}" if next_slot else "none"

            # Check for mismatch
            # Note: Some mismatches are expected due to architecture differences
            if orch_phase != expected_orch_phase:
                slot_logger.warning(
                    "SLOT MISMATCH: FlowState=%s (expected_orch=%s), Orchestrator=%s, next_slot=%s",
                    flow_phase, expected_orch_phase, orch_phase, next_slot_info
                )
            else:
                slot_logger.debug(
                    "SLOT MATCH: FlowState=%s, Orchestrator=%s, next_slot=%s",
                    flow_phase, orch_phase, next_slot_info
                )

            # Log slot progress for visibility
            progress = orchestrator.get_progress()
            filled_slots = [k for k, v in progress.items() if v]
            empty_slots = [k for k, v in progress.items() if not v]
            slot_logger.debug(
                "SLOT PROGRESS: filled=%s, empty=%s",
                filled_slots, empty_slots
            )

        except Exception as e:
            slot_logger.error("SLOT COMPARISON ERROR: %s", e)

    def _derive_next_phase_from_slots(self, order: OrderTask) -> OrderPhase:
        """
        Use SlotOrchestrator to determine the next phase.

        This is Phase 2 of the migration - using the orchestrator to drive
        phase transitions instead of hardcoded assignments.
        """
        orchestrator = SlotOrchestrator(order)

        # Check if any items are being configured
        current_item = order.items.get_current_item()
        if current_item is not None:
            return OrderPhase.CONFIGURING_ITEM

        next_slot = orchestrator.get_next_slot()
        if next_slot is None:
            return OrderPhase.COMPLETE

        # Map slot categories to OrderPhase values
        phase_map = {
            SlotCategory.ITEMS: OrderPhase.TAKING_ITEMS,
            SlotCategory.DELIVERY_METHOD: OrderPhase.CHECKOUT_DELIVERY,
            SlotCategory.DELIVERY_ADDRESS: OrderPhase.CHECKOUT_DELIVERY,  # Address is part of delivery
            SlotCategory.CUSTOMER_NAME: OrderPhase.CHECKOUT_NAME,
            SlotCategory.ORDER_CONFIRM: OrderPhase.CHECKOUT_CONFIRM,
            SlotCategory.PAYMENT_METHOD: OrderPhase.CHECKOUT_PAYMENT_METHOD,
            SlotCategory.NOTIFICATION: OrderPhase.CHECKOUT_PHONE,  # Will be refined later
        }
        return phase_map.get(next_slot.category, OrderPhase.TAKING_ITEMS)

    def _transition_to_next_slot(self, state: FlowState, order: OrderTask) -> None:
        """
        Update state.phase based on SlotOrchestrator.

        This replaces hardcoded phase transitions like:
            state.phase = OrderPhase.CHECKOUT_NAME

        With orchestrator-driven transitions that look at what's actually
        filled in the order.
        """
        next_phase = self._derive_next_phase_from_slots(order)
        if state.phase != next_phase:
            logger.info("SLOT TRANSITION: %s -> %s", state.phase.value, next_phase.value)
        state.phase = next_phase

    def _handle_greeting(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle greeting phase."""
        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        logger.info(
            "Greeting phase parsed: is_greeting=%s, unclear=%s, new_bagel=%s, quantity=%d",
            parsed.is_greeting,
            parsed.unclear,
            parsed.new_bagel,
            parsed.new_bagel_quantity,
        )

        if parsed.is_greeting or parsed.unclear:
            # Phase will be derived as TAKING_ITEMS by orchestrator on next turn
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

        # Phase is derived from orchestrator, no need to set explicitly
        return self._handle_taking_items_with_parsed(parsed, state, order, extracted_modifiers, user_input)

    def _handle_taking_items(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle taking new item orders."""
        parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)

        # Extract modifiers from raw input (keyword-based, no LLM)
        extracted_modifiers = extract_modifiers_from_input(user_input)
        if extracted_modifiers.has_modifiers():
            logger.info("Extracted modifiers from input: %s", extracted_modifiers)

        return self._handle_taking_items_with_parsed(parsed, state, order, extracted_modifiers, user_input)

    def _handle_taking_items_with_parsed(
        self,
        parsed: OpenInputResponse,
        state: FlowState,
        order: OrderTask,
        extracted_modifiers: ExtractedModifiers | None = None,
        raw_user_input: str | None = None,
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

        # Track items added for multi-item orders
        items_added = []
        last_result = None

        if parsed.new_menu_item:
            # Check if this "menu item" is actually a coffee/beverage that was misparsed
            menu_item_lower = parsed.new_menu_item.lower()
            coffee_beverage_types = {
                "coffee", "latte", "cappuccino", "espresso", "americano", "macchiato",
                "mocha", "cold brew", "tea", "chai", "matcha", "hot chocolate",
                "iced coffee", "iced latte", "iced cappuccino", "iced americano",
            }
            if menu_item_lower in coffee_beverage_types or any(bev in menu_item_lower for bev in coffee_beverage_types):
                # Redirect to coffee handling
                # Extract coffee modifiers deterministically from raw input since LLM may have missed them
                coffee_mods = ExtractedCoffeeModifiers()
                if raw_user_input:
                    coffee_mods = extract_coffee_modifiers_from_input(raw_user_input)
                    logger.info("Extracted coffee modifiers from raw input: sweetener=%s (qty=%d), syrup=%s",
                               coffee_mods.sweetener, coffee_mods.sweetener_quantity, coffee_mods.flavor_syrup)

                # Use LLM-parsed values if available, otherwise use deterministically extracted values
                sweetener = parsed.new_coffee_sweetener or coffee_mods.sweetener
                sweetener_qty = parsed.new_coffee_sweetener_quantity if parsed.new_coffee_sweetener else coffee_mods.sweetener_quantity
                flavor_syrup = parsed.new_coffee_flavor_syrup or coffee_mods.flavor_syrup

                logger.info("Redirecting misparsed menu item '%s' to coffee handler (sweetener=%s, qty=%d, syrup=%s)",
                           parsed.new_menu_item, sweetener, sweetener_qty, flavor_syrup)
                last_result = self._add_coffee(
                    parsed.new_menu_item,  # Use as coffee type
                    parsed.new_coffee_size,
                    parsed.new_coffee_iced,
                    parsed.new_coffee_milk,
                    sweetener,
                    sweetener_qty,
                    flavor_syrup,
                    parsed.new_menu_item_quantity,
                    state,
                    order,
                )
                items_added.append(parsed.new_menu_item)
            else:
                last_result = self._add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, state, order)
                items_added.append(parsed.new_menu_item)
                # If there's also a side item, add it too
                if parsed.new_side_item:
                    side_name = self._add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)
                    items_added.append(side_name)

            # Check if there's ALSO a coffee order in the same message
            if parsed.new_coffee and parsed.new_coffee_type:
                coffee_result = self._add_coffee(
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
                items_added.append(parsed.new_coffee_type)
                # Combine the messages
                if last_result and coffee_result:
                    combined_items = ", ".join(items_added)
                    last_result = StateMachineResult(
                        message=f"Got it, {combined_items}. Anything else?",
                        state=state,
                        order=order,
                    )

            if last_result:
                return last_result

        if parsed.new_side_item and not parsed.new_bagel:
            # Standalone side item order (no bagel)
            return self._add_side_item_with_response(parsed.new_side_item, parsed.new_side_item_quantity, state, order)

        if parsed.new_bagel:
            # Check if we have multiple bagels with different configs
            if parsed.bagel_details and len(parsed.bagel_details) > 0:
                # Multiple bagels with different configurations
                # Pass extracted_modifiers to apply to the first bagel
                result = self._add_bagels_from_details(
                    parsed.bagel_details, state, order, extracted_modifiers
                )
            elif parsed.new_bagel_quantity > 1:
                # Multiple bagels with same (or no) configuration
                # Pass extracted_modifiers to apply to the first bagel
                result = self._add_bagels(
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
                result = self._add_bagel(
                    bagel_type=parsed.new_bagel_type,
                    toasted=parsed.new_bagel_toasted,
                    spread=parsed.new_bagel_spread,
                    spread_type=parsed.new_bagel_spread_type,
                    state=state,
                    order=order,
                    extracted_modifiers=extracted_modifiers,
                )
            # If there's also a side item, add it too
            side_name = None
            if parsed.new_side_item:
                side_name = self._add_side_item(parsed.new_side_item, parsed.new_side_item_quantity, order)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee:
                coffee_result = self._add_coffee(
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
                # Combine the messages (bagel + optional side + coffee)
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                coffee_desc = parsed.new_coffee_type or "drink"
                items_list = [bagel_desc]
                if side_name:
                    items_list.append(side_name)
                items_list.append(coffee_desc)
                combined_items = ", ".join(items_list)
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    state=state,
                    order=order,
                )

            # If there's a side item but no coffee, update the result message to include it
            if side_name:
                bagel_desc = f"{parsed.new_bagel_quantity} bagel{'s' if parsed.new_bagel_quantity > 1 else ''}"
                return StateMachineResult(
                    message=f"Got it, {bagel_desc} and {side_name}. Anything else?",
                    state=state,
                    order=order,
                )
            return result

        if parsed.new_coffee:
            coffee_result = self._add_coffee(
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
            items_added.append(parsed.new_coffee_type or "drink")

            # Check if there's ALSO a menu item in the same message
            if parsed.new_menu_item:
                menu_result = self._add_menu_item(parsed.new_menu_item, parsed.new_menu_item_quantity, state, order)
                items_added.append(parsed.new_menu_item)
                # Combine the messages
                combined_items = ", ".join(items_added)
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    state=state,
                    order=order,
                )
            return coffee_result

        if parsed.new_speed_menu_bagel:
            speed_result = self._add_speed_menu_bagel(
                parsed.new_speed_menu_bagel_name,
                parsed.new_speed_menu_bagel_quantity,
                parsed.new_speed_menu_bagel_toasted,
                state,
                order,
            )
            items_added.append(parsed.new_speed_menu_bagel_name)

            # Check if there's ALSO a coffee in the same message
            if parsed.new_coffee:
                coffee_result = self._add_coffee(
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
                items_added.append(parsed.new_coffee_type or "drink")
                # Combine the messages
                combined_items = ", ".join(items_added)
                return StateMachineResult(
                    message=f"Got it, {combined_items}. Anything else?",
                    state=state,
                    order=order,
                )
            return speed_result

        if parsed.needs_soda_clarification:
            return self._handle_soda_clarification(state, order)

        if parsed.menu_query:
            return self._handle_menu_query(parsed.menu_query_type, state, order)

        if parsed.asking_signature_menu:
            return self._handle_signature_menu_inquiry(parsed.signature_menu_type, state, order)

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
        elif state.pending_field == "speed_menu_bagel_toasted":
            return self._handle_speed_menu_bagel_toasted(user_input, item, state, order)
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

        # Apply to the item (could be omelette's bagel_choice, sandwich's bagel_choice, or bagel's bagel_type)
        if isinstance(item, MenuItemTask):
            item.bagel_choice = parsed.bagel_type

            # For spread/salad sandwiches, continue to toasted question
            if item.menu_item_type in ("spread_sandwich", "salad_sandwich"):
                state.pending_field = "toasted"
                return StateMachineResult(
                    message="Would you like that toasted?",
                    state=state,
                    order=order,
                )

            # For omelettes and other menu items, mark complete
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
        item: Union[BagelItemTask, MenuItemTask],
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for bagel or sandwich."""
        parsed = parse_toasted_choice(user_input, model=self.model)

        if parsed.toasted is None:
            return StateMachineResult(
                message="Would you like that toasted? Yes or no?",
                state=state,
                order=order,
            )

        item.toasted = parsed.toasted

        # For MenuItemTask (spread/salad sandwiches), mark complete after toasted
        if isinstance(item, MenuItemTask):
            item.mark_complete()
            state.clear_pending()
            return self._get_next_question(state, order)

        # For BagelItemTask, check if spread is already set
        if item.spread is not None:
            # Spread already specified, bagel is complete
            self.recalculate_bagel_price(item)
            item.mark_complete()
            state.clear_pending()
            return self._configure_next_incomplete_bagel(state, order)

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
        """Handle pickup/delivery selection and address collection."""
        parsed = parse_delivery_choice(user_input, model=self.model)

        if parsed.choice == "unclear":
            # Check if we're waiting for an address (delivery selected but no address yet)
            if order.delivery_method.order_type == "delivery" and not order.delivery_method.address.street:
                # Try to extract address from input
                if parsed.address:
                    order.delivery_method.address.street = parsed.address
                    self._transition_to_next_slot(state, order)
                    return StateMachineResult(
                        message="Can I get a name for the order?",
                        state=state,
                        order=order,
                    )
                return StateMachineResult(
                    message="What's the delivery address?",
                    state=state,
                    order=order,
                )
            return StateMachineResult(
                message="Is this for pickup or delivery?",
                state=state,
                order=order,
            )

        order.delivery_method.order_type = parsed.choice
        if parsed.address:
            order.delivery_method.address.street = parsed.address

        # Use orchestrator to determine next phase
        # If delivery without address, orchestrator will keep us in delivery phase
        orchestrator = SlotOrchestrator(order)
        next_slot = orchestrator.get_next_slot()

        if next_slot and next_slot.category == SlotCategory.DELIVERY_ADDRESS:
            # Need to collect address
            return StateMachineResult(
                message="What's the delivery address?",
                state=state,
                order=order,
            )

        # Transition to next slot (should be CUSTOMER_NAME)
        self._transition_to_next_slot(state, order)
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
        self._transition_to_next_slot(state, order)

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
        logger.info("CONFIRMATION: handling input '%s', current items: %s",
                   user_input[:50], [i.get_summary() for i in order.items.items])
        parsed = parse_confirmation(user_input, model=self.model)
        logger.info("CONFIRMATION: parse result - wants_changes=%s, confirmed=%s",
                   parsed.wants_changes, parsed.confirmed)

        if parsed.wants_changes:
            # User wants to make changes - reset order_reviewed so orchestrator knows
            order.checkout.order_reviewed = False

            # Try to parse the input for new items
            # e.g., "can I also get a coke?" should add the coke
            item_parsed = parse_open_input(user_input, model=self.model, spread_types=self._spread_types)
            logger.info("CONFIRMATION: parse_open_input result - new_menu_item=%s, new_bagel=%s, new_coffee=%s, new_coffee_type=%s, new_speed_menu_bagel=%s",
                       item_parsed.new_menu_item, item_parsed.new_bagel, item_parsed.new_coffee, item_parsed.new_coffee_type, item_parsed.new_speed_menu_bagel)

            # If they mentioned a new item, process it
            if item_parsed.new_menu_item or item_parsed.new_bagel or item_parsed.new_coffee or item_parsed.new_speed_menu_bagel:
                logger.info("CONFIRMATION: Detected new item! Processing via _handle_taking_items_with_parsed")
                extracted_modifiers = extract_modifiers_from_input(user_input)
                # Use orchestrator to determine phase before processing
                self._transition_to_next_slot(state, order)
                result = self._handle_taking_items_with_parsed(item_parsed, state, order, extracted_modifiers, user_input)

                # Log items in result.order vs original order
                logger.info("CONFIRMATION: result.order items = %s", [i.get_summary() for i in result.order.items.items])
                logger.info("CONFIRMATION: original order items = %s", [i.get_summary() for i in order.items.items])
                logger.info("CONFIRMATION: result.state.phase = %s", result.state.phase)

                # Use orchestrator to determine if we should go back to confirmation
                # If all items complete and we have name and delivery, orchestrator will say ORDER_CONFIRM
                orchestrator = SlotOrchestrator(result.order)
                next_slot = orchestrator.get_next_slot()

                if (next_slot and next_slot.category == SlotCategory.ORDER_CONFIRM and
                    result.order.customer_info.name and
                    result.order.delivery_method.order_type):
                    logger.info("CONFIRMATION: Item added, returning to confirmation (orchestrator says ORDER_CONFIRM)")
                    self._transition_to_next_slot(result.state, result.order)
                    summary = self._build_order_summary(result.order)
                    logger.info("CONFIRMATION: Built summary, items count = %d", len(result.order.items.items))
                    return StateMachineResult(
                        message=f"{summary}\n\nDoes that look right?",
                        state=result.state,
                        order=result.order,
                    )

                return result

            # No new item detected, use orchestrator to determine phase
            self._transition_to_next_slot(state, order)
            return StateMachineResult(
                message="No problem. What would you like to change?",
                state=state,
                order=order,
            )

        if parsed.confirmed:
            # Mark order as reviewed but not yet fully confirmed
            # (confirmed=True is set only when order is complete with email/text choice)
            order.checkout.order_reviewed = True
            # Use orchestrator to determine next phase (should be PAYMENT_METHOD)
            self._transition_to_next_slot(state, order)
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
            # Text selected - set payment method and check for phone
            order.payment.method = "card_link"
            phone = parsed.phone_number or order.customer_info.phone
            if phone:
                order.customer_info.phone = phone
                order.payment.payment_link_destination = phone
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                self._transition_to_next_slot(state, order)  # Should be COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
                    state=state,
                    order=order,
                    is_complete=True,
                )
            else:
                # Need to ask for phone number - orchestrator will say NOTIFICATION
                self._transition_to_next_slot(state, order)
                return StateMachineResult(
                    message="What phone number should I text the confirmation to?",
                    state=state,
                    order=order,
                )

        if parsed.choice == "email":
            # Email selected - set payment method and check for email
            order.payment.method = "card_link"
            if parsed.email_address:
                order.customer_info.email = parsed.email_address
                order.payment.payment_link_destination = parsed.email_address
                order.checkout.generate_order_number()
                order.checkout.confirmed = True  # Now fully confirmed
                self._transition_to_next_slot(state, order)  # Should be COMPLETE
                return StateMachineResult(
                    message=f"Your order number is {order.checkout.short_order_number}. "
                           f"We'll send the confirmation to {parsed.email_address}. "
                           f"Thank you, {order.customer_info.name}!",
                    state=state,
                    order=order,
                    is_complete=True,
                )
            else:
                # Need to ask for email - orchestrator will say NOTIFICATION
                self._transition_to_next_slot(state, order)
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

    def _handle_phone(
        self,
        user_input: str,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle phone number collection for text confirmation."""
        parsed = parse_phone(user_input, model=self.model)

        if not parsed.phone:
            return StateMachineResult(
                message="What's the best phone number to text the order confirmation to?",
                state=state,
                order=order,
            )

        # Store phone and complete the order
        order.customer_info.phone = parsed.phone
        order.payment.payment_link_destination = parsed.phone
        order.checkout.generate_order_number()
        order.checkout.confirmed = True  # Now fully confirmed
        self._transition_to_next_slot(state, order)  # Should be COMPLETE

        return StateMachineResult(
            message=f"Your order number is {order.checkout.short_order_number}. "
                   f"We'll text you when it's ready. Thank you, {order.customer_info.name}!",
            state=state,
            order=order,
            is_complete=True,
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
        self._transition_to_next_slot(state, order)  # Should be COMPLETE

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
        quantity: int,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add a menu item and determine next question."""
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

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

        # If item not found in menu, ask for clarification
        if not menu_item:
            logger.warning("Menu item not found: '%s' - asking for clarification", item_name)
            return StateMachineResult(
                message=f"I'm sorry, I couldn't find '{item_name}' on our menu. Could you try again or ask what we have available?",
                state=state,
                order=order,
            )

        # Use the canonical name from menu if found
        canonical_name = menu_item.get("name", item_name)
        price = menu_item.get("base_price", 0.0)
        menu_item_id = menu_item.get("id")
        category = menu_item.get("item_type", "")  # item_type slug like "spread_sandwich"

        # Check if it's an omelette (requires side choice)
        is_omelette = "omelette" in canonical_name.lower() or "omelet" in canonical_name.lower()

        # Check if it's a spread or salad sandwich (requires toasted question)
        is_spread_or_salad_sandwich = category in ("spread_sandwich", "salad_sandwich")

        logger.info(
            "Menu item check: canonical_name='%s', category='%s', is_omelette=%s, is_spread_salad=%s, quantity=%d",
            canonical_name,
            category,
            is_omelette,
            is_spread_or_salad_sandwich,
            quantity,
        )

        # Determine the menu item type for tracking
        if is_omelette:
            item_type = "omelette"
        elif is_spread_or_salad_sandwich:
            item_type = category  # "spread_sandwich" or "salad_sandwich"
        else:
            item_type = None

        # Create the requested quantity of items
        first_item = None
        for i in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                requires_side_choice=is_omelette,
                menu_item_type=item_type,
            )
            item.mark_in_progress()
            order.items.add_item(item)
            if first_item is None:
                first_item = item

        logger.info("Added %d menu item(s): %s (price: $%.2f each, id: %s)", quantity, canonical_name, price, menu_item_id)

        if is_omelette:
            # Set state to wait for side choice (applies to first item, others will be configured after)
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = first_item.id
            state.pending_field = "side_choice"
            return StateMachineResult(
                message=f"Would you like a bagel or fruit salad with your {canonical_name}?",
                state=state,
                order=order,
            )
        elif is_spread_or_salad_sandwich:
            # For spread/salad sandwiches, ask for bagel choice first, then toasted
            state.phase = OrderPhase.CONFIGURING_ITEM
            state.pending_item_id = first_item.id
            state.pending_field = "bagel_choice"
            return StateMachineResult(
                message="What kind of bagel would you like that on?",
                state=state,
                order=order,
            )
        else:
            # Mark all items complete (non-omelettes don't need configuration)
            for item in order.items.items:
                if item.menu_item_name == canonical_name and item.status == TaskStatus.IN_PROGRESS:
                    item.mark_complete()
            return self._get_next_question(state, order)

    def _add_side_item(
        self,
        side_item_name: str,
        quantity: int,
        order: OrderTask,
    ) -> str:
        """Add a side item to the order without returning a response.

        Used when a side item is ordered alongside another item (e.g., "bagel with a side of sausage").

        Returns:
            The canonical name of the side item (for use in confirmation messages).
        """
        quantity = max(1, quantity)

        # Look up the side item in the menu
        menu_item = self._lookup_menu_item(side_item_name)

        # Use canonical name and price from menu if found
        canonical_name = menu_item.get("name", side_item_name) if menu_item else side_item_name
        price = menu_item.get("base_price", 0.0) if menu_item else 0.0
        menu_item_id = menu_item.get("id") if menu_item else None

        # Create the side item(s)
        for _ in range(quantity):
            item = MenuItemTask(
                menu_item_name=canonical_name,
                menu_item_id=menu_item_id,
                unit_price=price,
                menu_item_type="side",
            )
            item.mark_complete()  # Side items don't need configuration
            order.items.add_item(item)

        logger.info("Added %d side item(s): %s (price: $%.2f each)", quantity, canonical_name, price)
        return canonical_name

    def _add_side_item_with_response(
        self,
        side_item_name: str,
        quantity: int,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add a side item to the order and return an appropriate response.

        Used when a side item is ordered on its own (e.g., "I'll have a side of bacon").
        """
        self._add_side_item(side_item_name, quantity, order)

        # Get the canonical name for the response
        menu_item = self._lookup_menu_item(side_item_name)
        canonical_name = menu_item.get("name", side_item_name) if menu_item else side_item_name

        # Pluralize if quantity > 1
        if quantity > 1:
            item_display = f"{quantity} {canonical_name}s"
        else:
            item_display = canonical_name

        return StateMachineResult(
            message=f"I've added {item_display} to your order. Anything else?",
            state=state,
            order=order,
        )

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
            base_price, sandwich_protein, extras, spread, spread_type
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
                base_price, sandwich_protein, extras, bagel_spread, spread_type
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
                base_price, sandwich_protein, extras, spread, details.spread_type
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

        # No incomplete bagels - generate confirmation message for the bagels
        # Get all completed bagels to summarize
        completed_bagels = [item for item in order.items.items
                          if isinstance(item, BagelItemTask) and item.status == TaskStatus.COMPLETE]

        if completed_bagels:
            # Get the most recently completed bagel(s) summary
            last_bagel = completed_bagels[-1]
            bagel_summary = last_bagel.get_summary()

            # Count identical bagels at the end
            count = 0
            for bagel in reversed(completed_bagels):
                if bagel.get_summary() == bagel_summary:
                    count += 1
                else:
                    break

            if count > 1:
                summary = f"{count} {bagel_summary}s" if not bagel_summary.endswith("s") else f"{count} {bagel_summary}"
            else:
                summary = bagel_summary

            state.clear_pending()
            # Phase will be derived by orchestrator (no pending items = TAKING_ITEMS or checkout)
            return StateMachineResult(
                message=f"Got it, {summary}. Anything else?",
                state=state,
                order=order,
            )

        # Fallback to generic next question
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
        logger.info(
            "ADD COFFEE: type=%s, size=%s, iced=%s, sweetener=%s (qty=%d), syrup=%s",
            coffee_type, size, iced, sweetener, sweetener_quantity, flavor_syrup
        )
        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item from menu to get price and skip_config flag
        menu_item = self._lookup_menu_item(coffee_type) if coffee_type else None
        price = menu_item.get("base_price", 2.50) if menu_item else self._lookup_coffee_price(coffee_type)

        # Check if this drink should skip configuration questions
        # Coffee beverages (cappuccino, latte, etc.) ALWAYS need configuration regardless of database flag
        # This overrides the menu_item skip_config because item_type "beverage" has skip_config=1
        # but that's intended for sodas/bottled drinks, not coffee drinks
        coffee_type_lower = (coffee_type or "").lower()
        is_configurable_coffee = coffee_type_lower in COFFEE_BEVERAGE_TYPES or any(
            bev in coffee_type_lower for bev in COFFEE_BEVERAGE_TYPES
        )

        should_skip_config = False
        if is_configurable_coffee:
            # Coffee/tea drinks always need size and hot/iced configuration
            logger.info("ADD COFFEE: skip_config=False (configurable coffee beverage: %s)", coffee_type)
            should_skip_config = False
        elif menu_item and menu_item.get("skip_config"):
            logger.info("ADD COFFEE: skip_config=True (from menu_item)")
            should_skip_config = True
        elif is_soda_drink(coffee_type):
            # Fallback for items not in database
            logger.info("ADD COFFEE: skip_config=True (soda drink)")
            should_skip_config = True
        else:
            logger.info("ADD COFFEE: skip_config=False, will need configuration")

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
        # Find all coffee items (both complete and incomplete) to determine total count
        all_coffees = [
            item for item in order.items.items
            if isinstance(item, CoffeeItemTask)
        ]
        total_coffees = len(all_coffees)

        logger.info(
            "CONFIGURE COFFEE: Found %d total coffee items (total items: %d)",
            total_coffees, len(order.items.items)
        )

        # Configure coffees one at a time (fully configure each before moving to next)
        for idx, coffee in enumerate(all_coffees):
            if coffee.status != TaskStatus.IN_PROGRESS:
                continue

            coffee_num = idx + 1

            logger.info(
                "CONFIGURE COFFEE: Checking coffee id=%s, size=%s, iced=%s, status=%s",
                coffee.id, coffee.size, coffee.iced, coffee.status
            )

            # Build ordinal descriptor if multiple coffees
            if total_coffees > 1:
                ordinal = self._get_ordinal(coffee_num)
                coffee_desc = f"the {ordinal} coffee"
            else:
                coffee_desc = None

            # Ask about size first
            if not coffee.size:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = coffee.id
                state.pending_field = "coffee_size"
                if coffee_desc:
                    message = f"For {coffee_desc}, small, medium, or large?"
                else:
                    message = "What size would you like? Small, medium, or large?"
                return StateMachineResult(
                    message=message,
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

            # This coffee is complete - recalculate price with modifiers
            self.recalculate_coffee_price(coffee)
            coffee.mark_complete()

        # All coffees configured - no incomplete ones found
        logger.info("CONFIGURE COFFEE: No incomplete coffees, going to next question")
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
        input_lower = user_input.lower()

        # Try deterministic parsing first for hot/iced
        iced = None
        if re.search(r'\b(iced|cold)\b', input_lower):
            iced = True
        elif re.search(r'\b(hot|warm|regular)\b', input_lower):
            iced = False

        # Fall back to LLM if unclear
        if iced is None:
            parsed = parse_coffee_style(user_input, model=self.model)
            iced = parsed.iced

        if iced is None:
            return StateMachineResult(
                message="Would you like that hot or iced?",
                state=state,
                order=order,
            )

        item.iced = iced

        # Also extract any sweetener/syrup mentioned with the hot/iced response
        # e.g., "hot with 2 splenda" or "iced with vanilla"
        coffee_mods = extract_coffee_modifiers_from_input(user_input)
        if coffee_mods.sweetener and not item.sweetener:
            item.sweetener = coffee_mods.sweetener
            item.sweetener_quantity = coffee_mods.sweetener_quantity
            logger.info(f"Extracted sweetener from style response: {coffee_mods.sweetener_quantity} {coffee_mods.sweetener}")
        if coffee_mods.flavor_syrup and not item.flavor_syrup:
            item.flavor_syrup = coffee_mods.flavor_syrup
            logger.info(f"Extracted syrup from style response: {coffee_mods.flavor_syrup}")

        # Coffee is now complete - recalculate price with modifiers
        self.recalculate_coffee_price(item)
        item.mark_complete()
        state.clear_pending()

        # Check for more incomplete coffees before moving on
        return self._configure_next_incomplete_coffee(state, order)

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
    # Speed Menu Bagel Handlers
    # =========================================================================

    def _add_speed_menu_bagel(
        self,
        item_name: str | None,
        quantity: int,
        toasted: bool | None,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Add speed menu bagel(s) to the order."""
        if not item_name:
            return StateMachineResult(
                message="Which speed menu item would you like?",
                state=state,
                order=order,
            )

        # Ensure quantity is at least 1
        quantity = max(1, quantity)

        # Look up item from menu to get price
        menu_item = self._lookup_menu_item(item_name)
        price = menu_item.get("base_price", 10.00) if menu_item else 10.00
        menu_item_id = menu_item.get("id") if menu_item else None

        # Create the requested quantity of items
        for _ in range(quantity):
            item = SpeedMenuBagelItemTask(
                menu_item_name=item_name,
                menu_item_id=menu_item_id,
                toasted=toasted,
                unit_price=price,
            )
            if toasted is not None:
                # Toasted preference already specified - mark complete
                item.mark_complete()
            else:
                # Need to ask about toasting
                item.mark_in_progress()
            order.items.add_item(item)

        # If toasted was specified, we're done
        if toasted is not None:
            state.clear_pending()
            return self._get_next_question(state, order)

        # Need to configure toasted preference
        return self._configure_next_incomplete_speed_menu_bagel(state, order)

    def _configure_next_incomplete_speed_menu_bagel(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Configure the next incomplete speed menu bagel item."""
        # Find incomplete speed menu bagel items
        incomplete_items = [
            item for item in order.items.items
            if isinstance(item, SpeedMenuBagelItemTask) and item.status == TaskStatus.IN_PROGRESS
        ]

        if not incomplete_items:
            state.clear_pending()
            return self._get_next_question(state, order)

        # Configure items one at a time
        for item in incomplete_items:
            if item.toasted is None:
                state.phase = OrderPhase.CONFIGURING_ITEM
                state.pending_item_id = item.id
                state.pending_field = "speed_menu_bagel_toasted"
                return StateMachineResult(
                    message="Would you like that toasted?",
                    state=state,
                    order=order,
                )

            # This item is complete
            item.mark_complete()

        # All items configured
        state.clear_pending()
        return self._get_next_question(state, order)

    def _handle_speed_menu_bagel_toasted(
        self,
        user_input: str,
        item: SpeedMenuBagelItemTask,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle toasted preference for speed menu bagel."""
        parsed = parse_toasted_choice(user_input, model=self.model)

        if parsed.toasted is None:
            return StateMachineResult(
                message="Would you like that toasted?",
                state=state,
                order=order,
            )

        item.toasted = parsed.toasted
        item.mark_complete()
        state.clear_pending()

        return self._get_next_question(state, order)

    # =========================================================================
    # Menu Query Handlers
    # =========================================================================

    def _handle_menu_query(
        self,
        menu_query_type: str | None,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about menu items by type.

        Args:
            menu_query_type: Type of item being queried (e.g., 'beverage', 'bagel', 'sandwich')
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        if not menu_query_type:
            # Generic "what do you have?" - list available types
            available_types = [t.replace("_", " ") for t, items in items_by_type.items() if items]
            if available_types:
                return StateMachineResult(
                    message=f"We have: {', '.join(available_types)}. What would you like?",
                    state=state,
                    order=order,
                )
            return StateMachineResult(
                message="What can I get for you?",
                state=state,
                order=order,
            )

        # Handle spread/cream cheese queries as by-the-pound category
        if menu_query_type in ("spread", "cream_cheese", "cream cheese"):
            return self._list_by_pound_category("spread", state, order)

        # Map common query types to actual item_type slugs
        # - "soda", "water", "juice" -> "beverage" (cold-only drinks)
        # - "coffee", "tea", "latte" -> "sized_beverage" (hot/iced drinks)
        # - "beverage", "drink" -> combine both types
        type_aliases = {
            "coffee": "sized_beverage",
            "tea": "sized_beverage",
            "latte": "sized_beverage",
            "espresso": "sized_beverage",
            "soda": "beverage",
            "water": "beverage",
            "juice": "beverage",
        }

        # Handle "beverage" or "drink" queries by combining both types
        if menu_query_type in ("beverage", "drink"):
            sized_items = items_by_type.get("sized_beverage", [])
            cold_items = items_by_type.get("beverage", [])
            items = sized_items + cold_items
            if items:
                item_list = []
                for item in items[:15]:
                    name = item.get("name", "Unknown")
                    price = item.get("base_price", 0)
                    if price > 0:
                        item_list.append(f"{name} (${price:.2f})")
                    else:
                        item_list.append(name)
                if len(items) > 15:
                    item_list.append(f"...and {len(items) - 15} more")
                if len(item_list) == 1:
                    items_str = item_list[0]
                elif len(item_list) == 2:
                    items_str = f"{item_list[0]} and {item_list[1]}"
                else:
                    items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"
                return StateMachineResult(
                    message=f"Our beverages include: {items_str}. Would you like any of these?",
                    state=state,
                    order=order,
                )
            return StateMachineResult(
                message="I don't have any beverages on the menu right now. Is there anything else I can help you with?",
                state=state,
                order=order,
            )

        lookup_type = type_aliases.get(menu_query_type, menu_query_type)

        # Look up items for the specific type
        items = items_by_type.get(lookup_type, [])

        if not items:
            # Try to suggest what we do have
            available_types = [t.replace("_", " ") for t, i in items_by_type.items() if i]
            type_display = menu_query_type.replace("_", " ")
            if available_types:
                return StateMachineResult(
                    message=f"I don't have any {type_display}s on the menu. We do have: {', '.join(available_types)}. What would you like?",
                    state=state,
                    order=order,
                )
            return StateMachineResult(
                message=f"I'm sorry, I don't have any {type_display}s on the menu. What else can I help you with?",
                state=state,
                order=order,
            )

        # Format the items list with prices
        type_name = menu_query_type.replace("_", " ")
        # Proper pluralization
        if type_name.endswith("ch") or type_name.endswith("s"):
            type_display = type_name + "es"
        else:
            type_display = type_name + "s"

        item_list = []
        for item in items[:15]:  # Limit to 15 items
            name = item.get("name", "Unknown")
            price = item.get("base_price", 0)
            if price > 0:
                item_list.append(f"{name} (${price:.2f})")
            else:
                item_list.append(name)

        if len(items) > 15:
            item_list.append(f"...and {len(items) - 15} more")

        # Format the response
        if len(item_list) == 1:
            items_str = item_list[0]
        elif len(item_list) == 2:
            items_str = f"{item_list[0]} and {item_list[1]}"
        else:
            items_str = ", ".join(item_list[:-1]) + f", and {item_list[-1]}"

        return StateMachineResult(
            message=f"Our {type_display} include: {items_str}. Would you like any of these?",
            state=state,
            order=order,
        )

    def _handle_soda_clarification(
        self,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle when user orders a generic 'soda' without specifying type.

        Asks what kind of soda they want, listing available options.
        """
        # Get beverages from menu data
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}
        beverages = items_by_type.get("beverage", [])

        if beverages:
            # Get just the names of a few common sodas
            soda_names = [item.get("name", "") for item in beverages[:6]]
            # Filter out empty names and format nicely
            soda_names = [name for name in soda_names if name]
            if len(soda_names) > 3:
                soda_list = ", ".join(soda_names[:3]) + ", and others"
            elif len(soda_names) > 1:
                soda_list = ", ".join(soda_names[:-1]) + f", and {soda_names[-1]}"
            else:
                soda_list = soda_names[0] if soda_names else "Coke, Diet Coke, Sprite"

            return StateMachineResult(
                message=f"What kind? We have {soda_list}.",
                state=state,
                order=order,
            )

        # Fallback if no beverages in menu data
        return StateMachineResult(
            message="What kind? We have Coke, Diet Coke, Sprite, and others.",
            state=state,
            order=order,
        )

    # =========================================================================
    # Signature/Speed Menu Handlers
    # =========================================================================

    def _handle_signature_menu_inquiry(
        self,
        menu_type: str | None,
        state: FlowState,
        order: OrderTask,
    ) -> StateMachineResult:
        """Handle inquiry about signature/speed menu items.

        Args:
            menu_type: Specific type like 'signature_sandwich' or 'speed_menu_bagel',
                      or None for all signature items
        """
        items_by_type = self.menu_data.get("items_by_type", {}) if self.menu_data else {}

        # If a specific type is requested, look it up directly
        if menu_type:
            items = items_by_type.get(menu_type, [])
            # Get the display name from the type slug (proper pluralization)
            type_name = menu_type.replace("_", " ")
            if type_name.endswith("ch") or type_name.endswith("s"):
                type_display_name = type_name + "es"
            else:
                type_display_name = type_name + "s"
        else:
            # No specific type - combine signature_sandwich and speed_menu_bagel items
            items = []
            items.extend(items_by_type.get("signature_sandwich", []))
            items.extend(items_by_type.get("speed_menu_bagel", []))
            type_display_name = "signature menu options"

        if not items:
            return StateMachineResult(
                message="We don't have any pre-made signature items on the menu right now. Would you like to build your own?",
                state=state,
                order=order,
            )

        # Build a nice list of items with prices
        item_descriptions = []
        for item in items:
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

        message = f"Our {type_display_name} are: {items_list}. Would you like any of these?"

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
            # Phase derived by orchestrator
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
        # For spreads, fetch from menu_data (cheese_types contains cream cheese options)
        if category == "spread" and self.menu_data:
            cheese_types = self.menu_data.get("cheese_types", [])
            # Filter to only cream cheese, spreads, and butter
            items = [
                name for name in cheese_types
                if any(kw in name.lower() for kw in ["cream cheese", "spread", "butter"])
            ]
        else:
            items = BY_POUND_ITEMS.get(category, [])
        category_name = BY_POUND_CATEGORY_NAMES.get(category, category)

        if not items:
            state.clear_pending()
            # Phase derived by orchestrator
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
        # Phase derived by orchestrator

        # For spreads, don't say "by the pound" since they're also used on bagels
        if category == "spread":
            message = f"Our {category_name} include: {items_list}. Would you like any of these, or something else?"
        else:
            message = f"Our {category_name} by the pound include: {items_list}. Would you like any of these, or something else?"

        return StateMachineResult(
            message=message,
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
        # Phase derived by orchestrator
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
            # Count consecutive identical items at the end of the list
            last_item = items[-1]
            last_summary = last_item.get_summary()
            count = 0
            for item in reversed(items):
                if item.get_summary() == last_summary:
                    count += 1
                else:
                    break

            # Show quantity if more than 1 identical item
            if count > 1:
                summary = f"{count} {last_summary}s" if not last_summary.endswith("s") else f"{count} {last_summary}"
            else:
                summary = last_summary

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
        """Transition to checkout phase.

        If we already have delivery type and customer name (e.g., user added an item
        during confirmation), skip directly to order confirmation.
        """
        state.clear_pending()

        # Use orchestrator to determine next step in checkout
        self._transition_to_next_slot(state, order)

        # Check if we already have all the info we need (orchestrator would have set CONFIRM phase)
        if order.delivery_method.order_type and order.customer_info.name:
            # Skip to confirmation - we already have the customer info
            logger.info("CHECKOUT: Skipping to confirmation (already have name=%s, delivery=%s)",
                       order.customer_info.name, order.delivery_method.order_type)
            summary = self._build_order_summary(order)
            return StateMachineResult(
                message=f"{summary}\n\nDoes that look right?",
                state=state,
                order=order,
            )

        # Normal checkout flow - orchestrator determines if we need delivery or name
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
        """Build order summary string with consolidated identical items and total."""
        lines = ["Here's your order:"]

        # Group items by their summary string to consolidate identical items
        from collections import defaultdict
        item_data: dict[str, dict] = defaultdict(lambda: {"count": 0, "total_price": 0.0})
        for item in order.items.get_active_items():
            summary = item.get_summary()
            price = item.unit_price * getattr(item, 'quantity', 1)
            item_data[summary]["count"] += 1
            item_data[summary]["total_price"] += price

        # Build consolidated lines (no individual prices, just total at end)
        for summary, data in item_data.items():
            count = data["count"]
            if count > 1:
                # Pluralize: "3 cokes" instead of "3× coke"
                plural = f"{summary}s" if not summary.endswith("s") else summary
                lines.append(f"• {count} {plural}")
            else:
                lines.append(f"• {summary}")

        # Add "plus tax" note
        subtotal = order.items.get_subtotal()
        if subtotal > 0:
            lines.append(f"\nThat's ${subtotal:.2f} plus tax.")

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
            # Look for specific specialty bagel as menu item first
            bagel_name = f"{bagel_type.title()} Bagel" if "bagel" not in bagel_type_lower else bagel_type
            menu_item = self._lookup_menu_item(bagel_name)
            if menu_item:
                logger.info("Found specialty bagel: %s ($%.2f)", menu_item.get("name"), menu_item.get("base_price"))
                return menu_item.get("base_price", 2.50)

            # Try bread_prices from menu_data (ingredients table)
            if self.menu_data:
                bread_prices = self.menu_data.get("bread_prices", {})
                # Try exact match
                bagel_key = bagel_name.lower()
                if bagel_key in bread_prices:
                    price = bread_prices[bagel_key]
                    logger.info("Found specialty bagel in bread_prices: %s ($%.2f)", bagel_name, price)
                    return price
                # Try partial match for specialty type (e.g., "gluten free bagel")
                for bread_name, price in bread_prices.items():
                    if any(specialty in bread_name for specialty in specialty_bagels):
                        logger.info("Found specialty bagel in bread_prices (partial): %s ($%.2f)", bread_name, price)
                        return price

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

    def _lookup_spread_price(self, spread: str, spread_type: str | None = None) -> float:
        """
        Look up price for a spread, considering the spread type/flavor.

        First tries the full spread name (e.g., "Tofu Cream Cheese") from cheese_prices,
        then falls back to DEFAULT_MODIFIER_PRICES for generic spread.

        Args:
            spread: Base spread name (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

        Returns:
            Price for the spread
        """
        # Build full spread name by combining type + spread (e.g., "tofu cream cheese")
        if spread_type:
            full_spread_name = f"{spread_type} {spread}".lower()
        else:
            full_spread_name = spread.lower()

        # Try cheese_prices from menu_data first
        if self.menu_data:
            cheese_prices = self.menu_data.get("cheese_prices", {})

            # Try full name first (e.g., "tofu cream cheese")
            if full_spread_name in cheese_prices:
                price = cheese_prices[full_spread_name]
                logger.debug(
                    "Found spread price from cheese_prices: %s = $%.2f",
                    full_spread_name, price
                )
                return price

            # Try without type as fallback (e.g., "plain cream cheese" or just "cream cheese")
            spread_lower = spread.lower()
            plain_spread = f"plain {spread_lower}"
            if plain_spread in cheese_prices:
                price = cheese_prices[plain_spread]
                logger.debug(
                    "Found spread price from cheese_prices (plain): %s = $%.2f",
                    plain_spread, price
                )
                return price

        # Fall back to DEFAULT_MODIFIER_PRICES
        default_price = self.DEFAULT_MODIFIER_PRICES.get(spread.lower(), 0.0)
        if default_price > 0:
            logger.debug(
                "Using default spread price: %s = $%.2f",
                spread, default_price
            )
        return default_price

    def _calculate_bagel_price_with_modifiers(
        self,
        base_price: float,
        sandwich_protein: str | None,
        extras: list[str] | None,
        spread: str | None,
        spread_type: str | None = None,
    ) -> float:
        """
        Calculate total bagel price including modifiers.

        Args:
            base_price: Base bagel price
            sandwich_protein: Primary protein (e.g., "ham")
            extras: Additional modifiers (e.g., ["egg", "american"])
            spread: Spread choice (e.g., "cream cheese")
            spread_type: Spread flavor/variant (e.g., "tofu", "scallion")

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
            total += self._lookup_spread_price(spread, spread_type)

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
            item.spread_type,
        )

        # Update the item's price
        item.unit_price = new_price

        logger.debug(
            "Recalculated bagel price: base=%.2f, protein=%s, extras=%s, spread=%s (%s) -> total=%.2f",
            base_price, item.sandwich_protein, item.extras, item.spread, item.spread_type, new_price
        )

        return new_price

    def _lookup_coffee_modifier_price(self, modifier_name: str, modifier_type: str = "syrup") -> float:
        """
        Look up price modifier for a coffee add-on (syrup, milk, size).

        Searches the attribute_options for matching modifier prices.
        """
        if not modifier_name:
            return 0.0

        modifier_lower = modifier_name.lower().strip()

        # Try to find in item_types attribute options
        if self.menu_data:
            item_types = self.menu_data.get("item_types", {})
            # item_types is a dict with type slugs as keys
            for type_slug, type_data in item_types.items():
                if not isinstance(type_data, dict):
                    continue
                attrs = type_data.get("attributes", [])
                for attr in attrs:
                    if not isinstance(attr, dict):
                        continue
                    attr_slug = attr.get("slug", "")
                    # Match by modifier type (syrup, milk, size)
                    if modifier_type in attr_slug or attr_slug == modifier_type:
                        options = attr.get("options", [])
                        for opt in options:
                            if not isinstance(opt, dict):
                                continue
                            opt_slug = opt.get("slug", "").lower()
                            opt_name = opt.get("display_name", "").lower()
                            if modifier_lower in opt_slug or modifier_lower in opt_name or opt_slug in modifier_lower:
                                price = opt.get("price_modifier", 0.0)
                                if price > 0:
                                    logger.debug(
                                        "Found coffee modifier price: %s = $%.2f (from %s)",
                                        modifier_name, price, attr_slug
                                    )
                                    return price

        # Default coffee modifier prices
        default_prices = {
            # Size upcharges (relative to small)
            "medium": 0.50,
            "large": 1.00,
            # Milk alternatives
            "oat": 0.50,
            "oat milk": 0.50,
            "almond": 0.50,
            "almond milk": 0.50,
            "soy": 0.50,
            "soy milk": 0.50,
            # Flavor syrups
            "vanilla": 0.65,
            "vanilla syrup": 0.65,
            "hazelnut": 0.65,
            "hazelnut syrup": 0.65,
            "caramel": 0.65,
            "caramel syrup": 0.65,
            "peppermint": 1.00,
            "peppermint syrup": 1.00,
        }

        return default_prices.get(modifier_lower, 0.0)

    def _calculate_coffee_price_with_modifiers(
        self,
        base_price: float,
        size: str | None,
        milk: str | None,
        flavor_syrup: str | None,
    ) -> float:
        """
        Calculate total coffee price including modifiers.

        Args:
            base_price: Base coffee price (usually for small size)
            size: Size selection (small, medium, large)
            milk: Milk choice (regular, oat, almond, soy)
            flavor_syrup: Flavor syrup (vanilla, hazelnut, etc.)

        Returns:
            Total price including all modifiers
        """
        total = base_price

        # Add size upcharge (small is base price, medium/large have upcharges)
        if size and size.lower() not in ("small", "s"):
            size_upcharge = self._lookup_coffee_modifier_price(size, "size")
            total += size_upcharge
            if size_upcharge > 0:
                logger.debug("Coffee size upcharge: %s = +$%.2f", size, size_upcharge)

        # Add milk alternative upcharge (regular milk is free)
        if milk and milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self._lookup_coffee_modifier_price(milk, "milk")
            total += milk_upcharge
            if milk_upcharge > 0:
                logger.debug("Coffee milk upcharge: %s = +$%.2f", milk, milk_upcharge)

        # Add flavor syrup upcharge
        if flavor_syrup:
            syrup_upcharge = self._lookup_coffee_modifier_price(flavor_syrup, "syrup")
            total += syrup_upcharge
            if syrup_upcharge > 0:
                logger.debug("Coffee syrup upcharge: %s = +$%.2f", flavor_syrup, syrup_upcharge)

        return total

    def recalculate_coffee_price(self, item: CoffeeItemTask) -> float:
        """
        Recalculate and update a coffee item's price based on its current modifiers.

        Args:
            item: The CoffeeItemTask to recalculate

        Returns:
            The new calculated price
        """
        # Get base price from drink type
        base_price = self._lookup_coffee_price(item.drink_type)
        total = base_price

        # Calculate and store individual upcharges
        # Size upcharge (small is base price)
        size_upcharge = 0.0
        if item.size and item.size.lower() not in ("small", "s"):
            size_upcharge = self._lookup_coffee_modifier_price(item.size, "size")
            total += size_upcharge
        item.size_upcharge = size_upcharge

        # Milk alternative upcharge (regular milk is free)
        milk_upcharge = 0.0
        if item.milk and item.milk.lower() not in ("regular", "whole", "2%", "skim", "none", "no milk"):
            milk_upcharge = self._lookup_coffee_modifier_price(item.milk, "milk")
            total += milk_upcharge
        item.milk_upcharge = milk_upcharge

        # Flavor syrup upcharge
        syrup_upcharge = 0.0
        if item.flavor_syrup:
            syrup_upcharge = self._lookup_coffee_modifier_price(item.flavor_syrup, "syrup")
            total += syrup_upcharge
        item.syrup_upcharge = syrup_upcharge

        # Update the item's price
        item.unit_price = total

        logger.info(
            "Recalculated coffee price: base=$%.2f + size=$%.2f + milk=$%.2f + syrup=$%.2f -> total=$%.2f",
            base_price, size_upcharge, milk_upcharge, syrup_upcharge, total
        )

        return total
