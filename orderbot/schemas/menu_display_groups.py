"""
Menu Display Group Schemas for Orderbot
============================================

This module defines Pydantic models for menu display groups. Display groups
consolidate item types into user-friendly categories for menu listing.

When a user asks "what's on your menu?", we show these 7 groups instead of
25+ granular item types.

Endpoint Coverage:
------------------
- GET /admin/menu-display-groups: List all groups
- POST /admin/menu-display-groups: Create a new group
- GET /admin/menu-display-groups/{id}: Get a specific group
- PUT /admin/menu-display-groups/{id}: Update a group
- DELETE /admin/menu-display-groups/{id}: Delete a group
"""

from typing import Optional

from pydantic import BaseModel, Field

from .base import OrmModel


class MenuDisplayGroupBase(BaseModel):
    """Base fields for menu display groups."""

    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Display name (e.g., 'Breads', 'Sandwiches')"
    )
    slug: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier slug (e.g., 'breads', 'sandwiches')"
    )
    display_order: int = Field(
        default=0,
        ge=0,
        description="Sort order for display (lower numbers appear first)"
    )
    overall_category_id: Optional[int] = Field(
        None,
        description="FK to overall_categories"
    )


class MenuDisplayGroupCreate(MenuDisplayGroupBase):
    """Request model for creating a new menu display group."""
    aliases: list[str] = Field(
        default_factory=list,
        description="List of aliases for this group (e.g., ['alias1', 'alias2', 'alias3'])"
    )


class MenuDisplayGroupUpdate(BaseModel):
    """
    Request model for updating a menu display group.

    All fields are optional - only provided fields will be updated.
    """
    display_name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="Display name"
    )
    slug: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="Unique identifier slug"
    )
    display_order: Optional[int] = Field(
        None,
        ge=0,
        description="Sort order for display"
    )
    overall_category_id: Optional[int] = Field(
        None,
        description="FK to overall_categories"
    )
    aliases: Optional[list[str]] = Field(
        None,
        description="List of aliases (replaces existing aliases if provided)"
    )


class MenuDisplayGroupOut(OrmModel):
    """Response model for a menu display group."""

    id: int
    slug: str
    display_name: str
    display_order: int
    overall_category_id: Optional[int] = Field(
        None,
        description="FK to overall_categories"
    )
    overall_category_name: Optional[str] = Field(
        None,
        description="Display name of the overall category"
    )
    item_type_count: int = Field(
        default=0,
        description="Number of item types in this group"
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="List of aliases for this group"
    )


class MenuDisplayGroupList(BaseModel):
    """Response model for listing menu display groups."""

    groups: list[MenuDisplayGroupOut]
    total: int
