"""
Menu Item Category Schemas for Orderbot
============================================

This module defines Pydantic models for menu item categories. Categories
are high-level classifications like "drink" or "food" that menu items
can belong to. A menu item can belong to multiple categories.

Endpoint Coverage:
------------------
- GET /admin/categories: List all categories
- POST /admin/categories: Create a new category
- GET /admin/categories/{id}: Get a specific category
- PUT /admin/categories/{id}: Update a category
- DELETE /admin/categories/{id}: Delete a category

Usage:
------
Categories enable generic item searches like "I want a drink" to return
all items in the "drink" category for disambiguation.
"""

from typing import Optional

from pydantic import BaseModel, Field

from .base import TimestampedModel


class CategoryBase(BaseModel):
    """Base fields for menu item categories."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Display name (e.g., 'Drink', 'Food')"
    )
    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier slug (e.g., 'drink', 'food')"
    )
    description: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional description of the category"
    )


class CategoryCreate(CategoryBase):
    """Request model for creating a new category."""


class CategoryUpdate(BaseModel):
    """
    Request model for updating a category.

    All fields are optional - only provided fields will be updated.
    """
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Display name"
    )
    slug: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    description: Optional[str] = Field(
        None,
        max_length=200,
        description="Optional description"
    )


class CategoryOut(CategoryBase, TimestampedModel):
    """Response model for a category."""

    menu_item_count: int = Field(
        default=0,
        description="Number of menu items in this category"
    )


class CategoryList(BaseModel):
    """Response model for listing categories."""

    categories: list[CategoryOut]
    total: int
