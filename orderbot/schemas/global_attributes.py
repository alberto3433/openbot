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
    ingredient_id: int | None = None
    ingredient_name: str | None = None  # Display name from linked ingredient
    # Modifier category is derived from ingredient.category at runtime
    modifier_category_name: str | None = None  # Display name from linked ingredient's category
    # Option aliases (comma-separated for display, stored in global_attribute_option_aliases table)
    aliases: str | None = None
    # Skip rules - attributes to skip when this option is selected
    skip_rules: list[SkipRuleOutBasic] = []
    # Forward delegation - when user input matches target attribute's options,
    # auto-select this option and forward to target attribute
    forward_to_attribute_id: int | None = None
    forward_to_attribute_slug: str | None = None  # Slug for display
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlobalAttributeOptionCreate(BaseModel):
    """Request model for creating a global attribute option.

    When ingredient_id is provided, slug and display_name are derived from
    the ingredient and should not be sent. When no ingredient is linked,
    slug and display_name are required.
    """
    slug: str | None = None
    display_name: str | None = None
    price_modifier: float = 0.0
    is_default: bool = False
    is_available: bool = True
    display_order: int = 0
    # Link to ingredient (optional) - when set, slug/display_name derived from ingredient
    # modifier_category is also derived from ingredient.category at runtime
    ingredient_id: int | None = None
    # Option aliases (comma-separated string) - stored in global_attribute_option_aliases table
    aliases: str | None = None
    # Forward delegation - target attribute to forward to when input matches its options
    forward_to_attribute_id: int | None = None


class GlobalAttributeOptionUpdate(BaseModel):
    """Request model for updating a global attribute option."""
    slug: str | None = None
    display_name: str | None = None
    price_modifier: float | None = None
    is_default: bool | None = None
    is_available: bool | None = None
    display_order: int | None = None
    # Link to ingredient - when set, must_match/aliases are read from ingredient
    # modifier_category is also derived from ingredient.category at runtime
    # Set to null to unlink
    ingredient_id: int | None = None
    # Option aliases (comma-separated string) - replaces existing aliases
    aliases: str | None = None
    # Forward delegation - target attribute to forward to when input matches its options
    # Set to null to unlink
    forward_to_attribute_id: int | None = None


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
    description: str | None = None
    question_text: str | None = None  # Question to ask user for this attribute
    offer_question_text: str | None = None  # Question when offering at checkpoint
    # Options source category (for package_multi_select input types)
    # Specifies which ingredient category provides the options for this attribute.
    options_source_category: str | None = None
    options: list[GlobalAttributeOptionOut] = []
    # Count of item types using this attribute
    item_type_count: int = 0
    # List of item types using this attribute (for detail view)
    linked_item_types: list[LinkedItemTypeInfo] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlobalAttributeListOut(BaseModel):
    """Response model for listing global attributes (without full options)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    display_name: str
    input_type: str
    description: str | None = None
    question_text: str | None = None
    offer_question_text: str | None = None
    options_source_category: str | None = None
    option_count: int = 0
    item_type_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlobalAttributeCreate(BaseModel):
    """Request model for creating a global attribute."""
    slug: str
    display_name: str
    input_type: str = "single_select"
    description: str | None = None
    question_text: str | None = None
    offer_question_text: str | None = None
    options_source_category: str | None = None


class GlobalAttributeUpdate(BaseModel):
    """Request model for updating a global attribute."""
    slug: str | None = None
    display_name: str | None = None
    input_type: str | None = None
    description: str | None = None
    question_text: str | None = None
    offer_question_text: str | None = None
    options_source_category: str | None = None


# =============================================================================
# Item Type Global Attribute Link Schemas
# =============================================================================

class ItemTypeGlobalAttributeOut(BaseModel):
    """
    Response model for an item type's link to a global attribute.

    Contains item-type-specific settings (is_required, etc.)
    as well as the global attribute and its options.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type_id: int
    item_type_slug: str | None = None
    global_attribute_id: int
    global_attribute_slug: str
    global_attribute_display_name: str
    input_type: str

    # Item-type-specific settings
    display_order: int = 0
    is_required: bool = False
    allow_none: bool = True
    ask_in_conversation: bool = True
    listen_only: bool = False
    min_selections: int | None = None
    max_selections: int | None = None

    # Question text from the global attribute (for convenience)
    question_text: str | None = None
    offer_question_text: str | None = None

    # Subcategory filter for narrowing options per item type
    option_subcategory_filter: str | None = None

    # Options from the global attribute
    options: list[GlobalAttributeOptionOut] = []

    created_at: datetime | None = None
    updated_at: datetime | None = None


class ItemTypeGlobalAttributeLinkCreate(BaseModel):
    """Request model for linking a global attribute to an item type."""
    global_attribute_id: int
    display_order: int = 0
    is_required: bool = False
    allow_none: bool = True
    ask_in_conversation: bool = True
    listen_only: bool = False
    min_selections: int | None = None
    max_selections: int | None = None
    option_subcategory_filter: str | None = None


class ItemTypeGlobalAttributeLinkUpdate(BaseModel):
    """Request model for updating an item type's global attribute link."""
    display_order: int | None = None
    is_required: bool | None = None
    allow_none: bool | None = None
    ask_in_conversation: bool | None = None
    listen_only: bool | None = None
    min_selections: int | None = None
    max_selections: int | None = None
    option_subcategory_filter: str | None = None


# =============================================================================
# Bulk Import/Export Schemas
# =============================================================================

class GlobalAttributeWithOptionsCreate(BaseModel):
    """Request model for creating a global attribute with options in one call."""
    slug: str
    display_name: str
    input_type: str = "single_select"
    description: str | None = None
    question_text: str | None = None
    offer_question_text: str | None = None
    options_source_category: str | None = None
    options: list[GlobalAttributeOptionCreate] = []


# =============================================================================
# Create Option from Ingredient Schema
# =============================================================================

class GlobalAttributeOptionFromIngredientCreate(BaseModel):
    """
    Request model for creating an option from an existing ingredient.

    This reduces duplicate data entry - slug, display_name, and modifier_category
    are auto-populated from the ingredient, and the ingredient_id link is set
    automatically. User only needs to specify price and display order.
    """
    price_modifier: float = 0.0
    display_order: int = 0
    is_default: bool = False
    is_available: bool = True


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
