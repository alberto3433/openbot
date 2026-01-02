"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

from typing import Literal, Union
from pydantic import BaseModel, Field


# =============================================================================
# ParsedItem Types for Multi-Item Order Handling
# =============================================================================

class ParsedMenuItemEntry(BaseModel):
    """A parsed menu item from multi-item detection."""
    type: Literal["menu_item"] = "menu_item"
    menu_item_name: str
    quantity: int = 1
    bagel_type: str | None = None
    toasted: bool | None = None
    modifiers: list[str] = Field(default_factory=list)


class ParsedBagelEntry(BaseModel):
    """A parsed bagel from multi-item detection."""
    type: Literal["bagel"] = "bagel"
    bagel_type: str
    quantity: int = 1
    toasted: bool | None = None
    modifiers: list[str] = Field(default_factory=list)


class ParsedCoffeeEntry(BaseModel):
    """A parsed coffee from multi-item detection."""
    type: Literal["coffee"] = "coffee"
    drink_type: str
    size: str | None = None
    temperature: str | None = None
    milk: str | None = None
    modifiers: list[str] = Field(default_factory=list)
    quantity: int = 1


class ParsedSpeedMenuBagelEntry(BaseModel):
    """A parsed speed menu bagel from multi-item detection."""
    type: Literal["speed_menu_bagel"] = "speed_menu_bagel"
    speed_menu_name: str
    bagel_type: str | None = None
    toasted: bool | None = None
    quantity: int = 1
    modifiers: list[str] = Field(default_factory=list)


class ParsedSideItemEntry(BaseModel):
    """A parsed side item from multi-item detection."""
    type: Literal["side"] = "side"
    side_name: str
    quantity: int = 1


# Union type for dispatcher
ParsedItem = Union[
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
    ParsedSpeedMenuBagelEntry,
    ParsedSideItemEntry,
]


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
    special_instructions: str | None = Field(
        default=None,
        description="Special instructions about quantity/application: 'a little', 'extra', 'light', 'on the side', etc."
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
        description="Coffee size: small or large"
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


class CoffeeOrderDetails(BaseModel):
    """Details for a single coffee/drink in an order."""
    drink_type: str = Field(description="Coffee/drink type (coffee, latte, cappuccino, etc.)")
    size: str | None = Field(default=None, description="Size: small or large")
    iced: bool | None = Field(default=None, description="True if iced, False if hot, None if not specified")
    decaf: bool | None = Field(default=None, description="True if decaf, False if regular, None if not specified")
    quantity: int = Field(default=1, description="Number of this drink")
    milk: str | None = Field(default=None, description="Milk type: whole, skim, oat, almond, none/black")
    special_instructions: str | None = Field(default=None, description="Special instructions like 'a splash of milk', 'extra hot'")


class MenuItemOrderDetails(BaseModel):
    """Details for a single menu item in a multi-item order."""
    name: str = Field(description="Menu item name (e.g., 'The BLT', 'The Lexington')")
    quantity: int = Field(default=1, description="Number of this item")
    bagel_choice: str | None = Field(default=None, description="Bagel type if specified")
    toasted: bool | None = Field(default=None, description="Whether toasted")
    modifications: list[str] = Field(default_factory=list, description="Modifications like 'no onions'")


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
    new_menu_item_toasted: bool | None = Field(
        default=None,
        description="Whether the menu item should be toasted (True if 'toasted' mentioned, None if not specified)"
    )
    new_menu_item_bagel_choice: str | None = Field(
        default=None,
        description="Bagel type for spread/salad sandwiches if specified (e.g., 'plain bagel with cream cheese' -> 'plain')"
    )
    new_menu_item_modifications: list[str] = Field(
        default_factory=list,
        description="Modifications for menu items (e.g., 'with mayo and mustard' -> ['mayo', 'mustard'], 'no onions' -> ['no onions'])"
    )
    # For multiple menu items in a single order (e.g., "A Lexington and a BLT")
    additional_menu_items: list[MenuItemOrderDetails] = Field(
        default_factory=list,
        description="Additional menu items when ordering multiple in one request. The first item uses new_menu_item fields."
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
    # Bagel modifiers for orders like "everything bagel with bacon and egg"
    new_bagel_proteins: list[str] = Field(
        default_factory=list,
        description="Proteins to add to the bagel (e.g., 'bacon', 'egg', 'ham')"
    )
    new_bagel_cheeses: list[str] = Field(
        default_factory=list,
        description="Cheeses to add to the bagel (e.g., 'american', 'swiss', 'cheddar')"
    )
    new_bagel_toppings: list[str] = Field(
        default_factory=list,
        description="Toppings to add to the bagel (e.g., 'tomato', 'onion', 'lettuce')"
    )
    new_bagel_spreads: list[str] = Field(
        default_factory=list,
        description="Spreads to add to the bagel (e.g., 'cream cheese', 'butter')"
    )
    new_bagel_special_instructions: list[str] = Field(
        default_factory=list,
        description="Special instructions (e.g., 'light cream cheese', 'extra bacon')"
    )
    new_bagel_needs_cheese_clarification: bool = Field(
        default=False,
        description="True if user said 'cheese' without specifying type (American, Swiss, etc.)"
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
        description="Coffee size if specified: small or large"
    )
    new_coffee_iced: bool | None = Field(
        default=None,
        description="True if user wants iced, False if hot, None if not specified"
    )
    new_coffee_decaf: bool | None = Field(
        default=None,
        description="True if user wants decaf, False if regular, None if not specified"
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
    new_coffee_syrup_quantity: int = Field(
        default=1,
        description="Number of syrup pumps (e.g., '2 hazelnut syrups' = 2, 'double vanilla' = 2)"
    )
    new_coffee_special_instructions: str | None = Field(
        default=None,
        description="Special instructions for the coffee like 'a splash of milk', 'extra hot', 'light ice'"
    )
    new_coffee_quantity: int = Field(
        default=1,
        description="Number of drinks ordered (e.g., '3 diet cokes' -> 3, 'two coffees' -> 2)"
    )
    # For multiple coffees with different types specified upfront
    coffee_details: list[CoffeeOrderDetails] = Field(
        default_factory=list,
        description="When ordering multiple different coffees, list each one separately"
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
    new_speed_menu_bagel_bagel_choice: str | None = Field(
        default=None,
        description="Custom bagel choice for speed menu item (e.g., 'wheat' for 'Classic BEC on a wheat bagel')"
    )
    new_speed_menu_bagel_modifications: list[str] = Field(
        default_factory=list,
        description="Modifications for speed menu bagels (e.g., 'with mayo' -> ['mayo'], 'no onions' -> ['no onions'])"
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
    wants_more_menu_items: bool = Field(
        default=False,
        description="User is asking to see more items from a previous menu query (e.g., 'what other pastries?', 'what else?', 'more options')"
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

    # Recommendation questions (should NOT add to cart)
    asks_recommendation: bool = Field(
        default=False,
        description="User is asking for recommendations (e.g., 'what do you recommend?', 'what's popular?', 'what's your best bagel?')"
    )
    recommendation_category: str | None = Field(
        default=None,
        description="Category of recommendation asked: 'bagel', 'sandwich', 'coffee', 'breakfast', 'lunch', or None for general"
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

    # Order type preference (pickup/delivery mentioned upfront)
    order_type: Literal["pickup", "delivery"] | None = Field(
        default=None,
        description="If user mentions 'pickup order' or 'delivery order' upfront, capture that here"
    )

    # Multi-item order handling - list of parsed items for generic processing
    parsed_items: list[ParsedItem] = Field(
        default_factory=list,
        description="List of parsed items from multi-item order detection. Used for generic item processing in handler."
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
