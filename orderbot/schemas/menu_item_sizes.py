"""
Menu Item Size Pricing Schemas for Orderbot
================================================

This module defines Pydantic models for menu item size-based pricing.
The size pricing system replaces the base_price + upcharge model for
items with size variants (e.g., small/large coffee, 1/4 lb/1/2 lb deli).

Tables:
-------
- menu_item_size_categories: Categories like 'size', 'weight', 'quantity'
- menu_item_sizes: Individual sizes like 'small', 'large', '1/4 lb', 'each'
- menu_item_size_prices: Explicit price per menu item per size

Endpoint Coverage:
------------------
Size Categories:
- GET /admin/size-categories: List all size categories
- POST /admin/size-categories: Create a new size category
- PUT /admin/size-categories/{id}: Update a size category
- DELETE /admin/size-categories/{id}: Delete a size category

Sizes:
- GET /admin/sizes: List all sizes (optionally filtered by category)
- POST /admin/sizes: Create a new size
- PUT /admin/sizes/{id}: Update a size
- DELETE /admin/sizes/{id}: Delete a size

Size Prices (managed via menu item endpoints):
- GET /admin/menu-items/{id}/prices: Get size prices for a menu item
- PUT /admin/menu-items/{id}/prices: Update size prices for a menu item
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Size Category Schemas
# =============================================================================

class SizeCategoryBase(BaseModel):
    """Base fields for size categories."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name (e.g., 'Size', 'Weight', 'Quantity')"
    )
    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier slug (e.g., 'size', 'weight', 'quantity')"
    )
    question_text: str | None = Field(
        None,
        max_length=200,
        description="Question to ask customer (e.g., 'What size?', 'How much would you like?')"
    )


class SizeCategoryCreate(SizeCategoryBase):
    """Request model for creating a new size category."""


class SizeCategoryUpdate(BaseModel):
    """
    Request model for updating a size category.

    All fields are optional - only provided fields will be updated.
    """
    name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Display name"
    )
    slug: str | None = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    question_text: str | None = Field(
        None,
        max_length=200,
        description="Question to ask customer"
    )


class SizeCategoryOut(SizeCategoryBase):
    """Response model for a size category."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    created_at: datetime
    size_count: int = Field(
        default=0,
        description="Number of sizes in this category"
    )


class SizeCategoryList(BaseModel):
    """Response model for listing size categories."""

    categories: list[SizeCategoryOut]
    total: int


# =============================================================================
# Size Schemas
# =============================================================================

class SizeBase(BaseModel):
    """Base fields for sizes."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Size name (e.g., 'small', 'large', '1/4 lb', 'each')"
    )
    category_id: int = Field(
        ...,
        description="ID of the size category this size belongs to"
    )
    display_order: int = Field(
        default=0,
        description="Order in which to display this size (lower = first)"
    )


class SizeCreate(SizeBase):
    """Request model for creating a new size."""


class SizeUpdate(BaseModel):
    """
    Request model for updating a size.

    All fields are optional - only provided fields will be updated.
    """
    name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Size name"
    )
    category_id: int | None = Field(
        None,
        description="ID of the size category"
    )
    display_order: int | None = Field(
        None,
        description="Display order"
    )


class SizeOut(BaseModel):
    """Response model for a size."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    company_id: int
    category_id: int
    name: str
    display_order: int
    created_at: datetime
    category_name: str | None = Field(
        None,
        description="Name of the category this size belongs to"
    )
    menu_item_count: int = Field(
        default=0,
        description="Number of menu items using this size"
    )


class SizeList(BaseModel):
    """Response model for listing sizes."""

    sizes: list[SizeOut]
    total: int


# =============================================================================
# Size Price Schemas
# =============================================================================

class SizePriceBase(BaseModel):
    """Base fields for size prices."""

    size_id: int = Field(
        ...,
        description="ID of the size"
    )
    price: float = Field(
        ...,
        ge=0,
        description="Price for this size"
    )


class SizePriceCreate(SizePriceBase):
    """Request model for creating a size price entry."""


class SizePriceUpdate(BaseModel):
    """Request model for updating a size price."""

    price: float = Field(
        ...,
        ge=0,
        description="New price for this size"
    )


class SizePriceOut(BaseModel):
    """Response model for a size price entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    menu_item_id: int
    size_id: int
    price: float
    created_at: datetime
    size_name: str | None = Field(
        None,
        description="Name of the size"
    )
    size_display_order: int | None = Field(
        None,
        description="Display order of the size"
    )


class SizePriceList(BaseModel):
    """Response model for listing size prices for a menu item."""

    menu_item_id: int
    menu_item_name: str
    size_category_id: int | None = None
    size_category_name: str | None = None
    prices: list[SizePriceOut]
    total: int


class SizePriceBulkUpdate(BaseModel):
    """
    Request model for bulk updating size prices for a menu item.

    This replaces all existing size prices with the provided list.
    At least one price entry is required.
    """

    size_category_id: int = Field(
        ...,
        description="ID of the size category for this menu item"
    )
    prices: list[SizePriceCreate] = Field(
        ...,
        min_length=1,
        description="List of size prices (at least one required)"
    )


# =============================================================================
# Combined Schemas for Admin UI
# =============================================================================

class SizeCategoryWithSizes(SizeCategoryOut):
    """Size category with its sizes included."""

    sizes: list[SizeOut] = Field(
        default_factory=list,
        description="Sizes in this category"
    )
