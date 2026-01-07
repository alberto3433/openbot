"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

from typing import Literal, Union, Self
from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Helper Types for Coffee Modifiers
# =============================================================================

class SweetenerItem(BaseModel):
    """A sweetener with quantity for coffee orders."""
    type: str  # "sugar", "splenda", "stevia", "equal", etc.
    quantity: int = 1


class SyrupItem(BaseModel):
    """A flavor syrup with quantity for coffee orders."""
    type: str  # "vanilla", "caramel", "hazelnut", etc.
    quantity: int = 1


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
    """A parsed bagel from multi-item detection.

    This is the canonical representation for bagel orders, used by the
    parsed_items system for unified multi-item order handling.
    """
    type: Literal["bagel"] = "bagel"
    bagel_type: str | None = None  # May be None if user just said "bagel" without type
    quantity: int = 1
    toasted: bool | None = None
    scooped: bool | None = None  # True if bagel should be scooped out

    # Spread configuration
    spread: str | None = None  # "cream cheese", "butter", etc.
    spread_type: str | None = None  # "scallion", "veggie", "plain", etc.

    # Sandwich toppings
    proteins: list[str] = Field(default_factory=list)  # "bacon", "egg", "ham", "lox", etc.
    cheeses: list[str] = Field(default_factory=list)  # "american", "swiss", "cheddar", etc.
    toppings: list[str] = Field(default_factory=list)  # "tomato", "onion", "lettuce", etc.

    # Special instructions
    special_instructions: str | None = None

    # Flag for when user says "cheese" without specifying type
    needs_cheese_clarification: bool = False

    # Legacy modifiers list (for backwards compatibility during migration)
    modifiers: list[str] = Field(default_factory=list)


class ParsedCoffeeEntry(BaseModel):
    """A parsed coffee from multi-item detection.

    This is the canonical representation for coffee orders, used by the
    parsed_items system for unified multi-item order handling.
    """
    type: Literal["coffee"] = "coffee"
    drink_type: str
    size: str | None = None
    temperature: str | None = None  # "iced" or "hot"
    milk: str | None = None
    quantity: int = 1
    special_instructions: str | None = None

    # Decaf preference
    decaf: bool | None = None

    # Cream level preference (dark = less cream, light = more cream)
    cream_level: str | None = None

    # Sweeteners - supports multiple (e.g., "2 sugars and 1 splenda")
    sweeteners: list[SweetenerItem] = Field(default_factory=list)

    # Flavor syrups - supports multiple (e.g., "vanilla and caramel")
    syrups: list[SyrupItem] = Field(default_factory=list)

    # Flag for when user says "syrup" without specifying flavor
    wants_syrup: bool = False

    # Extra espresso shots (1 = double, 2 = triple)
    extra_shots: int = 0

    # Original text that was parsed (for required_match_phrases filtering)
    # Preserves "boxed coffee" when drink_type is extracted as "coffee"
    original_text: str | None = None

    # Legacy modifiers list (for backwards compatibility during migration)
    modifiers: list[str] = Field(default_factory=list)


class ParsedSignatureItemEntry(BaseModel):
    """A parsed signature item from multi-item detection."""
    type: Literal["signature_item"] = "signature_item"
    signature_item_name: str
    bagel_type: str | None = None
    toasted: bool | None = None
    quantity: int = 1
    modifiers: list[str] = Field(default_factory=list)


class ParsedSignatureItemEntry(BaseModel):
    """A parsed signature item from multi-item detection.

    Signature items are pre-configured items like 'The Classic BEC', 'The Leo', etc.
    """
    type: Literal["signature_item"] = "signature_item"
    signature_item_name: str  # The name of the signature item (e.g., "The Classic BEC")
    bagel_type: str | None = None  # Custom bagel choice (e.g., "wheat")
    toasted: bool | None = None
    quantity: int = 1
    modifiers: list[str] = Field(default_factory=list)


# Backwards compatibility alias
ParsedSpeedMenuBagelEntry = ParsedSignatureItemEntry


class ParsedSideItemEntry(BaseModel):
    """A parsed side item from multi-item detection."""
    type: Literal["side"] = "side"
    side_name: str
    quantity: int = 1


class ParsedByPoundEntry(BaseModel):
    """A parsed by-the-pound item from multi-item detection."""
    type: Literal["by_pound"] = "by_pound"
    item_name: str  # Canonical name (e.g., "Plain Cream Cheese", "Nova Scotia Salmon (Lox)")
    quantity: str  # e.g., "quarter lb", "half lb", "1 lb"
    category: str | None = None  # e.g., "spread", "fish", "cheese"


# Union type for dispatcher
ParsedItem = Union[
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
    ParsedSignatureItemEntry,
    ParsedSideItemEntry,
    ParsedByPoundEntry,
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
    toasted: bool | None = Field(
        default=None,
        description="If user specified toasted preference (e.g., 'plain bagel toasted' -> True, 'not toasted' -> False)"
    )
    spread: str | None = Field(
        default=None,
        description="If user specified spread (e.g., 'with cream cheese' -> 'cream cheese', 'with butter' -> 'butter')"
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
    """DEPRECATED: Use ParsedBagelEntry instead.

    Details for a single bagel in an order. This class is maintained for
    backward compatibility with the deprecated bagel_details field.
    """
    bagel_type: str | None = Field(default=None, description="Bagel type (plain, everything, cinnamon raisin, etc.)")
    toasted: bool | None = Field(default=None, description="Whether toasted")
    spread: str | None = Field(default=None, description="Spread (cream cheese, butter, etc.)")
    spread_type: str | None = Field(default=None, description="Spread variety (scallion, veggie, strawberry, etc.)")


class CoffeeOrderDetails(BaseModel):
    """DEPRECATED: Use ParsedCoffeeEntry instead.

    Details for a single coffee/drink in an order. This class is maintained for
    backward compatibility with the deprecated coffee_details field.
    """
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
    """Parser output when open for new items (not configuring a specific item).

    MIGRATION NOTE (Phase 10):
    The boolean flag fields (new_bagel, new_coffee, new_signature_item, new_menu_item,
    new_side_item and their associated fields) are DEPRECATED. Use the `parsed_items`
    field instead, which provides a unified list of ParsedBagelEntry, ParsedCoffeeEntry,
    ParsedSignatureItemEntry, ParsedMenuItemEntry, and ParsedSideItemEntry objects.

    The model_validator auto-populates parsed_items from boolean flags for backward
    compatibility, but new code should use parsed_items directly.
    """

    # DEPRECATED: Use parsed_items with ParsedMenuItemEntry instead.
    # These menu item fields are auto-converted to parsed_items by model_validator.
    new_menu_item: str | None = Field(
        default=None,
        description="DEPRECATED: Use parsed_items. Name of a menu item ordered"
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
    # DEPRECATED: Use parsed_items with ParsedSideItemEntry instead.
    # These side item fields are auto-converted to parsed_items by model_validator.
    new_side_item: str | None = Field(
        default=None,
        description="DEPRECATED: Use parsed_items. Side item ordered"
    )
    new_side_item_quantity: int = Field(
        default=1,
        description="DEPRECATED: Use parsed_items. Number of side items ordered"
    )
    # DEPRECATED: Use parsed_items with ParsedBagelEntry instead.
    # These bagel fields are auto-converted to parsed_items by model_validator.
    new_bagel: bool = Field(
        default=False,
        description="DEPRECATED: Use parsed_items. User wants to order a bagel"
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
    new_bagel_scooped: bool | None = Field(
        default=None,
        description="Whether the bagel should be scooped out (True if 'scooped' mentioned, None if not specified)"
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
    # DEPRECATED: Use parsed_items with ParsedBagelEntry objects instead.
    # This field is maintained for backward compatibility only.
    bagel_details: list[BagelOrderDetails] = Field(
        default_factory=list,
        description="DEPRECATED: Use parsed_items instead. When ordering multiple bagels with different configs, list each one separately"
    )
    # DEPRECATED: Use parsed_items with ParsedCoffeeEntry instead.
    # These coffee fields are auto-converted to parsed_items by model_validator.
    new_coffee: bool = Field(
        default=False,
        description="DEPRECATED: Use parsed_items. User wants to order coffee/drink"
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
    new_coffee_cream_level: str | None = Field(
        default=None,
        description="Cream level preference: dark (less cream), light (more cream), regular"
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
    # DEPRECATED: Use parsed_items with ParsedCoffeeEntry objects instead.
    # This field is maintained for backward compatibility only.
    coffee_details: list[CoffeeOrderDetails] = Field(
        default_factory=list,
        description="DEPRECATED: Use parsed_items instead. When ordering multiple different coffees, list each one separately"
    )

    # DEPRECATED: Use parsed_items with ParsedSignatureItemEntry instead.
    # Signature item orders (pre-configured sandwiches like "The Classic BEC", "The Leo")
    # These fields are auto-converted to parsed_items by model_validator.
    new_signature_item: bool = Field(
        default=False,
        description="DEPRECATED: Use parsed_items. User wants to order a signature item"
    )
    new_signature_item_name: str | None = Field(
        default=None,
        description="Name of the signature item (e.g., 'The Classic BEC', 'The Leo', 'The Max Zucker')"
    )
    new_signature_item_quantity: int = Field(
        default=1,
        description="Number of signature items ordered (e.g., '3 Classics' -> 3)"
    )
    new_signature_item_toasted: bool | None = Field(
        default=None,
        description="Whether the signature item should be toasted (True/False/None)"
    )
    new_signature_item_bagel_choice: str | None = Field(
        default=None,
        description="Custom bagel choice for signature item (e.g., 'wheat' for 'Classic BEC on a wheat bagel')"
    )
    new_signature_item_modifications: list[str] = Field(
        default_factory=list,
        description="Modifications for signature items (e.g., 'with mayo' -> ['mayo'], 'no onions' -> ['no onions'])"
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
        description="The specific type of signature items being asked about: 'signature_items' or None for all signature items"
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
        description="New spread to apply to the existing item (e.g., 'cream cheese', 'butter')"
    )
    modify_new_spread_type: str | None = Field(
        default=None,
        description="Type of spread (e.g., 'scallion', 'veggie', 'plain')"
    )

    # Multi-item order handling - list of parsed items for generic processing
    parsed_items: list[ParsedItem] = Field(
        default_factory=list,
        description="List of parsed items from multi-item order detection. Used for generic item processing in handler."
    )

    @model_validator(mode='after')
    def populate_parsed_items_from_boolean_flags(self) -> Self:
        """Auto-populate parsed_items from boolean flags for unified handler path.

        This validator ensures that even LLM responses that only use boolean flags
        (new_bagel, new_coffee, etc.) will have parsed_items populated so the
        unified _process_multi_item_order() path can handle all orders.

        Phase 9 migration: This enables removal of boolean flag handling code.
        """
        # Skip if parsed_items already populated (deterministic parser dual-write)
        if self.parsed_items:
            return self

        items: list[ParsedItem] = []

        # Add bagels from boolean flags
        if self.new_bagel:
            for _ in range(self.new_bagel_quantity):
                items.append(ParsedBagelEntry(
                    bagel_type=self.new_bagel_type,
                    quantity=1,  # Individual entries, quantity already expanded
                    toasted=self.new_bagel_toasted,
                    spread=self.new_bagel_spread,
                    spread_type=self.new_bagel_spread_type,
                    proteins=list(self.new_bagel_proteins) if self.new_bagel_proteins else [],
                    cheeses=list(self.new_bagel_cheeses) if self.new_bagel_cheeses else [],
                    toppings=list(self.new_bagel_toppings) if self.new_bagel_toppings else [],
                    needs_cheese_clarification=self.new_bagel_needs_cheese_clarification,
                    modifiers=list(self.new_bagel_special_instructions) if self.new_bagel_special_instructions else [],
                ))

        # Add coffee from boolean flags
        if self.new_coffee:
            # Build sweeteners list
            sweeteners = []
            if self.new_coffee_sweetener:
                sweeteners.append({
                    "type": self.new_coffee_sweetener,
                    "quantity": self.new_coffee_sweetener_quantity,
                })
            # Build syrups list
            syrups = []
            if self.new_coffee_flavor_syrup:
                syrups.append({
                    "type": self.new_coffee_flavor_syrup,
                    "quantity": self.new_coffee_syrup_quantity,
                })
            for _ in range(self.new_coffee_quantity):
                items.append(ParsedCoffeeEntry(
                    drink_type=self.new_coffee_type,  # Preserve None for generic drink requests
                    size=self.new_coffee_size,
                    temperature="iced" if self.new_coffee_iced else ("hot" if self.new_coffee_iced is False else None),
                    quantity=1,
                    milk=self.new_coffee_milk,
                    decaf=self.new_coffee_decaf,
                    special_instructions=self.new_coffee_special_instructions,
                    sweeteners=sweeteners.copy() if sweeteners else [],
                    syrups=syrups.copy() if syrups else [],
                ))

        # Add signature item from boolean flags
        if self.new_signature_item:
            for _ in range(self.new_signature_item_quantity):
                items.append(ParsedSignatureItemEntry(
                    signature_item_name=self.new_signature_item_name or "",
                    bagel_type=self.new_signature_item_bagel_choice,
                    toasted=self.new_signature_item_toasted,
                    quantity=1,
                    modifiers=list(self.new_signature_item_modifications) if self.new_signature_item_modifications else [],
                ))

        # Add menu item from boolean flags
        if self.new_menu_item:
            for _ in range(self.new_menu_item_quantity):
                items.append(ParsedMenuItemEntry(
                    menu_item_name=self.new_menu_item,
                    quantity=1,
                    bagel_type=self.new_menu_item_bagel_choice,
                    toasted=self.new_menu_item_toasted,
                    modifiers=list(self.new_menu_item_modifications) if self.new_menu_item_modifications else [],
                ))
            # Also add additional menu items if present
            for extra in self.additional_menu_items:
                for _ in range(extra.quantity):
                    items.append(ParsedMenuItemEntry(
                        menu_item_name=extra.name,
                        quantity=1,
                        bagel_type=extra.bagel_choice,
                        toasted=extra.toasted,
                        modifiers=list(extra.modifications) if extra.modifications else [],
                    ))

        # Add side item from boolean flags
        if self.new_side_item:
            for _ in range(self.new_side_item_quantity):
                items.append(ParsedSideItemEntry(
                    side_name=self.new_side_item,
                    quantity=1,
                ))

        self.parsed_items = items
        return self


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
