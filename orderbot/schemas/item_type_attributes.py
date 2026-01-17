"""
Item Type Attributes Schemas for Orderbot
==============================================

This module defines Pydantic models for managing item type attributes (the consolidated
schema that replaces item_type_field and attribute_definitions).

Tables Covered:
---------------
- item_type_attributes: Defines what attributes are available for each item type

Endpoint Coverage:
------------------
- GET/POST/PUT/DELETE /admin/item-type-attributes: Manage attribute definitions
"""

from datetime import datetime
from typing import List, Optional

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
