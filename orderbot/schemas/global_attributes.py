"""
Global Attributes Schemas for Orderbot
===========================================

This module defines Pydantic models for managing global (normalized) attributes
that are shared across item types.

Tables Covered:
---------------
- global_attributes: Master list of attribute definitions shared across item types
- global_attribute_options: Options for each global attribute
- item_type_global_attributes: Links item types to global attributes with per-type settings

Endpoint Coverage:
------------------
- GET/POST/PUT/DELETE /admin/global-attributes: Manage global attribute definitions
- GET/POST/PUT/DELETE /admin/global-attributes/{id}/options: Manage attribute options
- GET/POST/DELETE /admin/item-types/{id}/global-attributes: Link/unlink global attributes
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Global Attribute Option Schemas
# =============================================================================

class SkipRuleOutBasic(BaseModel):
    """Basic response model for skip rules (used within GlobalAttributeOptionOut)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    skipped_attribute_id: int
    skipped_attribute_slug: str
    skipped_attribute_name: str


class GlobalAttributeOptionOut(BaseModel):
    """Response model for global attribute options."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0
    # Link to ingredient for normalized must_match/aliases lookup
    ingredient_id: Optional[int] = None
    ingredient_name: Optional[str] = None  # Display name from linked ingredient
    # Link to modifier category for sub-categorization within an attribute
    modifier_category_id: Optional[int] = None
    modifier_category_name: Optional[str] = None  # Display name from linked category
    # Option aliases (comma-separated for display, stored in global_attribute_option_aliases table)
    aliases: Optional[str] = None
    # Skip rules - attributes to skip when this option is selected
    skip_rules: List[SkipRuleOutBasic] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GlobalAttributeOptionCreate(BaseModel):
    """Request model for creating a global attribute option.

    When ingredient_id is provided, slug and display_name are derived from
    the ingredient and should not be sent. When no ingredient is linked,
    slug and display_name are required.
    """
    slug: Optional[str] = None
    display_name: Optional[str] = None
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0
    # Link to ingredient (optional) - when set, slug/display_name derived from ingredient
    ingredient_id: Optional[int] = None
    # Link to modifier category for sub-categorization (e.g., milks within coffee_additions)
    modifier_category_id: Optional[int] = None
    # Option aliases (comma-separated string) - stored in global_attribute_option_aliases table
    aliases: Optional[str] = None


class GlobalAttributeOptionUpdate(BaseModel):
    """Request model for updating a global attribute option."""
    slug: Optional[str] = None
    display_name: Optional[str] = None
    price_modifier: Optional[float] = None
    is_default: Optional[bool] = None
    is_available: Optional[bool] = None
    display_order: Optional[int] = None
    # Link to ingredient - when set, must_match/aliases are read from ingredient
    # Set to null to unlink
    ingredient_id: Optional[int] = None
    # Link to modifier category for sub-categorization
    # Set to null to unlink
    modifier_category_id: Optional[int] = None
    # Option aliases (comma-separated string) - replaces existing aliases
    aliases: Optional[str] = None


# =============================================================================
# Linked Item Type Info (for displaying which item types use an attribute)
# =============================================================================

class LinkedItemTypeInfo(BaseModel):
    """Basic info about an item type that uses a global attribute."""
    id: int
    slug: str
    display_name: str


# =============================================================================
# Global Attribute Schemas
# =============================================================================

class GlobalAttributeOut(BaseModel):
    """
    Response model for global attributes.

    Global attributes are shared across item types. For example, a 'spread'
    attribute with all cream cheese options can be used by fish_sandwich,
    egg_sandwich, and bagel item types.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    input_type: str  # 'single_select', 'multi_select', 'boolean'
    description: Optional[str] = None
    options: List[GlobalAttributeOptionOut] = []
    # Count of item types using this attribute
    item_type_count: int = 0
    # List of item types using this attribute (for detail view)
    linked_item_types: List[LinkedItemTypeInfo] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GlobalAttributeListOut(BaseModel):
    """Response model for listing global attributes (without full options)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    input_type: str
    description: Optional[str] = None
    option_count: int = 0
    item_type_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class GlobalAttributeCreate(BaseModel):
    """Request model for creating a global attribute."""
    slug: str
    display_name: str
    input_type: str = "single_select"
    description: Optional[str] = None


class GlobalAttributeUpdate(BaseModel):
    """Request model for updating a global attribute."""
    slug: Optional[str] = None
    display_name: Optional[str] = None
    input_type: Optional[str] = None
    description: Optional[str] = None


# =============================================================================
# Item Type Global Attribute Link Schemas
# =============================================================================

class ItemTypeGlobalAttributeOut(BaseModel):
    """
    Response model for an item type's link to a global attribute.

    Contains item-type-specific settings (question_text, is_required, etc.)
    as well as the global attribute and its options.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type_id: int
    item_type_slug: Optional[str] = None
    global_attribute_id: int
    global_attribute_slug: str
    global_attribute_display_name: str
    input_type: str

    # Item-type-specific settings
    display_order: int = 0
    is_required: bool = False
    allow_none: bool = True
    ask_in_conversation: bool = True
    question_text: Optional[str] = None
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None

    # Options from the global attribute
    options: List[GlobalAttributeOptionOut] = []

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ItemTypeGlobalAttributeLinkCreate(BaseModel):
    """Request model for linking a global attribute to an item type."""
    global_attribute_id: int
    display_order: int = 0
    is_required: bool = False
    allow_none: bool = True
    ask_in_conversation: bool = True
    question_text: Optional[str] = None
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None


class ItemTypeGlobalAttributeLinkUpdate(BaseModel):
    """Request model for updating an item type's global attribute link."""
    display_order: Optional[int] = None
    is_required: Optional[bool] = None
    allow_none: Optional[bool] = None
    ask_in_conversation: Optional[bool] = None
    question_text: Optional[str] = None
    min_selections: Optional[int] = None
    max_selections: Optional[int] = None


# =============================================================================
# Bulk Import/Export Schemas
# =============================================================================

class GlobalAttributeWithOptionsCreate(BaseModel):
    """Request model for creating a global attribute with options in one call."""
    slug: str
    display_name: str
    input_type: str = "single_select"
    description: Optional[str] = None
    options: List[GlobalAttributeOptionCreate] = []


# =============================================================================
# Create Option from Ingredient Schema
# =============================================================================

class GlobalAttributeOptionFromIngredientCreate(BaseModel):
    """
    Request model for creating an option from an existing ingredient.

    This reduces duplicate data entry - slug and display_name are auto-populated
    from the ingredient, and the ingredient_id link is set automatically.
    User only needs to specify price and display order.
    """
    price_modifier: float = 0.0
    display_order: int = 0
    is_default: bool = False
    is_available: bool = True
    modifier_category_id: Optional[int] = None


# =============================================================================
# Skip Rule Schemas
# =============================================================================

class SkipRuleOut(BaseModel):
    """Response model for skip rules attached to an option."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    skipped_attribute_id: int
    skipped_attribute_slug: str
    skipped_attribute_name: str


class SkipRuleCreate(BaseModel):
    """Request model for creating a skip rule."""
    skipped_attribute_id: int
