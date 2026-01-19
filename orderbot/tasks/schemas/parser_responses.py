"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

import warnings
from typing import Literal, Union
from pydantic import BaseModel, Field


# =============================================================================
# Helper Types for Modifiers with Quantity
# =============================================================================

class QuantifiedModifier(BaseModel):
    """A modifier with quantity and category.

    Generic type for any modifier that can have a quantity attached.
    Category is determined by the parser from database lookup.

    Examples:
        QuantifiedModifier(slug="sugar", quantity=2, category="sweetener")
        QuantifiedModifier(slug="vanilla", quantity=1, category="syrup")
        QuantifiedModifier(slug="bacon", quantity=1, category="protein")
    """
    slug: str
    quantity: int = 1
    category: str | None = None  # e.g., "sweetener", "syrup", "protein", "topping"


class QualifierConflict(BaseModel):
    """A conflict between two qualifiers for the same modifier."""
    modifier: str  # The modifier with conflicting qualifiers (e.g., "mayo")
    qualifier1: str  # First qualifier (e.g., "light")
    qualifier2: str  # Second qualifier (e.g., "extra")


# =============================================================================
# Token Type for Smart Tokenization
# =============================================================================

class Token(BaseModel):
    """Token for smart multi-item order tokenization.

    Used to classify parts of user input during multi-item parsing.
    Each token represents a segment of the input with its classification.

    Token Types:
        - item: Contains an item trigger or matches a menu item
        - modifier: Known ingredient/modifier (cream cheese, bacon, lox)
        - attribute: Known attribute option (large, medium, hot, iced)
        - quantity: Number or quantity word (a, an, 2, three)
        - separator: "and", ","
        - unknown: Unclassified text

    Examples:
        Token(original="large iced latte", token_type="item",
              resolved_name="Latte", item_type="sized_beverage", quantity=1)

        Token(original="cream cheese", token_type="modifier",
              resolved_name="Cream Cheese")

        Token(original="a", token_type="quantity", quantity=1)
    """
    original: str  # Original text of this token
    token_type: Literal["item", "modifier", "attribute", "quantity", "separator", "unknown"]

    # Extracted quantity (from "a", "2", "three", etc.)
    quantity: int | None = None

    # Resolved menu item or modifier name
    resolved_name: str | None = None

    # Detected item type (for item tokens)
    item_type: str | None = None

    # For attribute tokens, the attribute slug
    attribute_slug: str | None = None


# =============================================================================
# ParsedItem Types for Multi-Item Order Handling
# =============================================================================

class ParsedItemEntry(BaseModel):
    """Unified parsed item entry for data-driven item handling.

    This is the canonical representation for ALL item types.
    All attributes are stored in attribute_values dict (keyed by attribute slug).
    All modifiers are stored in modifiers list with category and quantity.

    Attribute access: Use attribute_values.get("slug") directly.
    Modifier access: Use get_modifiers_by_category("category") helper.
    """
    type: Literal["item"] = "item"

    # Item identification
    item_type: str
    item_name: str | None = None  # Specific menu item name if known
    quantity: int = 1

    # Data-driven attribute values (keyed by attribute slug from database)
    attribute_values: dict = Field(default_factory=dict)

    # Unified modifiers list with category and quantity
    # Category is determined by parser from DB lookup
    modifiers: list[QuantifiedModifier] = Field(default_factory=list)

    # Special instructions text
    special_instructions: str | None = None

    # Original text (for context preservation in disambiguation)
    original_text: str | None = None

    # For signature/speed menu items
    is_signature: bool = False

    # For by-pound items (e.g., "1/4 lb", "1 lb")
    weight_unit: str | None = None

    def get_modifiers_by_category(self, category: str) -> list[QuantifiedModifier]:
        """Get all modifiers matching a category."""
        return [m for m in self.modifiers if m.category == category]

    def add_modifier(
        self, slug: str, category: str | None = None, quantity: int = 1
    ) -> None:
        """Add a modifier to the list."""
        self.modifiers.append(
            QuantifiedModifier(slug=slug, category=category, quantity=quantity)
        )

# ParsedItem is the unified type for all parsed items.
ParsedItem = ParsedItemEntry


class AttributeChoiceResponse(BaseModel):
    """Generic parser output for any attribute selection.

    Used for all single-attribute responses (bread type, size, temperature, etc.).
    The attribute_slug identifies which attribute this response is for.
    """
    attribute_slug: str = Field(
        default="",
        description="The attribute slug being answered (e.g., 'bread', 'size', 'temperature')"
    )
    value: str | bool | None = Field(
        default=None,
        description="The value chosen for this attribute"
    )
    quantity: int = Field(
        default=1,
        description="How many items this applies to (e.g., '2 of them plain' -> 2)"
    )
    declined: bool = Field(
        default=False,
        description="User explicitly doesn't want this attribute (e.g., 'no spread')"
    )
    unclear: bool = Field(
        default=False,
        description="Set to true if the value couldn't be determined"
    )
    special_instructions: str | None = Field(
        default=None,
        description="Special instructions (e.g., 'light', 'extra', 'on the side')"
    )
    wants_cancel: bool = Field(
        default=False,
        description="User wants to cancel this item or the order"
    )
    # For compound attributes (deprecated - all attributes are now atomic)
    sub_values: dict = Field(
        default_factory=dict,
        description="Additional sub-values (deprecated)"
    )

class MultiAttributeChoiceResponse(BaseModel):
    """Generic parser output for multiple items needing the same attribute.

    Used when asking about an attribute for multiple items at once.
    """
    attribute_slug: str = Field(
        description="The attribute slug being answered"
    )
    values: list = Field(
        default_factory=list,
        description="List of values in order for each item"
    )
    all_same_value: str | bool | None = Field(
        default=None,
        description="If all items have the same value, put it here"
    )
    unclear: bool = Field(
        default=False,
        description="Set to true if values couldn't be determined"
    )


class OpenInputResponse(BaseModel):
    """Parser output when open for new items (not configuring a specific item).

    All item data is stored in the `parsed_items` field as a list of ParsedItemEntry objects.
    """

    # Clarifications needed
    needs_category_clarification: str | None = Field(
        default=None,
        description="Category slug that needs clarification (e.g., 'soda' when user says 'I want a soda' without specifying type)"
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
    wants_more_menu_items: bool = Field(
        default=False,
        description="User is asking to see more items from a previous menu query (e.g., 'what other pastries?', 'what else?', 'more options')"
    )
    more_menu_category: str | None = Field(
        default=None,
        description="The category extracted from 'what other X' queries (e.g., 'signature sandwiches' from 'what other signature sandwiches do you have?'). Used to start a fresh query when no pagination context exists."
    )
    asking_signature_menu: bool = Field(
        default=False,
        description="User is asking about signature/speed menu items (e.g., 'what are your speed menu bagels?', 'what signature items do you have?')"
    )
    signature_menu_type: str | None = Field(
        default=None,
        description="The specific type of signature items being asked about: 'signature_items' or None for all signature items"
    )
    # Price inquiries
    asks_about_price: bool = Field(
        default=False,
        description="User is asking about prices (e.g., 'how much are bagels?', 'what's the price of a latte?')"
    )
    price_query_item: str | None = Field(
        default=None,
        description="Specific item user is asking about price for (e.g., 'sesame bagel', 'large latte')"
    )

    # Store info inquiries
    asks_store_hours: bool = Field(
        default=False,
        description="User is asking about store hours (e.g., 'what are your hours?', 'when do you close?')"
    )
    asks_store_location: bool = Field(
        default=False,
        description="User is asking about store location/address (e.g., 'where are you located?', 'what's your address?')"
    )
    asks_delivery_zone: bool = Field(
        default=False,
        description="User is asking if we deliver to a location (e.g., 'do you deliver to 10001?', 'do you deliver to Tribeca?')"
    )
    delivery_zone_query: str | None = Field(
        default=None,
        description="The location (zip code or neighborhood) the user is asking about delivery for"
    )

    # Customer service escalation
    wants_customer_service: bool = Field(
        default=False,
        description="User wants to speak to a manager, report an issue, or escalate a complaint (e.g., 'I want to speak to a manager', 'my order was wrong', 'I need a refund')"
    )

    # Recommendation questions (should NOT add to cart)
    asks_recommendation: bool = Field(
        default=False,
        description="User is asking for recommendations (e.g., 'what do you recommend?', 'what's popular?', 'what's your best bagel?')"
    )
    recommendation_category: str | None = Field(
        default=None,
        description="DEPRECATED: Use recommendation_match_type instead. Category of recommendation asked."
    )
    recommendation_match_type: str | None = Field(
        default=None,
        description="Type of recommendation match: 'general' (no specific category), 'menu_items' (matched specific items), 'item_type' (matched an item type)"
    )
    recommendation_menu_item_ids: list[int] | None = Field(
        default=None,
        description="List of menu item IDs that matched the recommendation search (when recommendation_match_type='menu_items')"
    )
    recommendation_item_type_slug: str | None = Field(
        default=None,
        description="Item type slug that matched the recommendation search (when recommendation_match_type='item_type')"
    )

    # Item description inquiries (should NOT add to cart)
    asks_item_description: bool = Field(
        default=False,
        description="User is asking what's on/in a specific item (e.g., 'what's on the health nut?', 'what comes on the BLT?', 'what's in the classic?')"
    )
    item_description_query: str | None = Field(
        default=None,
        description="The item name the user is asking about (e.g., 'health nut', 'BLT', 'classic')"
    )

    # Modifier/add-on inquiries (should NOT add to cart)
    asks_modifier_options: bool = Field(
        default=False,
        description="User is asking about available modifiers/add-ons (e.g., 'what can I add to coffee?', 'what sweeteners do you have?', 'what spreads go on bagels?')"
    )
    modifier_query_item: str | None = Field(
        default=None,
        description="The item type user is asking about modifiers for: 'coffee', 'tea', 'hot chocolate', 'bagel', 'sandwich', or None for general"
    )
    modifier_query_category: str | None = Field(
        default=None,
        description="Specific modifier category asked about: 'sweeteners', 'milks', 'syrups', 'spreads', 'toppings', 'proteins', 'cheeses', or None for all options"
    )

    # Ingredient-based menu search
    # When user types just an ingredient (e.g., "chicken"), show items containing it
    ingredient_search_query: str | None = Field(
        default=None,
        description="The ingredient user is searching for (e.g., 'chicken', 'bacon')"
    )
    ingredient_search_matches: list[dict] = Field(
        default_factory=list,
        description="Menu items that contain the searched ingredient by default"
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
    wants_repeat_order: bool = Field(
        default=False,
        description="User wants to repeat their previous order (e.g., 'same as last time', 'repeat my order', 'my usual')"
    )
    is_greeting: bool = Field(
        default=False,
        description="Just a greeting, no order content"
    )
    is_gratitude: bool = Field(
        default=False,
        description="Just a thank you, no order content"
    )
    is_help_request: bool = Field(
        default=False,
        description="User is asking for help or is confused"
    )
    unclear: bool = Field(
        default=False,
        description="Message couldn't be understood"
    )
    replace_last_item: bool = Field(
        default=False,
        description="User wants to replace/change the last item they ordered (e.g., 'make it a coke instead', 'change it to X', 'actually X instead', 'no, X instead')"
    )
    cancel_item: str | None = Field(
        default=None,
        description="User wants to cancel/remove an item (e.g., 'cancel the coke', 'remove the bagel', 'nevermind the coffee'). Contains the item description to remove."
    )
    duplicate_last_item: int = Field(
        default=0,
        description="User wants to add more of the last item (e.g., 'make it 2' -> 1, 'I'll take 3' -> 2). Value is how many MORE to add."
    )
    duplicate_new_item_type: str | None = Field(
        default=None,
        description="User wants another item of a specific type (e.g., 'another bagel' -> 'bagel', 'one more coffee' -> 'coffee'). Treat as new item and run config flow."
    )
    wants_duplicate_all: bool = Field(
        default=False,
        description="User wants to duplicate all items in the cart (e.g., 'all the items', 'everything again')."
    )

    # Order type preference (pickup/delivery mentioned upfront)
    order_type: Literal["pickup", "delivery"] | None = Field(
        default=None,
        description="If user mentions 'pickup order' or 'delivery order' upfront, capture that here"
    )

    # Modify existing item in cart (e.g., "can I have scallion cream cheese on the cinnamon raisin bagel")
    modify_existing_item: bool = Field(
        default=False,
        description="User wants to modify an existing item in the cart, not order a new item"
    )
    modify_target_description: str | None = Field(
        default=None,
        description="Description of the item to modify (e.g., 'cinnamon raisin bagel', 'plain bagel')"
    )
    modify_new_spread: str | None = Field(
        default=None,
        description="Atomic spread slug to apply (e.g., 'scallion_cream_cheese', 'butter')"
    )
    modify_add_modifiers: list[str] = Field(
        default_factory=list,
        description="Modifiers to add to existing item (e.g., ['bacon', 'cheese'] for 'add bacon and cheese'). May include qualifiers in parentheses: 'Mayo (extra)', 'Bacon (crispy, on the side)'"
    )
    modify_qualifier_conflicts: list[QualifierConflict] | None = Field(
        default=None,
        description="Conflicting qualifiers detected for modifiers. When present, handler should ask user for clarification."
    )

    # Multi-item order handling - list of parsed items for generic processing
    parsed_items: list[ParsedItem] = Field(
        default_factory=list,
        description="List of parsed items from multi-item order detection. Used for generic item processing in handler."
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
    asks_about_tax: bool = Field(
        default=False,
        description="User is asking about the total with tax (e.g., 'what's my total with tax?', 'how much with tax?')"
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
