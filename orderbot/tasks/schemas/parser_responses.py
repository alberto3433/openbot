"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

from typing import Literal
from pydantic import BaseModel, Field


# =============================================================================
# Unified Selection Model
# =============================================================================

class Selection(BaseModel):
    """A single customization choice for a menu item.

    This is the canonical format for ALL item customizations - both attribute
    choices (bread, size, toasted) and modifier add-ons (bacon, syrup, milk).

    The format is uniform across all selection types:
    - Attribute selections: Selection(slug="plain", category="bread", ...)
    - Boolean attributes: Selection(slug="yes", category="toasted", ...)
    - Modifier add-ons: Selection(slug="bacon", category="protein", quantity=2, ...)

    Examples:
        Selection(slug="everything", category="bread", price=0, display_name="Everything")
        Selection(slug="yes", category="toasted", price=0, display_name="Toasted")
        Selection(slug="large", category="size", price=0.90, display_name="Large")
        Selection(slug="bacon", category="protein", quantity=2, price=1.50, display_name="Bacon")
        Selection(slug="vanilla", category="syrup", price=0.50, display_name="Vanilla")
    """
    slug: str  # Selected option identifier (e.g., "plain", "bacon", "large", "yes")
    category: str  # What type of selection (e.g., "bread", "protein", "size", "toasted")
    quantity: int = 1  # How many (default 1)
    price: float = 0.0  # Price contribution per unit
    display_name: str | None = None  # Human-readable name (populated from cache if not provided)


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
    All customizations (attributes and modifiers) are stored in a unified
    `selections` list using the Selection format.

    Access methods:
    - get_selection(category): Get first selection for a category
    - get_selections(category): Get all selections for a category
    - has_selection(category): Check if any selection exists for category
    - add_selection(...): Add a new selection
    """
    type: Literal["item"] = "item"

    # Item identification
    item_type: str
    item_name: str | None = None  # Specific menu item name if known
    quantity: int = 1

    # Unified selections list - all customizations (attributes and modifiers)
    selections: list[Selection] = Field(default_factory=list)

    # Original text (for context preservation in disambiguation)
    original_text: str | None = None

    # For signature/speed menu items
    is_signature: bool = False

    # For by-pound items (e.g., "1/4 lb", "1 lb")
    weight_unit: str | None = None

    # Track unavailable options user attempted to select
    # Map of attr_slug -> {attempted_slug, attempted_display}
    # Used to show helpful "We don't have X - we have Y or Z" messages
    unavailable_selections: dict[str, dict] = Field(default_factory=dict)

    # Track unmatched tokens user mentioned that don't match any option
    # Map of attr_slug -> {tokens: list[str]}
    # Used to show "We don't have X. We have A, B, C..." with pagination
    unmatched_selections: dict[str, dict] = Field(default_factory=dict)

    # Item-level special instructions (e.g., "room for cream", "extra hot")
    special_instructions: list[str] = Field(default_factory=list)

    def get_selection(self, category: str) -> Selection | None:
        """Get first selection for a category (for single-select attributes)."""
        for sel in self.selections:
            if sel.category == category:
                return sel
        return None

    def get_selections(self, category: str) -> list[Selection]:
        """Get all selections for a category (for multi-select)."""
        return [sel for sel in self.selections if sel.category == category]

    def get_selection_value(self, category: str) -> str | None:
        """Get the slug of the first selection for a category."""
        sel = self.get_selection(category)
        return sel.slug if sel else None

    def has_selection(self, category: str) -> bool:
        """Check if any selection exists for a category."""
        return any(sel.category == category for sel in self.selections)

    def add_selection(
        self,
        slug: str,
        category: str,
        quantity: int = 1,
        price: float = 0.0,
        display_name: str | None = None,
    ) -> None:
        """Add a selection to the list."""
        self.selections.append(
            Selection(
                slug=slug,
                category=category,
                quantity=quantity,
                price=price,
                display_name=display_name,
            )
        )

    @property
    def attribute_values(self) -> dict:
        """Convert selections to dict format for backward compatibility."""
        result = {}
        for sel in self.selections:
            if sel.slug in ("yes", "no"):
                result[sel.category] = sel.slug == "yes"
            else:
                if sel.category in result:
                    existing = result[sel.category]
                    if isinstance(existing, list):
                        existing.append(sel.slug)
                    else:
                        result[sel.category] = [existing, sel.slug]
                else:
                    result[sel.category] = sel.slug
        return result

    @property
    def modifiers(self) -> list[Selection]:
        """Return selections for backward compatibility."""
        return self.selections


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
    wants_cancel: bool = Field(
        default=False,
        description="User wants to cancel this item or the order"
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
    # Attribute inquiries (e.g., "what bagel types do you have?")
    asks_attribute_options: bool = Field(
        default=False,
        description="User is asking about attribute options (e.g., 'what bagel types?', 'what sizes?')"
    )
    attribute_query_item_type: str | None = Field(
        default=None,
        description="Item type slug for attribute query (e.g., 'bagel' from 'what bagel types?')"
    )
    attribute_query_signal: str | None = Field(
        default=None,
        description="Signal word for attribute query (e.g., 'type', 'size', 'flavor')"
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
    recommendation_search_term: str | None = Field(
        default=None,
        description="Original search term extracted from the user's query (e.g., 'bagel', 'coffee')"
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
