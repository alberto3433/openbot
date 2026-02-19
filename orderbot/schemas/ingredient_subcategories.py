"""
Ingredient Subcategory Schemas for Orderbot
================================================

Pydantic models for ingredient subcategory CRUD operations.
Subcategories group ingredients within a category (e.g., 'bagel' under 'bread').

Endpoint Coverage:
------------------
- GET /admin/ingredient-subcategories: List all (optional ?category_slug= filter)
- POST /admin/ingredient-subcategories: Create
- PUT /admin/ingredient-subcategories/{id}: Update
- DELETE /admin/ingredient-subcategories/{id}: Delete
"""

from pydantic import BaseModel, Field

from .base import FullTimestampedModel


class IngredientSubcategoryBase(BaseModel):
    """Base fields for ingredient subcategories."""

    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable name"
    )
    category_slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Parent category slug"
    )
    display_order: int = Field(
        default=0,
        ge=0,
        description="Order for display in UI (lower = first)"
    )


class IngredientSubcategoryCreate(IngredientSubcategoryBase):
    """Request model for creating a new ingredient subcategory."""


class IngredientSubcategoryUpdate(BaseModel):
    """Request model for updating an ingredient subcategory. All fields optional."""

    slug: str | None = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    display_name: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        description="Human-readable name"
    )
    display_order: int | None = Field(
        None,
        ge=0,
        description="Order for display in UI"
    )


class IngredientSubcategoryOut(IngredientSubcategoryBase, FullTimestampedModel):
    """Response model for an ingredient subcategory."""


class IngredientSubcategoryList(BaseModel):
    """Response model for listing ingredient subcategories."""

    subcategories: list[IngredientSubcategoryOut]
    total: int
