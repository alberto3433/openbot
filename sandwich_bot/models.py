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
    is_configurable = Column(Boolean, nullable=False, default=True)  # True = has attributes to customize
    skip_config = Column(Boolean, nullable=False, default=False)  # True = skip config questions (e.g., sodas don't need hot/iced)

    # Relationships
    attribute_definitions = relationship("AttributeDefinition", back_populates="item_type", cascade="all, delete-orphan")
    menu_items = relationship("MenuItem", back_populates="item_type")


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
    attribute_definition_id = Column(Integer, ForeignKey("attribute_definitions.id", ondelete="CASCADE"), nullable=False, index=True)

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
    ingredient_links = relationship("AttributeOptionIngredient", back_populates="attribute_option", cascade="all, delete-orphan")


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
    name = Column(String, nullable=False)
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

    # By-the-pound category for items sold by weight
    # Values: 'fish', 'spread', 'cheese', 'cold_cut', 'salad'
    by_pound_category = Column(String, nullable=True)

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

    # relationships
    recipe_items = relationship("RecipeIngredient", back_populates="ingredient", cascade="all, delete-orphan")
    choice_for = relationship("RecipeChoiceItem", back_populates="ingredient", cascade="all, delete-orphan")
    store_availability = relationship("IngredientStoreAvailability", back_populates="ingredient", cascade="all, delete-orphan")
    attribute_option_links = relationship("AttributeOptionIngredient", back_populates="ingredient", cascade="all, delete-orphan")


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

    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


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

    # Branding
    logo_url = Column(String, nullable=True)  # URL to company logo

    # Business hours (JSON for structured format)
    business_hours = Column(JSON, nullable=True)  # e.g., {"mon": "9-5", "tue": "9-5", ...}

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)