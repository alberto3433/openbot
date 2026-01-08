import logging
import os
import traceback

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    JSON,
    DateTime,
    ForeignKey,
    Text,
    Index,
    UniqueConstraint,
    Numeric,
    event,
    func,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# --- Generic Item Type System ---

class ItemType(Base):
    """
    Defines a type of menu item (sandwich, pizza, taco, drink, etc.).

    An ItemType with is_configurable=True has attribute definitions that allow
    customization (e.g., sandwiches have bread, protein, toppings).
    Items with is_configurable=False are simple items (e.g., chips, soda).
    """
    __tablename__ = "item_types"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)  # e.g., "sandwich", "pizza", "drink"
    display_name = Column(String, nullable=False)  # e.g., "Sandwich", "Pizza", "Drink"
    display_name_plural = Column(String, nullable=True)  # e.g., "coffees and teas" for sized_beverage (if irregular)
    is_configurable = Column(Boolean, nullable=False, default=True)  # True = has attributes to customize
    skip_config = Column(Boolean, nullable=False, default=False)  # True = skip config questions (e.g., sodas don't need hot/iced)

    # Category keyword support (replaces MENU_CATEGORY_KEYWORDS constant)
    aliases = Column(String, nullable=True)  # Comma-separated keywords that map to this type (e.g., "bagels" for "bagel")
    expands_to = Column(JSON, nullable=True)  # JSON array of slugs for meta-categories (e.g., ["pastry", "snack"] for "dessert")
    name_filter = Column(String, nullable=True)  # Substring filter for item names (e.g., "tea" to filter sized_beverage)
    is_virtual = Column(Boolean, nullable=True, default=False)  # True for meta-categories without direct items

    # Relationships
    attribute_definitions = relationship("AttributeDefinition", back_populates="item_type", cascade="all, delete-orphan")
    menu_items = relationship("MenuItem", back_populates="item_type")
    fields = relationship("ItemTypeField", back_populates="item_type", cascade="all, delete-orphan")
    type_attributes = relationship("ItemTypeAttribute", back_populates="item_type", cascade="all, delete-orphan")
    type_ingredients = relationship("ItemTypeIngredient", back_populates="item_type", cascade="all, delete-orphan")


class ItemTypeField(Base):
    """
    Defines configurable fields for each item type.

    This table stores field definitions like bagel_type, toasted, spread, etc.
    for each item type. Fields can be marked as required (must have value for
    item to be complete) and/or ask (should prompt user for this field).

    The question_text is used to prompt the user when asking for this field.
    Fields are ordered by display_order for consistent question sequence.
    """
    __tablename__ = "item_type_field"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=False)
    field_name = Column(String(100), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    required = Column(Boolean, nullable=False, default=False)  # Item needs this field to be complete
    ask = Column(Boolean, nullable=False, default=True)  # Should prompt user for this field
    question_text = Column(Text, nullable=True)  # Question to ask user for this field
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    item_type = relationship("ItemType", back_populates="fields")

    __table_args__ = (
        UniqueConstraint('item_type_id', 'field_name', name='uq_item_type_field_item_type_field'),
        Index('idx_item_type_field_item_type', 'item_type_id'),
    )


class ResponsePattern(Base):
    """
    Stores patterns for recognizing user response types.

    This table enables data-driven response classification for:
    - Affirmative responses (yes, yeah, yep, sure, ok, etc.)
    - Negative responses (no, nope, nah, no thanks, etc.)
    - Cancel responses (cancel, never mind, forget it, etc.)
    - Done responses (that's all, that's it, nothing else, etc.)

    Patterns are matched case-insensitively against normalized user input.
    """
    __tablename__ = "response_pattern"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String(50), nullable=False, index=True)  # 'affirmative', 'negative', 'cancel', 'done'
    pattern = Column(String(100), nullable=False)  # The pattern to match
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('pattern_type', 'pattern', name='uq_response_pattern_type_pattern'),
        Index('idx_response_pattern_type', 'pattern_type'),
    )


class ModifierCategory(Base):
    """
    Defines a modifier/add-on category for menu item customization.

    This maps user input keywords (like "sweetener", "sugar", "milk", "dairy")
    to canonical category names (like "sweeteners", "milks") for answering
    questions like "what sweeteners do you have?".

    Some categories are database-backed (toppings, proteins, cheeses, spreads)
    where items are loaded from the Ingredient table. Others are static
    (sweeteners, milks, syrups) with predefined descriptions.
    """
    __tablename__ = "modifier_categories"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, nullable=False, index=True)  # e.g., "sweeteners", "milks"
    display_name = Column(String, nullable=False)  # e.g., "Sweeteners", "Milks"
    aliases = Column(String, nullable=True)  # Comma-separated keywords: "sweetener, sugar, sugars"

    # For static response categories (not database-backed)
    description = Column(String, nullable=True)  # e.g., "we have sugar, raw sugar, honey..."
    prompt_suffix = Column(String, nullable=True)  # e.g., "Would you like any in your drink?"

    # For database-backed categories (load from Ingredient table)
    loads_from_ingredients = Column(Boolean, nullable=False, default=False)
    ingredient_category = Column(String, nullable=True)  # Maps to Ingredient.category value


class AttributeDefinition(Base):
    """
    Defines a customizable attribute for an item type.

    Examples for sandwich: bread, size, protein, cheese, toppings, sauces, toasted
    Examples for pizza: size, crust, sauce, toppings
    """
    __tablename__ = "attribute_definitions"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=False, index=True)

    slug = Column(String, nullable=False)  # e.g., "bread", "protein", "toppings"
    display_name = Column(String, nullable=False)  # e.g., "Bread", "Protein", "Toppings"

    # Input type determines UI and validation
    # "single_select": Pick exactly one (e.g., bread type)
    # "multi_select": Pick multiple (e.g., toppings)
    # "boolean": Yes/no (e.g., toasted)
    input_type = Column(String, nullable=False, default="single_select")

    # Validation rules
    is_required = Column(Boolean, nullable=False, default=True)  # Must be specified
    allow_none = Column(Boolean, nullable=False, default=False)  # Can select "none" option
    min_selections = Column(Integer, nullable=True)  # For multi_select: minimum selections
    max_selections = Column(Integer, nullable=True)  # For multi_select: maximum selections

    # Display order (lower = shown first)
    display_order = Column(Integer, nullable=False, default=0)

    # Unique constraint: one definition per slug per item type
    __table_args__ = (
        UniqueConstraint("item_type_id", "slug", name="uix_item_type_attr_slug"),
    )

    # Relationships
    item_type = relationship("ItemType", back_populates="attribute_definitions")
    options = relationship("AttributeOption", back_populates="attribute_definition", cascade="all, delete-orphan")


class AttributeOption(Base):
    """
    An available option for an attribute definition.

    Examples for bread attribute: white, wheat, italian, wrap
    Examples for toppings attribute: lettuce, tomato, onion, pickle
    """
    __tablename__ = "attribute_options"

    id = Column(Integer, primary_key=True, index=True)
    # Legacy FK - nullable during transition to item_type_attributes
    attribute_definition_id = Column(Integer, ForeignKey("attribute_definitions.id", ondelete="CASCADE"), nullable=True, index=True)

    # New FK to consolidated item_type_attributes (primary FK going forward)
    item_type_attribute_id = Column(Integer, ForeignKey("item_type_attributes.id", ondelete="CASCADE"), nullable=True, index=True)

    slug = Column(String, nullable=False)  # e.g., "white", "wheat", "lettuce"
    display_name = Column(String, nullable=False)  # e.g., "White Bread", "Wheat Bread", "Lettuce"

    price_modifier = Column(Float, nullable=False, default=0.0)  # +/- to base price
    iced_price_modifier = Column(Float, nullable=False, default=0.0)  # Additional upcharge when iced
    is_default = Column(Boolean, nullable=False, default=False)  # Pre-selected by default
    is_available = Column(Boolean, nullable=False, default=True)  # False = 86'd

    # Display order (lower = shown first)
    display_order = Column(Integer, nullable=False, default=0)

    # Unique constraint: one option per slug per attribute definition
    __table_args__ = (
        UniqueConstraint("attribute_definition_id", "slug", name="uix_attr_def_option_slug"),
    )

    # Relationships
    attribute_definition = relationship("AttributeDefinition", back_populates="options")
    item_type_attribute = relationship("ItemTypeAttribute")
    ingredient_links = relationship("AttributeOptionIngredient", back_populates="attribute_option", cascade="all, delete-orphan")


class ItemTypeAttribute(Base):
    """
    Consolidated attribute definition for item types.

    Merges the functionality of item_type_field (conversation flow) and
    attribute_definitions (UI configuration) into a single table.

    Examples for egg_sandwich: bread, bagel_type, protein, cheese, toppings, toasted
    Examples for sized_beverage: size, iced, milk, sweetener, syrup

    Each attribute can have:
    - Options (via attribute_options table) for single_select/multi_select types
    - A question_text for conversational prompts
    - Required/optional status for order completion
    """
    __tablename__ = "item_type_attributes"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=False, index=True)

    # Identity
    slug = Column(String(50), nullable=False)  # e.g., "bread", "bagel_type", "protein"
    display_name = Column(String(100), nullable=True)  # e.g., "Bread", "Bagel Type", "Protein"

    # Type and validation (from attribute_definitions)
    input_type = Column(String(20), nullable=False, default="single_select")
    # "single_select": Pick exactly one
    # "multi_select": Pick multiple
    # "boolean": Yes/no
    # "text": Free text input

    is_required = Column(Boolean, nullable=False, default=False)  # Must be specified for complete order
    allow_none = Column(Boolean, nullable=False, default=True)  # Can select "none" option
    min_selections = Column(Integer, nullable=True)  # For multi_select: minimum selections
    max_selections = Column(Integer, nullable=True)  # For multi_select: maximum selections

    # Conversational flow (from item_type_field)
    display_order = Column(Integer, nullable=False, default=0)  # Order in which to ask questions
    ask_in_conversation = Column(Boolean, nullable=False, default=True)  # Should prompt user for this
    question_text = Column(Text, nullable=True)  # Question to ask user for this field

    # Ingredient integration - when True, options come from item_type_ingredients table
    # instead of attribute_options, filtered by ingredient_group
    loads_from_ingredients = Column(Boolean, nullable=False, default=False)
    ingredient_group = Column(String(50), nullable=True)  # Links to ItemTypeIngredient.ingredient_group

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one attribute per slug per item type
    __table_args__ = (
        UniqueConstraint("item_type_id", "slug", name="uq_item_type_attributes_type_slug"),
    )

    # Relationships
    item_type = relationship("ItemType", back_populates="type_attributes")
    menu_item_values = relationship("MenuItemAttributeValue", back_populates="attribute", cascade="all, delete-orphan")
    menu_item_selections = relationship("MenuItemAttributeSelection", back_populates="attribute", cascade="all, delete-orphan")


class MenuItemAttributeValue(Base):
    """
    Stores attribute values for a specific menu item.

    This replaces the default_config JSON column on menu_items with a proper
    relational structure. Each menu item has one row per attribute.

    For example, "The Lexington" (an egg_sandwich) would have rows for:
    - bread: option_id -> "Bagel", still_ask=TRUE (ask which bagel type)
    - protein: option_id -> "Egg White", still_ask=FALSE (locked)
    - cheese: option_id -> "Swiss", still_ask=TRUE (default but changeable)
    - toasted: value_boolean=NULL, still_ask=TRUE (must ask)
    """
    __tablename__ = "menu_item_attribute_values"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(Integer, ForeignKey("item_type_attributes.id", ondelete="CASCADE"), nullable=False, index=True)

    # For single_select: store the selected option
    option_id = Column(Integer, ForeignKey("attribute_options.id", ondelete="SET NULL"), nullable=True)

    # For boolean type
    value_boolean = Column(Boolean, nullable=True)

    # For text type (rarely needed)
    value_text = Column(Text, nullable=True)

    # Whether to still ask user even if there's a default value
    # TRUE = ask (e.g., "which bagel type?", or "confirm cheese?")
    # FALSE = use value as-is (locked, don't ask)
    still_ask = Column(Boolean, nullable=False, default=False)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one value per attribute per menu item
    __table_args__ = (
        UniqueConstraint("menu_item_id", "attribute_id", name="uq_menu_item_attribute_values"),
    )

    # Relationships
    menu_item = relationship("MenuItem", back_populates="attribute_values")
    attribute = relationship("ItemTypeAttribute", back_populates="menu_item_values")
    option = relationship("AttributeOption")


class MenuItemAttributeSelection(Base):
    """
    Join table for multi-select attribute values.

    For menu items with multi-select attributes (like toppings), this stores
    one row per selected option.

    For example, if "The Lexington" has toppings: ["Spinach", "Tomato"], this
    table would have two rows linking the menu item to those topping options.
    """
    __tablename__ = "menu_item_attribute_selections"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, index=True)
    attribute_id = Column(Integer, ForeignKey("item_type_attributes.id", ondelete="CASCADE"), nullable=False)
    option_id = Column(Integer, ForeignKey("attribute_options.id", ondelete="CASCADE"), nullable=False)

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())

    # Unique constraint: one entry per option per attribute per menu item
    __table_args__ = (
        UniqueConstraint("menu_item_id", "attribute_id", "option_id", name="uq_menu_item_attr_selection"),
    )

    # Relationships
    menu_item = relationship("MenuItem", back_populates="attribute_selections")
    attribute = relationship("ItemTypeAttribute", back_populates="menu_item_selections")
    option = relationship("AttributeOption")


class AttributeOptionIngredient(Base):
    """
    Links an attribute option to an ingredient for inventory tracking.

    This allows the 86 system to work with generic attributes - when an ingredient
    runs out, all attribute options using that ingredient become unavailable.

    An option can use multiple ingredients (e.g., a "loaded" topping option).
    """
    __tablename__ = "attribute_option_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    attribute_option_id = Column(Integer, ForeignKey("attribute_options.id", ondelete="CASCADE"), nullable=False, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False, index=True)

    quantity = Column(Float, nullable=False, default=1.0)  # Amount of ingredient used

    # Unique constraint: one link per option per ingredient
    __table_args__ = (
        UniqueConstraint("attribute_option_id", "ingredient_id", name="uix_attr_option_ingredient"),
    )

    # Relationships
    attribute_option = relationship("AttributeOption", back_populates="ingredient_links")
    ingredient = relationship("Ingredient", back_populates="attribute_option_links")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="confirmed", index=True)  # e.g., pending/confirmed/preparing/ready/completed/cancelled
    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)  # Email for payment links
    pickup_time = Column(String, nullable=True)

    # Price breakdown
    subtotal = Column(Float, nullable=True)  # Sum of line items before tax
    city_tax = Column(Float, nullable=True)  # City tax amount
    state_tax = Column(Float, nullable=True)  # State tax amount
    delivery_fee = Column(Float, nullable=True)  # Delivery fee (if delivery order)
    total_price = Column(Float, nullable=False, default=0.0)  # Final total including tax and fees

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    store_id = Column(String, nullable=True, index=True)  # Store identifier (e.g., "store_eb_001")

    # Order type: pickup or delivery
    order_type = Column(String, nullable=False, default="pickup")  # "pickup" or "delivery"
    delivery_address = Column(String, nullable=True)  # Address for delivery orders

    # Payment tracking
    payment_status = Column(String, nullable=False, default="unpaid")  # "unpaid", "pending_payment", "paid"
    payment_method = Column(String, nullable=True)  # "cash", "card_in_store", "card_phone", "card_link"

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    # Composite index for common query pattern: filtering by status and sorting by date
    __table_args__ = (
        Index("ix_orders_status_created_at", "status", "created_at"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=True)

    menu_item_name = Column(String, nullable=False)

    # Generic item type system
    item_type_id = Column(Integer, ForeignKey("item_types.id"), nullable=True, index=True)

    # Item configuration (JSON) - stores all item-specific details
    # e.g., {"item_type": "bagel", "bagel_type": "everything", "spread": "cream cheese", "toasted": true}
    # e.g., {"item_type": "drink", "size": "large", "milk": "oat", "style": "iced"}
    item_config = Column(JSON, nullable=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)

    # You can keep this if you want extra arbitrary config, or remove if unused
    extra = Column(JSON, default=dict)

    # Free-form notes for special instructions that don't fit standard modifiers
    # e.g., "light on the cream cheese", "extra crispy", "a splash of milk"
    notes = Column(String, nullable=True)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem", back_populates="order_items")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)  # Item description (e.g., "Two Eggs, Bacon, and Cheddar")
    category = Column(String, nullable=False, index=True)  # 'sandwich', 'side', 'drink', 'dessert', etc.
    is_signature = Column(Boolean, default=False, nullable=False)
    base_price = Column(Float, nullable=False)
    available_qty = Column(Integer, default=0, nullable=False)

    extra_metadata = Column(Text, nullable=True)

    # Link to generic item type system (optional - for migration compatibility)
    item_type_id = Column(Integer, ForeignKey("item_types.id"), nullable=True, index=True)
    item_type = relationship("ItemType", back_populates="menu_items")

    # Default configuration for this menu item (JSON)
    # e.g., {"bread": "italian", "protein": "turkey", "cheese": "provolone", "toasted": true}
    default_config = Column(JSON, nullable=True)

    # Required match phrases for search filtering (comma-separated)
    # If set, user input must contain at least ONE of these phrases for a match
    # Example: "coffee cake, cake" for "Russian Coffee Cake" prevents "coffee" from matching
    required_match_phrases = Column(String, nullable=True)

    # Aliases for matching user input to this item (comma-separated)
    # Example: "coke, coca cola" for "Coca-Cola" allows "coke" to match
    aliases = Column(String, nullable=True)

    # Abbreviation for text expansion (e.g., "oj" expands to "orange juice" before parsing)
    abbreviation = Column(String, nullable=True)

    # By-the-pound category for items sold by weight
    # Values: 'fish', 'spread', 'cheese', 'cold_cut', 'salad'
    by_pound_category = Column(String, nullable=True)

    # Classifier for sub-category grouping (e.g., 'muffin', 'cookie', 'omelette')
    # Enables filtering like "what muffins do you have?" without hardcoded lists
    classifier = Column(String, nullable=True, index=True)

    # Dietary attributes (computed/cached from ingredients - NULL = not computed)
    # For "is_X" flags: True only if ALL ingredients qualify
    # For "contains_X" flags: True if ANY ingredient contains the allergen
    is_vegan = Column(Boolean, nullable=True)
    is_vegetarian = Column(Boolean, nullable=True)
    is_gluten_free = Column(Boolean, nullable=True)
    is_dairy_free = Column(Boolean, nullable=True)
    is_kosher = Column(Boolean, nullable=True)

    # Allergen attributes
    contains_eggs = Column(Boolean, nullable=True)
    contains_fish = Column(Boolean, nullable=True)
    contains_sesame = Column(Boolean, nullable=True)
    contains_nuts = Column(Boolean, nullable=True)

    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    recipe = relationship("Recipe", back_populates="menu_items")

    order_items = relationship(
        "OrderItem",
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )
    store_availability = relationship("MenuItemStoreAvailability", back_populates="menu_item", cascade="all, delete-orphan")
    attribute_values = relationship("MenuItemAttributeValue", back_populates="menu_item", cascade="all, delete-orphan")
    attribute_selections = relationship("MenuItemAttributeSelection", back_populates="menu_item", cascade="all, delete-orphan")


# --- Per-store menu item availability (86 system) ---

class MenuItemStoreAvailability(Base):
    """Tracks menu item availability per store. If no entry exists for a store+item, assume available."""
    __tablename__ = "menu_item_store_availability"

    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(String, nullable=False, index=True)
    is_available = Column(Boolean, nullable=False, default=True)

    # Unique constraint: one entry per menu item per store
    __table_args__ = (
        UniqueConstraint("menu_item_id", "store_id", name="uix_menu_item_store"),
    )

    # relationships
    menu_item = relationship("MenuItem", back_populates="store_availability")


# --- New Ingredient model ---

class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)  # Canonical identifier (e.g., "oat_milk")
    category = Column(String, nullable=False)   # 'bread', 'protein', 'cheese', 'topping', 'sauce', 'side', 'drink', etc.
    unit = Column(String, nullable=False)       # 'slice', 'piece', 'oz', 'bag', 'ml', etc.
    track_inventory = Column(Boolean, nullable=False, default=True)
    base_price = Column(Float, nullable=False, default=0.0)  # Price for custom sandwiches (proteins mainly)
    is_available = Column(Boolean, nullable=False, default=True)  # False = "86'd" / out of stock

    # Dietary attributes (source of truth - ingredients define what they are)
    is_vegan = Column(Boolean, nullable=False, default=False)
    is_vegetarian = Column(Boolean, nullable=False, default=False)
    is_gluten_free = Column(Boolean, nullable=False, default=False)
    is_dairy_free = Column(Boolean, nullable=False, default=False)
    is_kosher = Column(Boolean, nullable=False, default=False)

    # Allergen attributes (what allergens this ingredient contains)
    contains_eggs = Column(Boolean, nullable=False, default=False)
    contains_fish = Column(Boolean, nullable=False, default=False)
    contains_sesame = Column(Boolean, nullable=False, default=False)
    contains_nuts = Column(Boolean, nullable=False, default=False)

    # Aliases for matching (comma-separated, e.g., "wheat" for "Whole Wheat Bagel")
    aliases = Column(Text, nullable=True)

    # Abbreviation for text expansion (e.g., "cc" expands to "cream cheese" before parsing)
    abbreviation = Column(String, nullable=True)

    # relationships
    recipe_items = relationship("RecipeIngredient", back_populates="ingredient", cascade="all, delete-orphan")
    choice_for = relationship("RecipeChoiceItem", back_populates="ingredient", cascade="all, delete-orphan")
    store_availability = relationship("IngredientStoreAvailability", back_populates="ingredient", cascade="all, delete-orphan")
    attribute_option_links = relationship("AttributeOptionIngredient", back_populates="ingredient", cascade="all, delete-orphan")
    item_type_links = relationship("ItemTypeIngredient", back_populates="ingredient", cascade="all, delete-orphan")


# --- Per-store ingredient availability (86 system) ---

class IngredientStoreAvailability(Base):
    """Tracks ingredient availability per store. If no entry exists for a store+ingredient, assume available."""
    __tablename__ = "ingredient_store_availability"

    id = Column(Integer, primary_key=True, index=True)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)
    store_id = Column(String, nullable=False, index=True)
    is_available = Column(Boolean, nullable=False, default=True)

    # Unique constraint: one entry per ingredient per store
    __table_args__ = (
        UniqueConstraint("ingredient_id", "store_id", name="uix_ingredient_store"),
    )

    # relationships
    ingredient = relationship("Ingredient", back_populates="store_availability")


# --- Item Type Ingredients (for unified ingredient management across item types) ---

class ItemTypeIngredient(Base):
    """
    Links ingredients to item types with per-type configuration.

    This enables a unified ingredient system where physical items like milk,
    sweeteners, and syrups can be managed alongside proteins, toppings, and spreads
    in a single ingredients table, with per-item-type configuration.

    When an attribute has loads_from_ingredients=True, its options come from
    this table filtered by ingredient_group, instead of from attribute_options.

    Examples:
    - Oat Milk linked to 'sized_beverage' with ingredient_group='milk', price_modifier=0.75
    - Bacon linked to 'bagel' with ingredient_group='protein', price_modifier=3.00
    - Vanilla Syrup linked to 'sized_beverage' with ingredient_group='syrup', price_modifier=0.50
    """
    __tablename__ = "item_type_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    item_type_id = Column(Integer, ForeignKey("item_types.id", ondelete="CASCADE"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id", ondelete="CASCADE"), nullable=False)

    # Grouping - which selector/category this appears in
    # e.g., 'milk', 'sweetener', 'syrup', 'spread', 'protein', 'topping', 'cheese'
    ingredient_group = Column(String(50), nullable=False)

    # Pricing - can vary by item type (oat milk might cost different for latte vs iced coffee)
    price_modifier = Column(Numeric(10, 2), nullable=False, default=0.00)

    # Display configuration
    display_order = Column(Integer, nullable=False, default=0)
    display_name_override = Column(String(100), nullable=True)  # e.g., "Oat" instead of "Oat Milk"

    # Selection behavior
    is_default = Column(Boolean, nullable=False, default=False)
    is_available = Column(Boolean, nullable=False, default=True)  # Per-item-type override

    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Unique constraint: one entry per item_type + ingredient + group combination
    __table_args__ = (
        UniqueConstraint('item_type_id', 'ingredient_id', 'ingredient_group', name='uq_item_type_ingredient_group'),
        Index('idx_item_type_ingredients_item_type', 'item_type_id'),
        Index('idx_item_type_ingredients_ingredient', 'ingredient_id'),
        Index('idx_item_type_ingredients_group', 'ingredient_group'),
        Index('idx_item_type_ingredients_item_type_group', 'item_type_id', 'ingredient_group'),
    )

    # Relationships
    item_type = relationship("ItemType", back_populates="type_ingredients")
    ingredient = relationship("Ingredient", back_populates="item_type_links")


# --- New Recipe model ---

class Recipe(Base):
    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # One recipe can be used by one or more menu items (though in practice it's usually 1:1)
    menu_items = relationship("MenuItem", back_populates="recipe")

    # relationships to ingredients and choice groups
    ingredients = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan")
    choice_groups = relationship("RecipeChoiceGroup", back_populates="recipe", cascade="all, delete-orphan")


# --- New RecipeIngredient model (base, always-included items) ---

class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)

    quantity = Column(Float, nullable=False)         # e.g. 2.0
    unit_override = Column(String, nullable=True)    # override Ingredient.unit if needed
    is_required = Column(Boolean, nullable=False, default=True)

    recipe = relationship("Recipe", back_populates="ingredients")
    ingredient = relationship("Ingredient", back_populates="recipe_items")


# --- New RecipeChoiceGroup model (e.g. "Bread", "Cheese", "Sauce") ---

class RecipeChoiceGroup(Base):
    __tablename__ = "recipe_choice_groups"

    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)

    name = Column(String, nullable=False)            # 'Bread', 'Cheese', 'Sauce', etc.
    min_choices = Column(Integer, nullable=False, default=1)
    max_choices = Column(Integer, nullable=False, default=1)
    is_required = Column(Boolean, nullable=False, default=True)

    recipe = relationship("Recipe", back_populates="choice_groups")
    choices = relationship("RecipeChoiceItem", back_populates="choice_group", cascade="all, delete-orphan")


# --- New RecipeChoiceItem model (the options inside a choice group) ---

class RecipeChoiceItem(Base):
    __tablename__ = "recipe_choice_items"

    id = Column(Integer, primary_key=True, index=True)
    choice_group_id = Column(Integer, ForeignKey("recipe_choice_groups.id"), nullable=False)
    ingredient_id = Column(Integer, ForeignKey("ingredients.id"), nullable=False)

    is_default = Column(Boolean, nullable=False, default=False)
    extra_price = Column(Float, nullable=False, default=0.0)

    choice_group = relationship("RecipeChoiceGroup", back_populates="choices")
    ingredient = relationship("Ingredient", back_populates="choice_for")


# --- Chat Session model for persistence ---

class ChatSession(Base):
    """
    Persists chat sessions to the database so they survive server restarts.
    """
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, nullable=False, index=True)  # UUID string

    # Store conversation history as JSON
    history = Column(JSON, nullable=False, default=list)

    # Store order state as JSON
    order_state = Column(JSON, nullable=False, default=dict)

    # Track which menu version was sent in system prompt (for token optimization)
    # If None, menu hasn't been sent yet; otherwise contains menu hash
    menu_version_sent = Column(String, nullable=True, default=None)

    # Store identifier for per-store availability (86 system)
    store_id = Column(String, nullable=True, index=True)

    # Caller ID for returning customer identification
    caller_id = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# --- Session Analytics model for tracking all sessions ---

class SessionAnalytics(Base):
    """
    Tracks all sessions for analytics - both abandoned and completed.
    Used to analyze user behavior and identify UX issues.
    """
    __tablename__ = "session_analytics"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, nullable=False, index=True)  # UUID string from chat session

    # Session outcome
    status = Column(String, nullable=False, default="abandoned", index=True)  # 'abandoned' or 'completed'

    # Session state at end
    message_count = Column(Integer, nullable=False, default=0)  # How many messages exchanged
    had_items_in_cart = Column(Boolean, nullable=False, default=False)  # Were there items in cart?
    item_count = Column(Integer, nullable=False, default=0)  # Number of items in cart
    cart_total = Column(Float, nullable=False, default=0.0)  # Cart/order value
    order_status = Column(String, nullable=False, default="pending")  # pending, confirmed, etc.

    # Full conversation history (JSON array of {role, content} objects)
    conversation_history = Column(JSON, nullable=True, default=list)

    # Last interaction details (kept for backward compatibility and quick queries)
    last_bot_message = Column(Text, nullable=True)  # What was the bot's last message?
    last_user_message = Column(Text, nullable=True)  # What did user say last?

    # Session details
    reason = Column(String, nullable=True)  # For abandoned: browser_close, refresh, navigation. For completed: null
    session_duration_seconds = Column(Integer, nullable=True)  # How long was the session?

    # Customer info (for completed orders)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)

    # Store info
    store_id = Column(String, nullable=True, index=True)  # Store identifier (e.g., "store_eb_001")

    # Timestamp
    ended_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


# Alias for backward compatibility
AbandonedSession = SessionAnalytics


# --- Store model for multi-location support ---

class Store(Base):
    """
    Represents a physical store location.
    Stores are managed via the admin interface and used for:
    - Store selection in customer chat
    - Per-store ingredient/menu item availability (86 system)
    - Order attribution
    """
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(String, unique=True, nullable=False, index=True)  # e.g., "store_eb_001"
    name = Column(String, nullable=False)  # e.g., "Sammy's Subs - East Brunswick"
    address = Column(String, nullable=False)
    city = Column(String, nullable=False)
    state = Column(String(2), nullable=False)  # e.g., "NJ"
    zip_code = Column(String(10), nullable=False)
    phone = Column(String, nullable=False)
    hours = Column(Text, nullable=True)  # Store hours description
    timezone = Column(String, nullable=False, default="America/New_York")  # IANA timezone, e.g., "America/Los_Angeles"
    status = Column(String, nullable=False, default="open")  # "open" or "closed"
    payment_methods = Column(JSON, nullable=False, default=list)  # ["cash", "credit", "bitcoin"]

    # Tax rates (stored as decimals, e.g., 0.04 for 4%)
    city_tax_rate = Column(Float, nullable=False, default=0.0)  # City/local tax rate
    state_tax_rate = Column(Float, nullable=False, default=0.0)  # State tax rate

    # Delivery configuration
    delivery_zip_codes = Column(JSON, nullable=False, default=list)  # List of zip codes for delivery
    delivery_fee = Column(Float, nullable=False, default=2.99)  # Delivery fee in dollars

    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# --- Neighborhood to Zip Code mapping ---

class NeighborhoodZipCode(Base):
    """
    Maps neighborhood names to their zip codes.
    Used for delivery zone lookups when customers specify a neighborhood.
    """
    __tablename__ = "neighborhood_zip_codes"

    id = Column(Integer, primary_key=True, index=True)
    neighborhood = Column(String(100), unique=True, nullable=False, index=True)
    zip_codes = Column(JSON, nullable=False, default=list)  # List of zip codes
    borough = Column(String(50), nullable=True)  # Manhattan, Brooklyn, Queens, Bronx


# --- Company model for company-level settings ---

class Company(Base):
    """
    Stores company-level settings such as name, contact info, branding.
    This is a single-row table - there should only be one company record.
    """
    __tablename__ = "company"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, default="Sammy's Subs")  # Company name shown to customers
    bot_persona_name = Column(String, nullable=False, default="Sammy")  # Bot's name/persona
    tagline = Column(String, nullable=True)  # e.g., "The best subs in town!"
    signature_item_label = Column(String, nullable=True)  # Custom label for signature items (e.g., "speed menu bagel")

    # Contact info
    headquarters_address = Column(String, nullable=True)
    corporate_phone = Column(String, nullable=True)
    corporate_email = Column(String, nullable=True)
    website = Column(String, nullable=True)

    # Social media & feedback
    instagram_handle = Column(String, nullable=True)  # e.g., "@zuckersbagels"
    feedback_form_url = Column(String, nullable=True)  # URL to customer feedback form

    # Branding
    logo_url = Column(String, nullable=True)  # URL to company logo

    # Business hours (JSON for structured format)
    business_hours = Column(JSON, nullable=True)  # e.g., {"mon": "9-5", "tue": "9-5", ...}

    # Payment Methods
    accepts_credit_cards = Column(Boolean, nullable=False, default=True)
    accepts_debit_cards = Column(Boolean, nullable=False, default=True)
    accepts_cash = Column(Boolean, nullable=False, default=True)
    accepts_apple_pay = Column(Boolean, nullable=False, default=False)
    accepts_google_pay = Column(Boolean, nullable=False, default=False)
    accepts_venmo = Column(Boolean, nullable=False, default=False)
    accepts_paypal = Column(Boolean, nullable=False, default=False)

    # Dietary & Certification Info
    is_kosher = Column(Boolean, nullable=False, default=False)
    kosher_certification = Column(String, nullable=True)  # e.g., "Tablet K", "OU", "OK"
    is_halal = Column(Boolean, nullable=False, default=False)
    has_vegetarian_options = Column(Boolean, nullable=False, default=True)
    has_vegan_options = Column(Boolean, nullable=False, default=True)
    has_gluten_free_options = Column(Boolean, nullable=False, default=False)

    # Amenities
    wifi_available = Column(Boolean, nullable=False, default=False)
    wheelchair_accessible = Column(Boolean, nullable=False, default=True)
    outdoor_seating = Column(Boolean, nullable=False, default=False)

    # Catering
    offers_catering = Column(Boolean, nullable=False, default=False)
    catering_minimum_order = Column(Numeric(10, 2), nullable=True)  # e.g., 50.00
    catering_advance_notice_hours = Column(Integer, nullable=True)  # e.g., 24
    catering_phone = Column(String, nullable=True)
    catering_email = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# --- MenuItem Insert Logging (for debugging duplicate inserts) ---
# Enable with environment variable: MENU_ITEM_INSERT_LOGGING=1

_menu_item_insert_logger = logging.getLogger("menu_item_inserts")


@event.listens_for(MenuItem, "before_insert")
def log_menu_item_insert(mapper, connection, target):
    """Log MenuItem inserts with stack trace to help identify duplicate sources."""
    if not os.environ.get("MENU_ITEM_INSERT_LOGGING"):
        return

    stack = "".join(traceback.format_stack()[:-1])  # Exclude this function
    _menu_item_insert_logger.warning(
        f"MenuItem INSERT: name='{target.name}', category='{target.category}'\n"
        f"Stack trace:\n{stack}"
    )