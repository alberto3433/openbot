"""
Ingredient Schemas for Sandwich Bot
====================================

This module defines Pydantic models for ingredient management, including the
"86" system for marking items as out of stock. Ingredients represent the
building blocks of menu items (breads, proteins, cheeses, toppings, sauces).

Endpoint Coverage:
------------------
- GET /admin/ingredients: List all ingredients
- POST /admin/ingredients: Create a new ingredient
- GET /admin/ingredients/{id}: Get a specific ingredient
- PUT /admin/ingredients/{id}: Update an ingredient
- PATCH /admin/ingredients/{id}/availability: Quick 86/un-86 toggle
- DELETE /admin/ingredients/{id}: Delete an ingredient
- GET /admin/ingredients/unavailable: List all 86'd ingredients
- GET /admin/ingredients/menu-items: List menu items with availability
- PATCH /admin/ingredients/menu-items/{id}/availability: Toggle menu item availability

The "86" System:
----------------
In restaurant terminology, "86" means an item is unavailable/out of stock.
Rather than tracking exact inventory counts, this system uses a simple
boolean flag (is_available) that staff can toggle quickly.

When an ingredient is 86'd:
1. The chatbot won't offer it as an option
2. Orders containing it will show a warning
3. The admin dashboard highlights it for restocking

Availability Levels:
--------------------
1. **Global Availability** (Ingredient.is_available):
   Affects all stores. Use when ingredient is completely out.

2. **Store-Specific Availability** (IngredientStoreAvailability):
   Allows different availability per location. Useful for multi-store
   operations where one location may run out while others have stock.

Ingredient Categories:
----------------------
- bread: Bread types (white, wheat, sourdough, etc.)
- protein: Meats and proteins (turkey, ham, bacon, etc.)
- cheese: Cheese options (american, swiss, cheddar, etc.)
- topping: Vegetables and toppings (lettuce, tomato, onion, etc.)
- sauce: Sauces and condiments (mayo, mustard, oil & vinegar, etc.)
- spread: Spreads for bagels (cream cheese, butter, etc.)

Usage:
------
    # Mark an ingredient as 86'd (out of stock)
    update = IngredientAvailabilityUpdate(is_available=False)

    # Mark as 86'd at a specific store only
    update = IngredientAvailabilityUpdate(
        is_available=False,
        store_id="store_eb_001"
    )
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class IngredientOut(BaseModel):
    """
    Response model for ingredient data.

    Basic ingredient information without store-specific availability.
    The is_available field reflects global availability.

    Attributes:
        id: Database primary key
        name: Display name (e.g., "Swiss Cheese")
        category: Type category (bread, protein, cheese, topping, sauce)
        unit: Unit of measurement (piece, oz, slice, etc.)
        track_inventory: Whether to track counts (legacy, usually False)
        is_available: Global availability (False = 86'd everywhere)
        aliases: List of synonyms for matching (e.g., ["wheat"] for "Whole Wheat Bagel")
        must_match: List of strings - at least one must be in input for this to match
        abbreviation: Short form expanded before parsing (e.g., "cc" for "cream cheese")
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    unit: str
    track_inventory: bool
    is_available: bool
    aliases: list[str] = []
    must_match: list[str] = []
    abbreviation: Optional[str] = None


class IngredientCreate(BaseModel):
    """
    Request model for creating a new ingredient.

    Attributes:
        name: Display name (required)
        category: Category for grouping (required)
        unit: Unit of measurement (default: "piece")
        track_inventory: Enable inventory counting (default: False)
        is_available: Initial availability (default: True)
        aliases: Comma-separated synonyms for matching (optional)
        must_match: Comma-separated strings - at least one must be in input for this to match
        abbreviation: Short form expanded before parsing (e.g., "cc" for "cream cheese")

    Example:
        {
            "name": "Provolone",
            "category": "cheese",
            "unit": "slice",
            "is_available": true,
            "aliases": "prov, provolone cheese"
        }
    """
    name: str
    category: str
    unit: str = "piece"
    track_inventory: bool = False
    is_available: bool = True
    aliases: Optional[str] = None
    must_match: Optional[str] = None
    abbreviation: Optional[str] = None


class IngredientUpdate(BaseModel):
    """
    Request model for updating an ingredient.

    All fields are optional - only provided fields will be updated.

    Attributes:
        name: New display name
        category: New category
        unit: New unit of measurement
        track_inventory: Update inventory tracking
        is_available: Update global availability (to 86 or un-86)
        aliases: Comma-separated synonyms for matching
        must_match: Comma-separated strings - at least one must be in input for this to match
        abbreviation: Short form expanded before parsing (e.g., "cc" for "cream cheese")
    """
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    track_inventory: Optional[bool] = None
    is_available: Optional[bool] = None
    aliases: Optional[str] = None
    must_match: Optional[str] = None
    abbreviation: Optional[str] = None


class IngredientAvailabilityUpdate(BaseModel):
    """
    Simple payload for quickly toggling ingredient availability.

    This is the primary way staff 86/un-86 items during service.
    Designed for quick one-click toggles in the admin UI.

    Attributes:
        is_available: New availability state (True = available, False = 86'd)
        store_id: If provided, updates store-specific availability.
                  If omitted, updates global availability.

    Examples:
        # 86 globally (all stores)
        {"is_available": false}

        # 86 at one store only
        {"is_available": false, "store_id": "store_eb_001"}

        # Un-86 (back in stock)
        {"is_available": true}
    """
    is_available: bool
    store_id: Optional[str] = None


class IngredientStoreAvailabilityOut(BaseModel):
    """
    Response model for ingredient with store-specific availability.

    Like IngredientOut but the is_available field reflects availability
    at a specific store (or global if no store was specified).

    Attributes:
        id: Database primary key
        name: Display name
        category: Type category
        unit: Unit of measurement
        track_inventory: Whether inventory counting is enabled
        is_available: Availability at the queried store (or global)
        aliases: List of synonyms for matching
        must_match: List of strings - at least one must be in input for this to match
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    unit: str
    track_inventory: bool
    is_available: bool
    aliases: list[str] = []
    must_match: list[str] = []


class MenuItemStoreAvailabilityOut(BaseModel):
    """
    Response model for menu item with store-specific availability.

    Used for the menu item availability management endpoints.
    Allows 86'ing entire menu items (not just ingredients).

    Attributes:
        id: Database primary key
        name: Menu item display name
        category: Menu category
        base_price: Item base price
        is_available: Availability at the queried store
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    base_price: float
    is_available: bool


class MenuItemAvailabilityUpdate(BaseModel):
    """
    Payload for toggling menu item availability.

    Similar to IngredientAvailabilityUpdate but for entire menu items.
    Use when a complete dish is unavailable (not just an ingredient).

    Attributes:
        is_available: New availability state
        store_id: If provided, updates store-specific availability

    Example:
        # 86 the Turkey Club at one location
        {"is_available": false, "store_id": "store_eb_001"}
    """
    is_available: bool
    store_id: Optional[str] = None
