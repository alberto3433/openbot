"""
Menu Item Schemas for Sandwich Bot
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
1. **Categories**: Group items for display (sandwiches, drinks, sides, etc.)

2. **Signature Items**: Pre-configured items on the "speed menu" that can be
   ordered by name without customization (e.g., "The Italian", "Classic BLT").

3. **Item Types**: Link to ItemType for configurable items. Determines what
   attributes (bread, size, toppings) are available for customization.

4. **Base Price**: Starting price before any modifiers. Actual price may vary
   based on size, add-ons, and other attribute selections.

5. **Metadata**: Flexible JSON field for additional item data like description,
   default configuration, allergen info, etc.

6. **Available Qty**: Legacy inventory field (kept for compatibility).
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
        category="sandwiches",
        is_signature=True,
        base_price=12.99,
        metadata={"description": "Triple-decker turkey sandwich"}
    )

    # Response will include the generated ID
    new_item = MenuItemOut.model_validate(db_item)
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class MenuItemOut(BaseModel):
    """
    Response model for menu item data.

    Used when returning menu item information from the API.
    Can be created directly from SQLAlchemy MenuItem objects.

    Attributes:
        id: Database primary key
        name: Display name (e.g., "Turkey Club")
        category: Grouping category (e.g., "sandwiches", "drinks")
        is_signature: Whether this is a pre-configured signature item
        base_price: Starting price in dollars
        available_qty: Legacy inventory count (use 86 system instead)
        metadata: Additional item data (description, defaults, etc.)
        item_type_id: Foreign key to ItemType for configuration options
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    is_signature: bool
    base_price: float
    available_qty: int
    metadata: Dict[str, Any]
    item_type_id: Optional[int] = None


class MenuItemCreate(BaseModel):
    """
    Request model for creating a new menu item.

    All fields except name, category, and base_price have sensible defaults.

    Attributes:
        name: Display name (required, must be unique within category)
        category: Grouping category (required)
        is_signature: Whether this is a signature item (default: False)
        base_price: Starting price in dollars (required)
        available_qty: Legacy inventory count (default: 0)
        metadata: Additional item data (default: empty dict)
        item_type_id: Link to ItemType for configuration (optional)

    Example:
        {
            "name": "Veggie Delight",
            "category": "sandwiches",
            "is_signature": true,
            "base_price": 10.99,
            "metadata": {
                "description": "Fresh vegetables on your choice of bread",
                "vegetarian": true
            }
        }
    """
    name: str
    category: str
    is_signature: bool = False
    base_price: float
    available_qty: int = 0
    metadata: Dict[str, Any] = {}
    item_type_id: Optional[int] = None


class MenuItemUpdate(BaseModel):
    """
    Request model for updating a menu item.

    All fields are optional - only provided fields will be updated.
    This supports partial updates (PATCH semantics) even on PUT endpoints.

    Attributes:
        name: New display name (optional)
        category: New category (optional)
        is_signature: Update signature status (optional)
        base_price: New base price (optional)
        available_qty: Update inventory count (optional)
        metadata: Replace metadata dict (optional, replaces entire dict)
        item_type_id: Change linked ItemType (optional)

    Example:
        # Update only the price
        {"base_price": 11.99}

        # Update multiple fields
        {"name": "Super Veggie Delight", "base_price": 12.99}
    """
    name: Optional[str] = None
    category: Optional[str] = None
    is_signature: Optional[bool] = None
    base_price: Optional[float] = None
    available_qty: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    item_type_id: Optional[int] = None
