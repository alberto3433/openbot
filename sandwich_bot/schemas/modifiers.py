"""
Modifier Schemas for Sandwich Bot
==================================

This module defines Pydantic models for the menu configuration system,
including Item Types, Attribute Definitions, and Attribute Options. This
system allows flexible configuration of what options are available for
different types of menu items.

Endpoint Coverage:
------------------
Item Types:
- GET /admin/modifiers/item-types: List all item types
- POST /admin/modifiers/item-types: Create item type
- GET /admin/modifiers/item-types/{id}: Get item type details
- PUT /admin/modifiers/item-types/{id}: Update item type
- DELETE /admin/modifiers/item-types/{id}: Delete item type

Attribute Definitions:
- POST /admin/modifiers/item-types/{id}/attributes: Add attribute to type
- PUT /admin/modifiers/attributes/{id}: Update attribute
- DELETE /admin/modifiers/attributes/{id}: Delete attribute

Attribute Options:
- POST /admin/modifiers/attributes/{id}/options: Add option to attribute
- PUT /admin/modifiers/options/{id}: Update option
- DELETE /admin/modifiers/options/{id}: Delete option

Hierarchical Structure:
-----------------------
The modifier system has three levels:

1. **Item Type** (e.g., "Bagel", "Sandwich", "Coffee")
   - Defines a category of configurable items
   - Links to menu items via MenuItem.item_type_id
   - Contains attribute definitions

2. **Attribute Definition** (e.g., "Size", "Bread", "Milk")
   - Defines a configurable aspect of the item type
   - Specifies input type (single select, multi select)
   - Contains options to choose from

3. **Attribute Option** (e.g., "Small", "Medium", "Large")
   - Individual choices for an attribute
   - Can have price modifiers (+$1 for large)
   - Can be marked as default or unavailable

Example Structure:
------------------
```
Item Type: "Bagel"
├── Attribute: "Size"
│   ├── Option: "Regular" (default, +$0)
│   └── Option: "Mini" (+$0)
├── Attribute: "Spread"
│   ├── Option: "Plain Cream Cheese" (+$2)
│   ├── Option: "Veggie Cream Cheese" (+$2.50)
│   └── Option: "Butter" (+$0.50)
└── Attribute: "Toasted"
    ├── Option: "Yes"
    └── Option: "No" (default)
```

Input Types:
------------
- "single_select": Customer picks exactly one option
- "multi_select": Customer can pick multiple options
- "boolean": Yes/no toggle (like "toasted")

Configurability:
----------------
- is_configurable: If True, chatbot asks about attributes
- skip_config: If True, skip configuration (pre-configured items)

Usage:
------
    # Create a coffee item type with size attribute
    coffee_type = ItemTypeCreate(
        slug="coffee",
        display_name="Coffee",
        is_configurable=True
    )

    # Add size attribute
    size_attr = AttributeDefinitionCreate(
        slug="size",
        display_name="Size",
        input_type="single_select",
        is_required=True
    )

    # Add size options with price modifiers
    small = AttributeOptionCreate(slug="small", display_name="Small", price_modifier=0)
    medium = AttributeOptionCreate(slug="medium", display_name="Medium", price_modifier=0.50)
    large = AttributeOptionCreate(slug="large", display_name="Large", price_modifier=1.00)
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Attribute Option Schemas
# =============================================================================

class AttributeOptionOut(BaseModel):
    """
    Response model for an attribute option.

    Options are the individual choices within an attribute
    (e.g., "Small", "Medium", "Large" for a Size attribute).

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "medium")
        display_name: Human-readable name (e.g., "Medium")
        price_modifier: Price adjustment when selected (e.g., 0.50)
        is_default: Whether this is pre-selected
        is_available: Whether option is currently available
        display_order: Sort order for display
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    price_modifier: float
    is_default: bool
    is_available: bool
    display_order: int


class AttributeOptionCreate(BaseModel):
    """
    Request model for creating an attribute option.

    Attributes:
        slug: URL-safe identifier (required)
        display_name: Human-readable name (required)
        price_modifier: Price adjustment (default: 0)
        is_default: Pre-select this option (default: False)
        is_available: Option availability (default: True)
        display_order: Sort order (default: 0)

    Example:
        {
            "slug": "large",
            "display_name": "Large (20oz)",
            "price_modifier": 1.00,
            "is_default": false,
            "display_order": 3
        }
    """
    slug: str
    display_name: str
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0


class AttributeOptionUpdate(BaseModel):
    """
    Request model for updating an attribute option.

    All fields optional - only provided fields are updated.

    Attributes:
        slug: New slug
        display_name: New display name
        price_modifier: New price modifier
        is_default: Update default status
        is_available: Update availability
        display_order: New sort order
    """
    slug: Optional[str] = None
    display_name: Optional[str] = None
    price_modifier: Optional[float] = None
    is_default: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None


# =============================================================================
# Attribute Definition Schemas
# =============================================================================

class AttributeDefinitionOut(BaseModel):
    """
    Response model for an attribute definition.

    Attributes define configurable aspects of an item type
    (e.g., "Size", "Bread", "Toppings").

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "size")
        display_name: Human-readable name (e.g., "Size")
        input_type: How user selects (single_select, multi_select)
        is_required: Whether selection is mandatory
        allow_none: Whether "none" is a valid choice
        min_selections: Minimum selections for multi_select
        max_selections: Maximum selections for multi_select
        display_order: Sort order for display
        options: List of available options
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    input_type: str
    is_required: bool
    allow_none: bool
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: int
    options: List[AttributeOptionOut] = []


class AttributeDefinitionCreate(BaseModel):
    """
    Request model for creating an attribute definition.

    Attributes:
        slug: URL-safe identifier (required)
        display_name: Human-readable name (required)
        input_type: Selection type (default: single_select)
        is_required: Require selection (default: True)
        allow_none: Allow "none" choice (default: False)
        min_selections: Min for multi_select
        max_selections: Max for multi_select
        display_order: Sort order (default: 0)

    Example:
        {
            "slug": "toppings",
            "display_name": "Toppings",
            "input_type": "multi_select",
            "is_required": false,
            "min_selections": 0,
            "max_selections": 5,
            "display_order": 3
        }
    """
    slug: str
    display_name: str
    input_type: str = "single_select"
    is_required: bool = True
    allow_none: bool = False
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: int = 0


class AttributeDefinitionUpdate(BaseModel):
    """
    Request model for updating an attribute definition.

    All fields optional - only provided fields are updated.

    Attributes:
        slug: New slug
        display_name: New display name
        input_type: New input type
        is_required: Update required status
        allow_none: Update allow_none
        min_selections: New minimum
        max_selections: New maximum
        display_order: New sort order
    """
    slug: Optional[str] = None
    display_name: Optional[str] = None
    input_type: Optional[str] = None
    is_required: Optional[bool] = None
    allow_none: Optional[bool] = None
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: Optional[int] = None


# =============================================================================
# Item Type Schemas
# =============================================================================

class ItemTypeOut(BaseModel):
    """
    Response model for an item type.

    Item types define categories of configurable menu items
    (e.g., "Bagel", "Sandwich", "Coffee").

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "bagel")
        display_name: Human-readable name (e.g., "Bagel")
        is_configurable: Whether items need configuration
        skip_config: Skip configuration dialog
        attribute_definitions: List of configurable attributes
        menu_item_count: Number of menu items using this type
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    is_configurable: bool
    skip_config: bool = False
    attribute_definitions: List[AttributeDefinitionOut] = []
    menu_item_count: int = 0


class ItemTypeCreate(BaseModel):
    """
    Request model for creating an item type.

    Attributes:
        slug: URL-safe identifier (required)
        display_name: Human-readable name (required)
        is_configurable: Enable configuration (default: True)
        skip_config: Skip config dialog (default: False)

    Example:
        {
            "slug": "specialty_drink",
            "display_name": "Specialty Drink",
            "is_configurable": true
        }
    """
    slug: str
    display_name: str
    is_configurable: bool = True
    skip_config: bool = False


class ItemTypeUpdate(BaseModel):
    """
    Request model for updating an item type.

    All fields optional - only provided fields are updated.

    Attributes:
        slug: New slug
        display_name: New display name
        is_configurable: Update configurability
        skip_config: Update skip_config flag
    """
    slug: Optional[str] = None
    display_name: Optional[str] = None
    is_configurable: Optional[bool] = None
    skip_config: Optional[bool] = None
