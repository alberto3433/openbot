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


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="confirmed", index=True)  # e.g., draft/confirmed/cancelled
    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    pickup_time = Column(String, nullable=True)
    total_price = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    store_id = Column(String, nullable=True, index=True)  # Store identifier (e.g., "store_eb_001")

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

    # 🔹 New columns to match persist_confirmed_order and OrderItemOut
    item_type = Column(String, nullable=True)
    size = Column(String, nullable=True)
    bread = Column(String, nullable=True)
    protein = Column(String, nullable=True)
    cheese = Column(String, nullable=True)
    toppings = Column(JSON, nullable=True)   # stores list
    sauces = Column(JSON, nullable=True)     # stores list
    toasted = Column(Boolean, nullable=True)

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    line_total = Column(Float, nullable=False)

    # You can keep this if you want extra arbitrary config, or remove if unused
    extra = Column(JSON, default=dict)

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

    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=True)
    recipe = relationship("Recipe", back_populates="menu_items")

    # 🔹 Add this block:
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

    # relationships
    recipe_items = relationship("RecipeIngredient", back_populates="ingredient", cascade="all, delete-orphan")
    choice_for = relationship("RecipeChoiceItem", back_populates="ingredient", cascade="all, delete-orphan")
    store_availability = relationship("IngredientStoreAvailability", back_populates="ingredient", cascade="all, delete-orphan")


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