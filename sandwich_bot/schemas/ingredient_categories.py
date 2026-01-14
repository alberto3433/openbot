"""
Ingredient Category Schemas for Sandwich Bot
=============================================

This module defines Pydantic models for ingredient categories. Categories
classify ingredients by type (protein, topping, cheese, etc.) and modifier
type (food vs beverage).

Endpoint Coverage:
------------------
- GET /admin/ingredient-categories: List all categories
- POST /admin/ingredient-categories: Create a new category
- PUT /admin/ingredient-categories/{id}: Update a category
- DELETE /admin/ingredient-categories/{id}: Delete a category

Modifier Types:
---------------
Categories are classified by how they're used:
- **food**: Modifiers for food items (bagels, sandwiches, omelettes)
  Examples: protein, topping, sauce, cheese, spread
- **beverage**: Modifiers for beverages (coffee, tea)
  Examples: milk, sweetener, syrup
- **None**: Not a modifier (used for item types, not customizations)
  Examples: bread
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Valid modifier type values
ModifierType = Literal["food", "beverage"]


class IngredientCategoryBase(BaseModel):
    """Base fields for ingredient categories."""

    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier slug (e.g., 'protein', 'topping')"
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Human-readable name (e.g., 'Proteins', 'Toppings')"
    )
    modifier_type: Optional[ModifierType] = Field(
        None,
        description="How this category is used: 'food', 'beverage', or null"
    )
    display_order: int = Field(
        default=0,
        ge=0,
        description="Order for display in UI (lower = first)"
    )


class IngredientCategoryCreate(IngredientCategoryBase):
    """Request model for creating a new ingredient category."""
    pass


class IngredientCategoryUpdate(BaseModel):
    """
    Request model for updating an ingredient category.

    All fields are optional - only provided fields will be updated.
    """
    slug: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    display_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Human-readable name"
    )
    modifier_type: Optional[str] = Field(
        None,
        description="How this category is used: 'food', 'beverage', or empty string for null"
    )
    display_order: Optional[int] = Field(
        None,
        ge=0,
        description="Order for display in UI"
    )


class IngredientCategoryOut(IngredientCategoryBase):
    """Response model for an ingredient category."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class IngredientCategoryList(BaseModel):
    """Response model for listing ingredient categories."""

    categories: list[IngredientCategoryOut]
    total: int
