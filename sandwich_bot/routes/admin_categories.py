"""
Admin Categories Routes for Sandwich Bot
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

Usage:
------
    # Add a new category
    POST /admin/categories
    {
        "name": "Dessert",
        "slug": "dessert",
        "description": "Sweet treats and pastries"
    }

    # Update a category
    PUT /admin/categories/3
    {
        "description": "Updated description"
    }
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import Category, MenuItemCategory
from ..schemas.categories import (
    CategoryCreate,
    CategoryUpdate,
    CategoryOut,
    CategoryList,
)


logger = logging.getLogger(__name__)

# Router definition
admin_categories_router = APIRouter(
    prefix="/admin/categories",
    tags=["Admin - Categories"]
)


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


# =============================================================================
# Category Endpoints
# =============================================================================

@admin_categories_router.get("", response_model=CategoryList)
def list_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CategoryList:
    """List all menu item categories."""
    categories = db.query(Category).order_by(Category.name).all()

    return CategoryList(
        categories=[_category_to_out(c, db) for c in categories],
        total=len(categories)
    )


@admin_categories_router.post("", response_model=CategoryOut, status_code=201)
def create_category(
    payload: CategoryCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CategoryOut:
    """Create a new category."""
    # Check for duplicate slug
    slug = payload.slug.lower().strip()
    existing = db.query(Category).filter(Category.slug == slug).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A category with slug '{slug}' already exists"
        )

    # Check for duplicate name
    name = payload.name.strip()
    existing_name = db.query(Category).filter(Category.name == name).first()
    if existing_name:
        raise HTTPException(
            status_code=400,
            detail=f"A category with name '{name}' already exists"
        )

    category = Category(
        name=name,
        slug=slug,
        description=payload.description.strip() if payload.description else None,
    )
    db.add(category)
    db.commit()
    db.refresh(category)

    logger.info("Created category: %s (%s)", category.name, category.slug)
    return _category_to_out(category, db)


@admin_categories_router.get("/{category_id}", response_model=CategoryOut)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CategoryOut:
    """Get a specific category by ID."""
    category = db.query(Category).filter(Category.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    return _category_to_out(category, db)


@admin_categories_router.put("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CategoryOut:
    """Update a category."""
    category = db.query(Category).filter(Category.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Update fields if provided
    if payload.slug is not None:
        new_slug = payload.slug.lower().strip()
        # Check for duplicate slug (excluding self)
        existing = db.query(Category).filter(
            Category.slug == new_slug,
            Category.id != category_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A category with slug '{new_slug}' already exists"
            )
        category.slug = new_slug

    if payload.name is not None:
        new_name = payload.name.strip()
        # Check for duplicate name (excluding self)
        existing = db.query(Category).filter(
            Category.name == new_name,
            Category.id != category_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A category with name '{new_name}' already exists"
            )
        category.name = new_name

    if payload.description is not None:
        category.description = payload.description.strip() if payload.description else None

    db.commit()
    db.refresh(category)

    logger.info("Updated category %d: %s (%s)", category.id, category.name, category.slug)
    return _category_to_out(category, db)


@admin_categories_router.delete("/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a category."""
    category = db.query(Category).filter(Category.id == category_id).first()

    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Check if category has menu items
    menu_item_count = db.query(MenuItemCategory).filter(
        MenuItemCategory.category_id == category_id
    ).count()

    if menu_item_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category '{category.name}' - it has {menu_item_count} menu items assigned"
        )

    name = category.name
    db.delete(category)
    db.commit()

    logger.info("Deleted category: %s", name)
