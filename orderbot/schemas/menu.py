"""
Menu Item Schemas for Orderbot
===================================

This module defines Pydantic models for menu item CRUD operations. Menu items
represent products that customers can order, such as sandwiches, bagels,
drinks, and sides.

Endpoint Coverage:
------------------
- GET /admin/menu: List all menu items
- POST /admin/menu: Create a new menu item
- GET /admin/menu/{id}: Get a specific menu item
- PUT /admin/menu/{id}: Update a menu item
- DELETE /admin/menu/{id}: Delete a menu item

Menu Item Concepts:
-------------------
1. **Signature Items**: Pre-configured items on the "speed menu" that can be
   ordered by name without customization (e.g., "The Italian", "Classic BLT").

2. **Item Types**: Link to ItemType for configurable items. Determines what
   attributes (bread, size, toppings) are available for customization.

3. **Base Price**: Starting price before any modifiers. Actual price may vary
   based on size, add-ons, and other attribute selections.

4. **Ingredients**: Default ingredients stored via menu_item_ingredients
   junction table (e.g., a BEC sandwich has bacon, egg, cheese).

5. **Available Qty**: Legacy inventory field (kept for compatibility).
   Modern inventory uses the "86" system via Ingredient.is_available.

Availability:
-------------
Menu item availability can be controlled at two levels:
- Global: Set via the MenuItem record
- Per-Store: Set via MenuItemStoreAvailability for multi-location support

Usage:
------
    # Create a new menu item
    item_data = MenuItemCreate(
        name="Turkey Club",
        is_signature=True,
        base_price=12.99,
        item_type_id=3,
    )

    # Response will include the generated ID
    new_item = MenuItemOut.model_validate(db_item)
"""

from pydantic import BaseModel, ConfigDict


class SizePriceOut(BaseModel):
    """Size price entry for a menu item."""
    size_id: int
    size_name: str
    price: float


class MenuItemIngredientOut(BaseModel):
    """Ingredient entry for a menu item."""
    ingredient_id: int
    ingredient_name: str
    ingredient_category: str
    quantity: int


class MenuItemIngredientInput(BaseModel):
    """Ingredient entry for creating/updating a menu item."""
    ingredient_id: int
    quantity: int = 1


class MenuItemOut(BaseModel):
    """
    Response model for menu item data.

    Used when returning menu item information from the API.
    Can be created directly from SQLAlchemy MenuItem objects.

    Attributes:
        id: Database primary key
        name: Display name (e.g., "Turkey Club")
        category: DEPRECATED - Derived from item_type.display_name for backward compatibility
        is_signature: Whether this is a pre-configured signature item
        base_price: Starting price in dollars
        available_qty: Legacy inventory count (use 86 system instead)
        item_type_id: Foreign key to ItemType for configuration options
        aliases: List of synonyms for matching (e.g., ["coke", "coca cola"])
        abbreviation: Short form expanded before parsing (e.g., "oj" for "orange juice")
        ingredients: Default ingredients via menu_item_ingredients junction table
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None = None
    category: str | None = None  # DEPRECATED - derived from item_type.display_name
    is_signature: bool
    base_price: float
    available_qty: int
    item_type_id: int | None = None
    aliases: list[str] = []
    abbreviation: str | None = None
    required_match_phrases: str | None = None
    size_category_id: int | None = None
    size_prices: list[SizePriceOut] = []
    ingredients: list[MenuItemIngredientOut] = []

    # Dietary attributes (computed from ingredients when available, else stored values)
    is_vegan: bool | None = None
    is_vegetarian: bool | None = None
    is_gluten_free: bool | None = None
    is_dairy_free: bool | None = None
    is_kosher: bool | None = None

    # Allergen attributes
    contains_eggs: bool | None = None
    contains_fish: bool | None = None
    contains_sesame: bool | None = None
    contains_nuts: bool | None = None

    # True when item has ingredients defined (dietary values are computed, not editable)
    has_ingredients: bool = False

    # Unit of sale
    unit_type: str = "each"  # each, by_weight, dozen, pack
    quantity_per_unit: int | None = None  # Number of items per unit (for packs)


class SizePriceInput(BaseModel):
    """Size price entry for creating/updating a menu item."""
    size_id: int
    price: float


class MenuItemCreate(BaseModel):
    """
    Request model for creating a new menu item.

    Required fields: name, base_price (or size_prices)
    Recommended: item_type_id (for configuration)

    Attributes:
        name: Display name (required, must be unique)
        is_signature: Whether this is a signature item (default: False)
        base_price: Starting price in dollars (required if no size_prices)
        available_qty: Legacy inventory count (default: 0)
        item_type_id: Link to ItemType for configuration (recommended)
        aliases: Comma-separated synonyms for matching (optional)
        abbreviation: Short form expanded before parsing (e.g., "oj" for "orange juice")

    Example:
        {
            "name": "Veggie Delight",
            "item_type_id": 3,
            "is_signature": true,
            "base_price": 10.99
        }
    """
    name: str
    description: str | None = None
    is_signature: bool = False
    base_price: float | None = None
    available_qty: int = 0
    item_type_id: int | None = None
    aliases: str | None = None
    abbreviation: str | None = None
    required_match_phrases: str | None = None
    size_category_id: int | None = None
    size_prices: list[SizePriceInput] | None = None

    # Dietary attributes (used as fallback when no ingredients defined)
    is_vegan: bool | None = None
    is_vegetarian: bool | None = None
    is_gluten_free: bool | None = None
    is_dairy_free: bool | None = None
    is_kosher: bool | None = None

    # Allergen attributes
    contains_eggs: bool | None = None
    contains_fish: bool | None = None
    contains_sesame: bool | None = None
    contains_nuts: bool | None = None

    # Unit of sale
    unit_type: str | None = None  # each, by_weight, dozen, pack
    quantity_per_unit: int | None = None  # Number of items per unit (for packs)


class MenuItemUpdate(BaseModel):
    """
    Request model for updating a menu item.

    All fields are optional - only provided fields will be updated.
    This supports partial updates (PATCH semantics) even on PUT endpoints.

    Attributes:
        name: New display name (optional)
        is_signature: Update signature status (optional)
        base_price: New base price (optional)
        available_qty: Update inventory count (optional)
        item_type_id: Change linked ItemType (optional)
        aliases: Comma-separated synonyms for matching (optional)
        abbreviation: Short form expanded before parsing (e.g., "oj" for "orange juice")
        ingredients: List of ingredient entries to assign (replaces existing)

    Example:
        # Update only the price
        {"base_price": 11.99}

        # Update multiple fields
        {"name": "Super Veggie Delight", "base_price": 12.99}
    """
    name: str | None = None
    description: str | None = None
    is_signature: bool | None = None
    base_price: float | None = None
    available_qty: int | None = None
    item_type_id: int | None = None
    aliases: str | None = None
    abbreviation: str | None = None
    required_match_phrases: str | None = None
    size_category_id: int | None = None
    size_prices: list[SizePriceInput] | None = None
    ingredients: list[MenuItemIngredientInput] | None = None

    # Dietary attributes (used as fallback when no ingredients defined)
    is_vegan: bool | None = None
    is_vegetarian: bool | None = None
    is_gluten_free: bool | None = None
    is_dairy_free: bool | None = None
    is_kosher: bool | None = None

    # Allergen attributes
    contains_eggs: bool | None = None
    contains_fish: bool | None = None
    contains_sesame: bool | None = None
    contains_nuts: bool | None = None

    # Unit of sale
    unit_type: str | None = None  # each, by_weight, dozen, pack
    quantity_per_unit: int | None = None  # Number of items per unit (for packs)
