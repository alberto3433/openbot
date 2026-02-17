"""
Modifier Schemas for Orderbot
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
    slug: str | None = None
    display_name: str | None = None
    price_modifier: float | None = None
    is_default: bool | None = None
    is_available: bool | None = None
    display_order: int | None = None


# =============================================================================
# Item Type Schemas
# =============================================================================

# =============================================================================
# Global Attribute Reference (for ItemTypeOut)
# =============================================================================

class GlobalAttributeRef(BaseModel):
    """
    Lightweight reference to a global attribute linked to an item type.

    Used in ItemTypeOut to show which global attributes are linked without
    including full option details.

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "bread", "size")
        display_name: Human-readable name (e.g., "Bread", "Size")
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str


# =============================================================================
# Overall Category Schemas
# =============================================================================

class OverallCategoryOut(BaseModel):
    """
    Response model for an overall category.

    Categories group item types and ingredient categories by modifier extraction rules
    (e.g., "food" vs "beverage").

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "food", "beverage")
        display_name: Human-readable name (e.g., "Food", "Beverage")
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str


class OverallCategoryAdminOut(BaseModel):
    """Response model for overall category admin CRUD (maps display_name to name)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    description: str | None = None
    menu_item_count: int = 0


class OverallCategoryAdminCreate(BaseModel):
    """Create payload for overall category."""
    name: str
    slug: str
    description: str | None = None


class OverallCategoryAdminUpdate(BaseModel):
    """Update payload for overall category."""
    name: str | None = None
    slug: str | None = None
    description: str | None = None


class OverallCategoryAdminList(BaseModel):
    """List response for overall categories."""
    categories: list[OverallCategoryAdminOut]
    total: int


# =============================================================================
# Item Type Schemas
# =============================================================================

class ItemTypeListOut(BaseModel):
    """
    Lightweight response model for item type list (sidebar).

    Returns essential fields plus counts for fast loading using
    efficient aggregated queries.

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "bagel")
        display_name: Human-readable name (e.g., "Bagel")
        menu_item_count: Number of menu items using this type
        global_attribute_count: Number of linked global attributes
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    menu_item_count: int = 0
    global_attribute_count: int = 0


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
        menu_display_group_id: FK to menu_display_groups table (required)
        menu_display_group_name: Display name of the group (e.g., "Breads")
        overall_category_name: Category inherited from display group (e.g., "Food")
        menu_item_count: Number of menu items using this type
        global_attribute_count: Number of linked global attributes
        global_attributes: List of linked global attributes (slug and display_name)
        aliases: List of synonyms for matching (e.g., ["coffee", "java"])
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    is_configurable: bool
    skip_config: bool = False
    menu_display_group_id: int
    menu_display_group_name: str
    overall_category_name: str | None = None  # Inherited from display group
    menu_item_count: int = 0
    global_attribute_count: int = 0
    global_attributes: list[GlobalAttributeRef] = []
    aliases: list[str] = []


class ItemTypeCreate(BaseModel):
    """
    Request model for creating an item type.

    Note: is_configurable and skip_config are derived from linked global
    attributes and cannot be set directly.

    The overall category (food vs beverage) is inherited from the display group.

    Attributes:
        slug: URL-safe identifier (required)
        display_name: Human-readable name (required)
        menu_display_group_id: FK to menu_display_groups table (required)
        aliases: Comma-separated synonyms for matching (optional)

    Example:
        {
            "slug": "specialty_drink",
            "display_name": "Specialty Drink",
            "menu_display_group_id": 4,
            "aliases": "fancy drink, gourmet beverage"
        }
    """
    slug: str
    display_name: str
    menu_display_group_id: int
    aliases: str | None = None  # Comma-separated aliases


class ItemTypeUpdate(BaseModel):
    """
    Request model for updating an item type.

    All fields optional - only provided fields are updated.

    Note: is_configurable and skip_config are derived from linked global
    attributes and cannot be set directly.

    The overall category (food vs beverage) is inherited from the display group.

    Attributes:
        slug: New slug
        display_name: New display name
        menu_display_group_id: FK to menu_display_groups table
        aliases: Comma-separated synonyms for matching
    """
    slug: str | None = None
    display_name: str | None = None
    menu_display_group_id: int | None = None
    aliases: str | None = None  # Comma-separated aliases


# =============================================================================
# Modifier Category Schemas
# =============================================================================

class ModifierCategoryOut(BaseModel):
    """
    Response model for a modifier category.

    Modifier categories define groups of add-ons/modifiers that customers
    can ask about (e.g., "what sweeteners do you have?").

    Attributes:
        id: Database primary key
        slug: URL-safe identifier (e.g., "sweeteners")
        display_name: Human-readable name (e.g., "Sweeteners")
        aliases: List of keywords that trigger this category
        description: Static response text for small categories
        prompt_suffix: Question to ask after listing options
        loads_from_ingredients: If True, options are loaded from Ingredient table
        ingredient_category: Category value in Ingredient table (if loads_from_ingredients)
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    aliases: list[str] = []
    description: str | None = None
    prompt_suffix: str | None = None
    loads_from_ingredients: bool = False
    ingredient_category: str | None = None


class ModifierCategoryCreate(BaseModel):
    """
    Request model for creating a modifier category.

    Attributes:
        slug: URL-safe identifier (required)
        display_name: Human-readable name (required)
        aliases: Comma-separated keywords (e.g., "sweetener, sugar, sugars")
        description: Static response text (for small fixed lists)
        prompt_suffix: Question after listing (default: "What would you like?")
        loads_from_ingredients: Load options from Ingredient table (default: False)
        ingredient_category: Ingredient.category value (if loads_from_ingredients)

    Example (static category):
        {
            "slug": "sweeteners",
            "display_name": "Sweeteners",
            "aliases": "sweetener, sweeteners, sugar, sugars",
            "description": "We have sugar, raw sugar, honey, Equal, Splenda, and Stevia.",
            "prompt_suffix": "Would you like any of these in your drink?",
            "loads_from_ingredients": false
        }

    Example (database-backed category):
        {
            "slug": "toppings",
            "display_name": "Toppings",
            "aliases": "topping, toppings, bagel topping",
            "prompt_suffix": "What would you like on your bagel?",
            "loads_from_ingredients": true,
            "ingredient_category": "topping"
        }
    """
    slug: str
    display_name: str
    aliases: str | None = None
    description: str | None = None
    prompt_suffix: str = "What would you like?"
    loads_from_ingredients: bool = False
    ingredient_category: str | None = None


class ModifierCategoryUpdate(BaseModel):
    """
    Request model for updating a modifier category.

    All fields optional - only provided fields are updated.

    Attributes:
        slug: New slug
        display_name: New display name
        aliases: New comma-separated keywords
        description: New static response text
        prompt_suffix: New question text
        loads_from_ingredients: Update database-backed flag
        ingredient_category: New ingredient category
    """
    slug: str | None = None
    display_name: str | None = None
    aliases: str | None = None
    description: str | None = None
    prompt_suffix: str | None = None
    loads_from_ingredients: bool | None = None
    ingredient_category: str | None = None
