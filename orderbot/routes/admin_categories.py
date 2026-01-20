"""
Admin Categories Routes for Orderbot
=========================================

This module contains admin endpoints for managing menu item categories.
Categories are high-level classifications (drink, food) that menu items
can belong to. A menu item can belong to multiple categories.

Endpoints:
----------
- GET /admin/categories: List all categories
- POST /admin/categories: Create a new category
- GET /admin/categories/{id}: Get a specific category
- PUT /admin/categories/{id}: Update a category
- DELETE /admin/categories/{id}: Delete a category

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Category, MenuItemCategory
from ..schemas.categories import (
    CategoryCreate,
    CategoryUpdate,
    CategoryOut,
    CategoryList,
)
from .crud_factory import CRUDRouterFactory


def _category_to_out(category: Category, db: Session) -> CategoryOut:
    """Convert a Category model to CategoryOut with menu_item_count."""
    menu_item_count = db.query(MenuItemCategory).filter(
        MenuItemCategory.category_id == category.id
    ).count()

    return CategoryOut(
        id=category.id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        created_at=category.created_at,
        menu_item_count=menu_item_count,
    )


def _build_create_kwargs(payload: CategoryCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload with normalization."""
    slug = payload.slug.lower().strip()
    name = payload.name.strip()

    # Check for duplicate name (factory only handles slug)
    existing_name = db.query(Category).filter(Category.name == name).first()
    if existing_name:
        raise HTTPException(
            status_code=400,
            detail=f"A category with name '{name}' already exists"
        )

    return {
        "name": name,
        "slug": slug,
        "description": payload.description.strip() if payload.description else None,
    }


def _handle_before_update(
    item: Category,
    payload: CategoryUpdate,
    db: Session,
) -> None:
    """Apply update payload to item with custom validation."""
    if payload.slug is not None:
        item.slug = payload.slug.lower().strip()

    if payload.name is not None:
        new_name = payload.name.strip()
        # Check for duplicate name (excluding self)
        existing = db.query(Category).filter(
            Category.name == new_name,
            Category.id != item.id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A category with name '{new_name}' already exists"
            )
        item.name = new_name

    if payload.description is not None:
        item.description = payload.description.strip() if payload.description else None


def _handle_before_delete(item: Category, db: Session) -> None:
    """Check if category can be deleted."""
    menu_item_count = db.query(MenuItemCategory).filter(
        MenuItemCategory.category_id == item.id
    ).count()

    if menu_item_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category '{item.name}' - it has {menu_item_count} menu items assigned"
        )


def _build_list_response(
    items: list[CategoryOut],
    total: int,
) -> CategoryList:
    """Build list response wrapper."""
    return CategoryList(categories=items, total=total)


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=Category,
    create_schema=CategoryCreate,
    update_schema=CategoryUpdate,
    response_schema=CategoryOut,
    prefix="/admin/categories",
    tags=["Admin - Categories"],
    id_param="category_id",
    not_found_message="Category not found",
    unique_fields=["slug"],
    order_by=["name"],
    to_response=_category_to_out,
    on_before_create=_build_create_kwargs,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
    list_response_schema=CategoryList,
    list_response_builder=_build_list_response,
)

# Export the router
admin_categories_router = _crud.router
