"""
Item Type Attributes Schemas for Sandwich Bot
==============================================

This module defines Pydantic models for managing item type attributes (the consolidated
schema that replaces item_type_field and attribute_definitions) and menu item attribute
values (per-menu-item configuration).

Tables Covered:
---------------
- item_type_attributes: Defines what attributes are available for each item type
- menu_item_attribute_values: Stores per-menu-item configuration values
- menu_item_attribute_selections: Join table for multi-select values

Endpoint Coverage:
------------------
- GET/POST/PUT/DELETE /admin/item-type-attributes: Manage attribute definitions
- GET/PUT /admin/menu/{id}/attributes: Get/set menu item attribute values
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Item Type Attribute Schemas (Type-level definitions)
# =============================================================================

class AttributeOptionOut(BaseModel):
    """Response model for attribute options."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: Optional[str] = None
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0
    # For ingredient-based options
    ingredient_id: Optional[int] = None
    ingredient_name: Optional[str] = None


class AttributeOptionCreate(BaseModel):
    """Request model for creating an attribute option."""
    slug: str
    display_name: Optional[str] = None
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0


class AttributeOptionUpdate(BaseModel):
    """Request model for updating an attribute option."""
    slug: Optional[str] = None
    display_name: Optional[str] = None
    price_modifier: Optional[float] = None
    is_default: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None


class ItemTypeAttributeOut(BaseModel):
    """
    Response model for item type attributes.

    Attributes define what configuration options are available for an item type.
    For example, 'egg_sandwich' might have attributes: bread, protein, cheese, toppings.

    When loads_from_ingredients=True, options come from the item_type_ingredients table
    joined to ingredients, instead of from attribute_options.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type_id: int
    item_type_slug: Optional[str] = None
    slug: str
    display_name: Optional[str] = None
    input_type: str  # 'single_select', 'multi_select', 'boolean', 'text'
    is_required: bool = False
    allow_none: bool = True
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: int = 0
    ask_in_conversation: bool = True
    question_text: Optional[str] = None
    # Ingredient integration
    loads_from_ingredients: bool = False
    ingredient_group: Optional[str] = None
    options: List[AttributeOptionOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ItemTypeAttributeCreate(BaseModel):
    """Request model for creating an item type attribute."""
    item_type_id: int
    slug: str
    display_name: Optional[str] = None
    input_type: str = "single_select"
    is_required: bool = False
    allow_none: bool = True
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: int = 0
    ask_in_conversation: bool = True
    question_text: Optional[str] = None


class ItemTypeAttributeUpdate(BaseModel):
    """Request model for updating an item type attribute."""
    slug: Optional[str] = None
    display_name: Optional[str] = None
    input_type: Optional[str] = None
    is_required: Optional[bool] = None
    allow_none: Optional[bool] = None
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None
    display_order: Optional[int] = None
    ask_in_conversation: Optional[bool] = None
    question_text: Optional[str] = None


# =============================================================================
# Menu Item Attribute Value Schemas (Instance-level values)
# =============================================================================

class MenuItemAttributeValueOut(BaseModel):
    """
    Response model for a single attribute value on a menu item.

    Represents the value of one attribute for a specific menu item.
    For example, The Lexington's 'bread' attribute has value 'Bagel'.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    attribute_id: int
    attribute_slug: str
    attribute_display_name: Optional[str] = None
    input_type: str

    # The actual value (one of these will be set based on input_type)
    option_id: Optional[int] = None
    option_display_name: Optional[str] = None
    value_boolean: Optional[bool] = None
    value_text: Optional[str] = None

    # For multi_select, list of selected options
    selected_options: List[AttributeOptionOut] = []

    # Whether to still ask user even with a default value
    still_ask: bool = False


class MenuItemAttributeValueUpdate(BaseModel):
    """
    Request model for updating a single attribute value.

    Set the appropriate value field based on the attribute's input_type:
    - single_select: set option_id
    - multi_select: set selected_option_ids
    - boolean: set value_boolean
    - text: set value_text
    """
    option_id: Optional[int] = None
    selected_option_ids: Optional[List[int]] = None
    value_boolean: Optional[bool] = None
    value_text: Optional[str] = None
    still_ask: Optional[bool] = None


class MenuItemAttributesOut(BaseModel):
    """
    Response model for all attribute values on a menu item.

    Used by GET /admin/menu/{id}/attributes to return all configured
    attribute values for a menu item.
    """
    menu_item_id: int
    menu_item_name: str
    item_type_slug: Optional[str] = None
    attributes: List[MenuItemAttributeValueOut] = []


class MenuItemAttributesUpdate(BaseModel):
    """
    Request model for bulk updating menu item attributes.

    Allows setting multiple attribute values in a single request.
    Keys are attribute slugs, values are the attribute value data.

    Example:
        {
            "attributes": {
                "bread": {"option_id": 5, "still_ask": true},
                "protein": {"option_id": 12, "still_ask": false},
                "toppings": {"selected_option_ids": [20, 21, 22]},
                "toasted": {"value_boolean": true}
            }
        }
    """
    attributes: Dict[str, MenuItemAttributeValueUpdate]


# =============================================================================
# Combined schemas for form-based editing
# =============================================================================

class AttributeFormField(BaseModel):
    """
    Schema for rendering an attribute as a form field in the admin UI.

    Includes all information needed to render the appropriate form control
    (select, multi-select, checkbox, text input) with current value.
    """
    attribute_id: int
    slug: str
    display_name: Optional[str] = None
    input_type: str
    is_required: bool = False
    allow_none: bool = True
    question_text: Optional[str] = None

    # Available options (for select types)
    options: List[AttributeOptionOut] = []

    # Current value
    current_option_id: Optional[int] = None
    current_option_ids: List[int] = []  # For multi_select
    current_boolean: Optional[bool] = None
    current_text: Optional[str] = None

    # Whether to still ask in conversation
    still_ask: bool = False


class MenuItemEditForm(BaseModel):
    """
    Complete form data for editing a menu item's attributes.

    Used to populate the admin edit form with all attributes
    and their current values.
    """
    menu_item_id: int
    menu_item_name: str
    item_type_id: Optional[int] = None
    item_type_slug: Optional[str] = None
    fields: List[AttributeFormField] = []


# =============================================================================
# Ingredient Link Schemas (for loads_from_ingredients=True attributes)
# =============================================================================

class IngredientLinkCreate(BaseModel):
    """Request model for linking an ingredient to an attribute."""
    ingredient_id: int
    price_modifier: float = 0.0
    display_name_override: Optional[str] = None
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0


class IngredientLinkUpdate(BaseModel):
    """Request model for updating an ingredient link."""
    price_modifier: Optional[float] = None
    display_name_override: Optional[str] = None
    is_default: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None


class AvailableIngredientOut(BaseModel):
    """Response model for ingredients available to link."""
    id: int
    name: str
    slug: str
    category: str
    is_available: bool = True
