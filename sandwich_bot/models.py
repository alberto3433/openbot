from sqlalchemy import Column, Integer, String, Float, Boolean, JSON, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, relationship

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship

Base = declarative_base()


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    status = Column(String, nullable=False, default="confirmed")  # e.g., draft/confirmed/cancelled
    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    pickup_time = Column(String, nullable=True)
    total_price = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
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
    category = Column(String, nullable=False)  # 'sandwich', 'side', 'drink', 'dessert', etc.
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

# --- New Ingredient model ---

class Ingredient(Base):
    __tablename__ = "ingredients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    category = Column(String, nullable=False)   # 'bread', 'protein', 'cheese', 'topping', 'sauce', 'side', 'drink', etc.
    unit = Column(String, nullable=False)       # 'slice', 'piece', 'oz', 'bag', 'ml', etc.
    track_inventory = Column(Boolean, nullable=False, default=True)

    # relationships
    recipe_items = relationship("RecipeIngredient", back_populates="ingredient", cascade="all, delete-orphan")
    choice_for = relationship("RecipeChoiceItem", back_populates="ingredient", cascade="all, delete-orphan")


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

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)