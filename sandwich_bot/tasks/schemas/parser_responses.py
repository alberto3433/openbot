"""
State-Specific Parser Response Schemas.

This module contains all Pydantic models used for parsing user input
in different states of the order flow. Each model constrains the possible
interpretations of user input for a specific context.
"""

import warnings
from typing import Literal, Union, Self
from pydantic import BaseModel, Field, model_validator


# =============================================================================
# Helper Types for Modifiers with Quantity
# =============================================================================

class QuantifiedModifier(BaseModel):
    """A modifier with quantity (sweeteners, syrups, extra shots, etc.).

    Generic type for any modifier that can have a quantity attached.
    Used for sweeteners, syrups, and other quantifiable beverage additions.

    Examples:
        QuantifiedModifier(slug="sugar", quantity=2)  # 2 sugars
        QuantifiedModifier(slug="vanilla", quantity=1)  # 1 vanilla syrup
    """
    slug: str
    quantity: int = 1


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

    This is the canonical representation for ALL item types, replacing the
    item-specific ParsedBagelEntry and ParsedCoffeeEntry classes.

    All item attributes are stored in the attribute_values dict, keyed by
    attribute slug from the database (e.g., "size", "temperature", "bread").

    Examples:
        # Bagel
        ParsedItemEntry(
            item_type="bagel",
            attribute_values={"bread": "everything", "toasted": True, "spread_type": "scallion"},
            modifiers=["bacon", "egg"],
        )

        # Coffee
        ParsedItemEntry(
            item_type="sized_beverage",
            item_name="Latte",
            attribute_values={"size": "large", "temperature": "iced", "milk": "oat"},
            syrups=[QuantifiedModifier(slug="vanilla", quantity=1)],
        )
    """
    type: Literal["item"] = "item"

    # Item identification
    item_type: str  # "bagel", "sized_beverage", "espresso", "spread_sandwich", etc.
    item_name: str | None = None  # Specific menu item name if known (e.g., "Latte", "Cappuccino")
    quantity: int = 1

    # Data-driven attribute values (keyed by attribute slug)
    # Keys match attribute slugs in the database: "bread", "size", "temperature", "milk", etc.
    attribute_values: dict = Field(default_factory=dict)

    # Modifiers (ingredients to add - proteins, cheeses, toppings, spreads, etc.)
    modifiers: list[str] = Field(default_factory=list)

    # Structured modifiers for beverages (need quantity info)
    sweeteners: list[QuantifiedModifier] = Field(default_factory=list)
    syrups: list[QuantifiedModifier] = Field(default_factory=list)

    # Special instructions text
    special_instructions: str | None = None

    # Original text (for context preservation in disambiguation)
    original_text: str | None = None

    # For signature/speed menu items
    is_signature: bool = False

    # For by-pound items (e.g., "1/4 lb", "1 lb")
    weight_unit: str | None = None

    # Flags that may require clarification
    needs_cheese_clarification: bool = False
    wants_syrup: bool = False  # User said "syrup" without specifying flavor

    # Bread type property (aligned with DB attribute slug)
    @property
    def bread(self) -> str | None:
        """Get bread type from attribute_values."""
        return self.attribute_values.get("bread")

    @property
    def toasted(self) -> bool | None:
        """Get toasted from attribute_values."""
        return self.attribute_values.get("toasted")

    @property
    def scooped(self) -> bool | None:
        """Get scooped from attribute_values."""
        return self.attribute_values.get("scooped")

    @property
    def spread(self) -> str | None:
        """Get spread from attribute_values."""
        return self.attribute_values.get("spread")

    @property
    def spread_type(self) -> str | None:
        """Get spread_type from attribute_values."""
        return self.attribute_values.get("spread_type")

    @property
    def drink_type(self) -> str | None:
        """Get drink type (item_name for beverages)."""
        return self.item_name

    @property
    def size(self) -> str | None:
        """Get size from attribute_values."""
        return self.attribute_values.get("size")

    @property
    def temperature(self) -> str | None:
        """Get temperature from attribute_values."""
        return self.attribute_values.get("temperature")

    @property
    def iced(self) -> bool | None:
        """Backward-compatible property that derives bool from temperature."""
        temp = self.attribute_values.get("temperature")
        if temp is None:
            return None
        return temp == "iced"

    @property
    def milk(self) -> str | None:
        """Get milk from attribute_values."""
        return self.attribute_values.get("milk")

    @property
    def decaf(self) -> bool | None:
        """Get decaf from attribute_values."""
        return self.attribute_values.get("decaf")

    @property
    def cream_level(self) -> str | None:
        """Get cream_level from attribute_values."""
        return self.attribute_values.get("cream_level")

    @property
    def extra_shots(self) -> int:
        """Get extra_shots from attribute_values."""
        return self.attribute_values.get("extra_shots", 0)

    # Backward-compatible properties for bagel ingredient categorization.
    # In ParsedItemEntry, all ingredients are combined in modifiers list.
    # These return empty lists since categorization is not preserved.
    # The handler add_bagel() will recategorize modifiers if needed.
    @property
    def proteins(self) -> list[str]:
        """Return empty list - proteins are in modifiers list."""
        return []

    @property
    def cheeses(self) -> list[str]:
        """Return empty list - cheeses are in modifiers list."""
        return []

    @property
    def toppings(self) -> list[str]:
        """Return empty list - toppings are in modifiers list."""
        return []

    @classmethod
    def from_bagel_entry(cls, entry: "ParsedBagelEntry") -> "ParsedItemEntry":
        """Convert a ParsedBagelEntry to ParsedItemEntry."""
        attr_values = {}
        if entry.bread:
            attr_values["bread"] = entry.bread
        if entry.toasted is not None:
            attr_values["toasted"] = entry.toasted
        if entry.scooped is not None:
            attr_values["scooped"] = entry.scooped
        if entry.spread:
            attr_values["spread_type"] = entry.spread
        if entry.spread_type:
            attr_values["spread_type"] = entry.spread_type

        # Combine all modifier lists
        modifiers = []
        modifiers.extend(entry.proteins)
        modifiers.extend(entry.cheeses)
        modifiers.extend(entry.toppings)
        modifiers.extend(entry.modifiers)

        return cls(
            item_type="bagel",
            quantity=entry.quantity,
            attribute_values=attr_values,
            modifiers=modifiers,
            special_instructions=entry.special_instructions,
            needs_cheese_clarification=entry.needs_cheese_clarification,
        )

    @classmethod
    def from_coffee_entry(cls, entry: "ParsedCoffeeEntry") -> "ParsedItemEntry":
        """Convert a ParsedCoffeeEntry to ParsedItemEntry."""
        attr_values = {}
        if entry.size:
            attr_values["size"] = entry.size
        if entry.temperature:
            attr_values["temperature"] = entry.temperature
        if entry.milk:
            attr_values["milk"] = entry.milk
        if entry.decaf is not None:
            attr_values["decaf"] = entry.decaf
        if entry.cream_level:
            attr_values["cream_level"] = entry.cream_level
        if entry.extra_shots:
            attr_values["extra_shots"] = entry.extra_shots

        # Convert sweeteners and syrups
        sweeteners = [QuantifiedModifier(slug=s.slug, quantity=s.quantity) for s in entry.sweeteners]
        syrups = [QuantifiedModifier(slug=s.slug, quantity=s.quantity) for s in entry.syrups]

        return cls(
            item_type="sized_beverage",
            item_name=entry.drink_type,
            quantity=entry.quantity,
            attribute_values=attr_values,
            modifiers=list(entry.modifiers),
            sweeteners=sweeteners,
            syrups=syrups,
            special_instructions=entry.special_instructions,
            original_text=entry.original_text,
            wants_syrup=entry.wants_syrup,
        )


class ParsedMenuItemEntry(BaseModel):
    """A parsed menu item from multi-item detection.

    This handles both regular menu items and signature items (is_signature=True).
    Signature items are pre-configured items like 'The Classic BEC', 'The Leo', etc.
    """
    type: Literal["menu_item"] = "menu_item"
    menu_item_name: str
    quantity: int = 1
    bread: str | None = None
    toasted: bool | None = None
    modifiers: list[str] = Field(default_factory=list)
    is_signature: bool = False  # True for signature items like "The Classic BEC"


class ParsedBagelEntry(BaseModel):
    """DEPRECATED: Use ParsedItemEntry instead.

    A parsed bagel from multi-item detection. This class is maintained for
    backward compatibility. New code should use ParsedItemEntry with
    item_type="bagel" and store attributes in attribute_values dict.
    """

    @model_validator(mode="after")
    def emit_deprecation_warning(self) -> Self:
        """Emit deprecation warning when this class is instantiated."""
        warnings.warn(
            "ParsedBagelEntry is deprecated. Use ParsedItemEntry with item_type='bagel' instead.",
            DeprecationWarning,
            stacklevel=4,
        )
        return self

    type: Literal["bagel"] = "bagel"
    bread: str | None = None  # May be None if user just said "bagel" without type
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
    """DEPRECATED: Use ParsedItemEntry instead.

    A parsed coffee from multi-item detection. This class is maintained for
    backward compatibility. New code should use ParsedItemEntry with
    item_type="sized_beverage" and store attributes in attribute_values dict.
    """

    @model_validator(mode="after")
    def emit_deprecation_warning(self) -> Self:
        """Emit deprecation warning when this class is instantiated."""
        warnings.warn(
            "ParsedCoffeeEntry is deprecated. Use ParsedItemEntry with item_type='sized_beverage' instead.",
            DeprecationWarning,
            stacklevel=4,
        )
        return self

    type: Literal["coffee"] = "coffee"
    drink_type: str
    size: str | None = None
    temperature: str | None = None  # "iced" or "hot"
    milk: str | None = None
    quantity: int = 1
    special_instructions: str | None = None

    @property
    def iced(self) -> bool | None:
        """Backward-compatible property that derives bool from temperature."""
        if self.temperature is None:
            return None
        return self.temperature == "iced"

    # Decaf preference
    decaf: bool | None = None

    # Cream level preference (dark = less cream, light = more cream)
    cream_level: str | None = None

    # Sweeteners - supports multiple (e.g., "2 sugars and 1 splenda")
    sweeteners: list[QuantifiedModifier] = Field(default_factory=list)

    # Flavor syrups - supports multiple (e.g., "vanilla and caramel")
    syrups: list[QuantifiedModifier] = Field(default_factory=list)

    # Flag for when user says "syrup" without specifying flavor
    wants_syrup: bool = False

    # Extra espresso shots (1 = double, 2 = triple)
    extra_shots: int = 0

    # Original text that was parsed (for required_match_phrases filtering)
    # Preserves "boxed coffee" when drink_type is extracted as "coffee"
    original_text: str | None = None

    # Legacy modifiers list (for backwards compatibility during migration)
    modifiers: list[str] = Field(default_factory=list)




# Legacy aliases for backwards compatibility (deprecated - use ParsedMenuItemEntry with is_signature=True)
# These are kept temporarily for any code still referencing them
ParsedSignatureItemEntry = ParsedMenuItemEntry
ParsedSpeedMenuBagelEntry = ParsedMenuItemEntry


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
# Note: ParsedItemEntry is the new unified type. ParsedBagelEntry and ParsedCoffeeEntry
# are deprecated but still supported for backward compatibility.
ParsedItem = Union[
    ParsedItemEntry,
    ParsedMenuItemEntry,
    ParsedBagelEntry,
    ParsedCoffeeEntry,
    ParsedSideItemEntry,
    ParsedByPoundEntry,
]


class SideChoiceResponse(BaseModel):
    """Parser output when waiting for omelette side choice."""
    choice: Literal["bagel", "fruit_salad", "unclear"] = Field(
        description="What side the user chose: 'bagel', 'fruit_salad', or 'unclear' if not understood"
    )
    bread: str | None = Field(
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
    bread: str | None = Field(
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

    All item data is stored in the `parsed_items` field as a list of ParsedItemEntry,
    ParsedMenuItemEntry, ParsedSideItemEntry, or ParsedByPoundEntry objects.

    DEPRECATED FIELDS (kept for parser compatibility, will be removed after parser cleanup):
    - new_bagel, new_bagel_* fields
    - new_coffee, new_coffee_* fields
    - new_signature_item, new_signature_item_* fields
    - new_menu_item, new_menu_item_* fields
    - new_side_item, new_side_item_* fields
    - bagel_details, coffee_details
    - additional_menu_items
    """

    # ============ DEPRECATED BOOLEAN FLAGS - DO NOT USE IN NEW CODE ============
    # These are kept for backward compatibility with parser code that still sets them.
    # All handlers should read from parsed_items instead.

    # Bagel fields (DEPRECATED)
    new_bagel: bool = Field(default=False, description="DEPRECATED: Use parsed_items")
    new_bagel_quantity: int = Field(default=1, description="DEPRECATED: Use parsed_items")
    new_bagel_type: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_toasted: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_scooped: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_spread: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_spread_type: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_proteins: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_cheeses: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_toppings: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_spreads: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_special_instructions: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_bagel_needs_cheese_clarification: bool = Field(default=False, description="DEPRECATED: Use parsed_items")
    bagel_details: list[BagelOrderDetails] = Field(default_factory=list, description="DEPRECATED: Use parsed_items")

    # Coffee fields (DEPRECATED)
    new_coffee: bool = Field(default=False, description="DEPRECATED: Use parsed_items")
    new_coffee_type: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_size: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_iced: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_decaf: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_milk: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_cream_level: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_sweetener: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_sweetener_quantity: int | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_flavor_syrup: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_syrup_quantity: int | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_special_instructions: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_coffee_quantity: int = Field(default=1, description="DEPRECATED: Use parsed_items")
    coffee_details: list[CoffeeOrderDetails] = Field(default_factory=list, description="DEPRECATED: Use parsed_items")

    # Signature item fields (DEPRECATED)
    new_signature_item: bool = Field(default=False, description="DEPRECATED: Use parsed_items")
    new_signature_item_name: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_signature_item_quantity: int = Field(default=1, description="DEPRECATED: Use parsed_items")
    new_signature_item_toasted: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_signature_item_bagel_choice: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_signature_item_modifications: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")

    # Menu item fields (DEPRECATED)
    new_menu_item: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_menu_item_quantity: int = Field(default=1, description="DEPRECATED: Use parsed_items")
    new_menu_item_toasted: bool | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_menu_item_bagel_choice: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_menu_item_modifications: list[str] | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    additional_menu_items: list[MenuItemOrderDetails] = Field(default_factory=list, description="DEPRECATED: Use parsed_items")

    # Side item fields (DEPRECATED)
    new_side_item: str | None = Field(default=None, description="DEPRECATED: Use parsed_items")
    new_side_item_quantity: int = Field(default=1, description="DEPRECATED: Use parsed_items")

    # ============ END DEPRECATED FIELDS ============

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

    @model_validator(mode='after')
    def sync_deprecated_fields_and_parsed_items(self) -> Self:
        """Bidirectional sync between deprecated fields and parsed_items.

        This ensures backward compatibility in both directions:
        1. If parsed_items is populated → populate deprecated fields (for tests checking deprecated fields)
        2. If deprecated fields are set but parsed_items is empty → populate parsed_items (for handler code)

        This is a Phase 4 migration helper - deprecated fields will be removed eventually.
        """
        # Direction 2: If deprecated fields are set but parsed_items is empty, create parsed_items
        if not self.parsed_items:
            items_to_add = []

            # Create bagel entry from deprecated fields
            if self.new_bagel:
                attr_values = {}
                if self.new_bagel_type:
                    attr_values["bread"] = self.new_bagel_type
                if self.new_bagel_toasted is not None:
                    attr_values["toasted"] = self.new_bagel_toasted
                if self.new_bagel_scooped is not None:
                    attr_values["scooped"] = self.new_bagel_scooped
                if self.new_bagel_spread:
                    attr_values["spread"] = self.new_bagel_spread
                if self.new_bagel_spread_type:
                    attr_values["spread_type"] = self.new_bagel_spread_type

                modifiers = []
                if self.new_bagel_proteins:
                    modifiers.extend(self.new_bagel_proteins)
                if self.new_bagel_cheeses:
                    modifiers.extend(self.new_bagel_cheeses)
                if self.new_bagel_toppings:
                    modifiers.extend(self.new_bagel_toppings)

                for _ in range(self.new_bagel_quantity):
                    items_to_add.append(ParsedItemEntry(
                        item_type="bagel",
                        quantity=1,
                        attribute_values=attr_values.copy(),
                        modifiers=modifiers.copy(),
                        needs_cheese_clarification=self.new_bagel_needs_cheese_clarification,
                    ))

            # Create coffee entry from deprecated fields
            if self.new_coffee:
                attr_values = {}
                if self.new_coffee_size:
                    attr_values["size"] = self.new_coffee_size
                if self.new_coffee_iced is not None:
                    attr_values["temperature"] = "iced" if self.new_coffee_iced else "hot"
                if self.new_coffee_decaf is not None:
                    attr_values["decaf"] = self.new_coffee_decaf
                if self.new_coffee_milk:
                    attr_values["milk"] = self.new_coffee_milk
                if self.new_coffee_cream_level:
                    attr_values["cream_level"] = self.new_coffee_cream_level

                sweeteners = []
                if self.new_coffee_sweetener:
                    sweeteners.append(QuantifiedModifier(
                        type=self.new_coffee_sweetener,
                        quantity=self.new_coffee_sweetener_quantity or 1
                    ))

                syrups = []
                if self.new_coffee_flavor_syrup:
                    syrups.append(QuantifiedModifier(
                        type=self.new_coffee_flavor_syrup,
                        quantity=self.new_coffee_syrup_quantity or 1
                    ))

                for _ in range(self.new_coffee_quantity):
                    items_to_add.append(ParsedItemEntry(
                        item_type="sized_beverage",
                        item_name=self.new_coffee_type,
                        quantity=1,
                        attribute_values=attr_values.copy(),
                        sweeteners=sweeteners.copy(),
                        syrups=syrups.copy(),
                        special_instructions=self.new_coffee_special_instructions,
                    ))

            # Create signature item entry from deprecated fields
            if self.new_signature_item:
                attr_values = {}
                if self.new_signature_item_bagel_choice:
                    attr_values["bread"] = self.new_signature_item_bagel_choice
                if self.new_signature_item_toasted is not None:
                    attr_values["toasted"] = self.new_signature_item_toasted
                for _ in range(self.new_signature_item_quantity):
                    items_to_add.append(ParsedItemEntry(
                        item_type="menu_item",
                        item_name=self.new_signature_item_name,
                        quantity=1,
                        attribute_values=attr_values.copy(),
                        modifiers=self.new_signature_item_modifications or [],
                        is_signature=True,
                    ))

            # Create menu item entry from deprecated fields
            if self.new_menu_item:
                attr_values = {}
                if self.new_menu_item_bagel_choice:
                    attr_values["bread"] = self.new_menu_item_bagel_choice
                if self.new_menu_item_toasted is not None:
                    attr_values["toasted"] = self.new_menu_item_toasted
                for _ in range(self.new_menu_item_quantity):
                    items_to_add.append(ParsedItemEntry(
                        item_type="menu_item",
                        item_name=self.new_menu_item,
                        quantity=1,
                        attribute_values=attr_values.copy(),
                        modifiers=self.new_menu_item_modifications or [],
                    ))

            # Create side item entry from deprecated fields
            if self.new_side_item:
                for _ in range(self.new_side_item_quantity):
                    items_to_add.append(ParsedItemEntry(
                        item_type="side",
                        item_name=self.new_side_item,
                        quantity=1,
                    ))

            self.parsed_items = items_to_add
            return self

        # Direction 1: If parsed_items is populated, populate deprecated fields

        # Find first bagel
        bagels = [p for p in self.parsed_items if getattr(p, 'item_type', None) == 'bagel']
        if bagels:
            first_bagel = bagels[0]
            self.new_bagel = True
            self.new_bagel_quantity = len(bagels)
            self.new_bagel_type = first_bagel.bread
            self.new_bagel_toasted = first_bagel.toasted
            self.new_bagel_scooped = first_bagel.scooped
            self.new_bagel_spread = first_bagel.spread
            self.new_bagel_spread_type = first_bagel.spread_type
            # Check for needs_cheese_clarification
            if hasattr(first_bagel, 'needs_cheese_clarification'):
                self.new_bagel_needs_cheese_clarification = first_bagel.needs_cheese_clarification
            # Extract proteins from modifiers if present
            # In ParsedItemEntry, all ingredients are combined in modifiers list
            # For backwards compatibility, set new_bagel_proteins to the modifiers list
            if first_bagel.modifiers:
                self.new_bagel_proteins = list(first_bagel.modifiers)

        # Find first coffee/sized_beverage
        coffees = [p for p in self.parsed_items if getattr(p, 'item_type', None) == 'sized_beverage']
        if coffees:
            first_coffee = coffees[0]
            self.new_coffee = True
            self.new_coffee_quantity = len(coffees)
            self.new_coffee_type = first_coffee.drink_type or first_coffee.item_name
            self.new_coffee_size = first_coffee.size
            # Handle temperature -> iced conversion
            if first_coffee.temperature:
                self.new_coffee_iced = first_coffee.temperature == "iced"
            else:
                self.new_coffee_iced = first_coffee.iced
            self.new_coffee_decaf = first_coffee.decaf
            self.new_coffee_milk = first_coffee.milk
            # Handle sweeteners
            if first_coffee.sweeteners:
                self.new_coffee_sweetener = first_coffee.sweeteners[0].slug
                self.new_coffee_sweetener_quantity = first_coffee.sweeteners[0].quantity
            # Handle syrups
            if first_coffee.syrups:
                self.new_coffee_flavor_syrup = first_coffee.syrups[0].slug
                self.new_coffee_syrup_quantity = first_coffee.syrups[0].quantity
            if first_coffee.special_instructions:
                self.new_coffee_special_instructions = first_coffee.special_instructions

        # Find first signature item (identified by is_signature=True or item_type='signature_item')
        signature_items = [p for p in self.parsed_items
                          if getattr(p, 'is_signature', False) or getattr(p, 'item_type', None) == 'signature_item']
        if signature_items:
            first_sig = signature_items[0]
            self.new_signature_item = True
            self.new_signature_item_quantity = len(signature_items)
            self.new_signature_item_name = getattr(first_sig, 'menu_item_name', None) or getattr(first_sig, 'item_name', None)
            self.new_signature_item_toasted = first_sig.toasted
            self.new_signature_item_bagel_choice = first_sig.bread
            if first_sig.modifiers:
                self.new_signature_item_modifications = first_sig.modifiers

        # Find first menu item (not bagel, not signature, not coffee)
        # ParsedMenuItemEntry uses type='menu_item', ParsedItemEntry uses item_type
        menu_items = [p for p in self.parsed_items
                      if getattr(p, 'type', None) == 'menu_item'  # ParsedMenuItemEntry
                      or getattr(p, 'item_type', None) in ('menu_item', 'spread_sandwich', 'side')
                      or (getattr(p, 'type', None) == 'item' and getattr(p, 'item_type', None) not in ('bagel', 'sized_beverage', 'signature_item'))]
        # Exclude signature items from menu items
        menu_items = [m for m in menu_items if not getattr(m, 'is_signature', False)]
        if menu_items:
            first_menu = menu_items[0]
            # Check if it's actually a menu item type
            if getattr(first_menu, 'item_type', None) not in ('bagel', 'sized_beverage', 'signature_item', 'side'):
                self.new_menu_item = getattr(first_menu, 'menu_item_name', None) or getattr(first_menu, 'item_name', None)
                self.new_menu_item_quantity = len([m for m in menu_items if getattr(m, 'item_type', None) == getattr(first_menu, 'item_type', None)])
                self.new_menu_item_toasted = first_menu.toasted
                self.new_menu_item_bagel_choice = first_menu.bread
                if first_menu.modifiers:
                    self.new_menu_item_modifications = first_menu.modifiers

        # Find side items
        # Check both 'item_type' (ParsedItemEntry) and 'type' (ParsedSideItemEntry) attributes
        side_items = [
            p for p in self.parsed_items
            if getattr(p, 'item_type', None) == 'side' or getattr(p, 'type', None) == 'side'
        ]
        if side_items:
            first_side = side_items[0]
            # Check side_name (ParsedSideItemEntry), item_name (ParsedItemEntry), or menu_item_name
            self.new_side_item = (
                getattr(first_side, 'side_name', None)
                or getattr(first_side, 'item_name', None)
                or getattr(first_side, 'menu_item_name', None)
            )
            self.new_side_item_quantity = len(side_items)

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
