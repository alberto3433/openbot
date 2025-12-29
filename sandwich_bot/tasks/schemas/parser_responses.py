"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

from typing import Literal
from pydantic import BaseModel, Field


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
    notes: str | None = Field(
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


class CoffeeOrderDetails(BaseModel):
    """Details for a single coffee/drink in an order."""
    drink_type: str = Field(description="Coffee/drink type (coffee, latte, cappuccino, etc.)")
    size: str | None = Field(default=None, description="Size: small, medium, or large")
    iced: bool | None = Field(default=None, description="True if iced, False if hot, None if not specified")
    quantity: int = Field(default=1, description="Number of this drink")
    milk: str | None = Field(default=None, description="Milk type: whole, skim, oat, almond, none/black")
    notes: str | None = Field(default=None, description="Special instructions like 'a splash of milk', 'extra hot'")


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
    new_coffee_notes: str | None = Field(
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

    # Order type preference (pickup/delivery mentioned upfront)
    order_type: Literal["pickup", "delivery"] | None = Field(
        default=None,
        description="If user mentions 'pickup order' or 'delivery order' upfront, capture that here"
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
