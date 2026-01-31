"""
Admin Menu Item Size Routes for Orderbot
=============================================

This module contains admin endpoints for managing menu item size-based pricing.
The size pricing system allows explicit prices per size per menu item,
replacing the base_price + upcharge model for items with size variants.

Size Categories:
----------------
Categories like 'size' (small/large), 'weight' (1/4 lb, 1/2 lb), 'quantity' (each).
Each category has a question_text for asking customers to choose.

Sizes:
------
Individual size options within a category. Sizes have a display_order
to control how they're presented to customers.

Size Prices:
------------
Explicit price per menu item per size. Managed via the menu item admin
endpoints, not directly through these routes.

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import MenuItemSizeCategory, MenuItemSize, MenuItemSizePrice
from ..schemas.menu_item_sizes import (
    SizeCategoryCreate,
    SizeCategoryUpdate,
    SizeCategoryOut,
    SizeCategoryList,
    SizeCategoryWithSizes,
    SizeCreate,
    SizeUpdate,
    SizeOut,
    SizeList,
)
from ..services.helpers import get_or_create_company
from .crud_helpers import apply_payload_updates


logger = logging.getLogger(__name__)

# Router definitions
admin_size_categories_router = APIRouter(
    prefix="/admin/size-categories",
    tags=["Admin - Size Categories"]
)

admin_sizes_router = APIRouter(
    prefix="/admin/sizes",
    tags=["Admin - Sizes"]
)


# =============================================================================
# Helper Functions
# =============================================================================

def _category_to_out(category: MenuItemSizeCategory, db: Session) -> SizeCategoryOut:
    """Convert a MenuItemSizeCategory model to SizeCategoryOut with size_count."""
    size_count = db.query(MenuItemSize).filter(
        MenuItemSize.category_id == category.id
    ).count()

    return SizeCategoryOut(
        id=category.id,
        company_id=category.company_id,
        name=category.name,
        slug=category.slug,
        question_text=category.question_text,
        created_at=category.created_at,
        size_count=size_count,
    )


def _size_to_out(size: MenuItemSize, db: Session) -> SizeOut:
    """Convert a MenuItemSize model to SizeOut with category_name and menu_item_count."""
    menu_item_count = db.query(MenuItemSizePrice).filter(
        MenuItemSizePrice.size_id == size.id
    ).count()

    return SizeOut(
        id=size.id,
        company_id=size.company_id,
        category_id=size.category_id,
        name=size.name,
        display_order=size.display_order,
        created_at=size.created_at,
        category_name=size.category.name if size.category else None,
        menu_item_count=menu_item_count,
    )


# =============================================================================
# Size Category Endpoints
# =============================================================================

@admin_size_categories_router.get("", response_model=SizeCategoryList)
def list_size_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeCategoryList:
    """List all size categories."""
    company = get_or_create_company(db)
    categories = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.company_id == company.id
    ).order_by(MenuItemSizeCategory.name).all()

    return SizeCategoryList(
        categories=[_category_to_out(c, db) for c in categories],
        total=len(categories)
    )


@admin_size_categories_router.get("/with-sizes", response_model=list[SizeCategoryWithSizes])
def list_size_categories_with_sizes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[SizeCategoryWithSizes]:
    """List all size categories with their sizes included."""
    company = get_or_create_company(db)
    categories = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.company_id == company.id
    ).order_by(MenuItemSizeCategory.name).all()

    result = []
    for category in categories:
        sizes = db.query(MenuItemSize).filter(
            MenuItemSize.category_id == category.id
        ).order_by(MenuItemSize.display_order).all()

        cat_out = _category_to_out(category, db)
        result.append(SizeCategoryWithSizes(
            **cat_out.model_dump(),
            sizes=[_size_to_out(s, db) for s in sizes]
        ))

    return result


@admin_size_categories_router.post("", response_model=SizeCategoryOut, status_code=201)
def create_size_category(
    payload: SizeCategoryCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeCategoryOut:
    """Create a new size category."""
    company = get_or_create_company(db)

    # Check for duplicate slug
    slug = payload.slug.lower().strip()
    existing = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.company_id == company.id,
        MenuItemSizeCategory.slug == slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A size category with slug '{slug}' already exists"
        )

    category = MenuItemSizeCategory(
        company_id=company.id,
        name=payload.name.strip(),
        slug=slug,
        question_text=payload.question_text.strip() if payload.question_text else None,
    )
    db.add(category)
    db.commit()
    db.refresh(category)

    logger.info("Created size category: %s (%s)", category.name, category.slug)
    return _category_to_out(category, db)


@admin_size_categories_router.get("/{category_id}", response_model=SizeCategoryOut)
def get_size_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeCategoryOut:
    """Get a specific size category by ID."""
    category = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Size category not found")

    return _category_to_out(category, db)


@admin_size_categories_router.put("/{category_id}", response_model=SizeCategoryOut)
def update_size_category(
    category_id: int,
    payload: SizeCategoryUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeCategoryOut:
    """Update a size category."""
    category = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Size category not found")

    # Check for duplicate slug (company-scoped uniqueness)
    if payload.slug is not None:
        new_slug = payload.slug.lower().strip()
        existing = db.query(MenuItemSizeCategory).filter(
            MenuItemSizeCategory.company_id == category.company_id,
            MenuItemSizeCategory.slug == new_slug,
            MenuItemSizeCategory.id != category_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A size category with slug '{new_slug}' already exists"
            )

    # Apply updates with normalization
    apply_payload_updates(
        category, payload, db,
        normalize_fields={"slug": "lower_strip", "name": "strip", "question_text": "strip"}
    )

    db.commit()
    db.refresh(category)

    logger.info("Updated size category %d: %s (%s)", category.id, category.name, category.slug)
    return _category_to_out(category, db)


@admin_size_categories_router.delete("/{category_id}", status_code=204)
def delete_size_category(
    category_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a size category."""
    category = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(status_code=404, detail="Size category not found")

    # Check if category has sizes
    size_count = db.query(MenuItemSize).filter(
        MenuItemSize.category_id == category_id
    ).count()

    if size_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete category '{category.name}' - it has {size_count} sizes. Delete the sizes first."
        )

    name = category.name
    db.delete(category)
    db.commit()

    logger.info("Deleted size category: %s", name)


# =============================================================================
# Size Endpoints
# =============================================================================

@admin_sizes_router.get("", response_model=SizeList)
def list_sizes(
    category_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeList:
    """List all sizes, optionally filtered by category."""
    company = get_or_create_company(db)
    query = db.query(MenuItemSize).filter(
        MenuItemSize.company_id == company.id
    )

    if category_id is not None:
        query = query.filter(MenuItemSize.category_id == category_id)

    sizes = query.order_by(
        MenuItemSize.category_id,
        MenuItemSize.display_order
    ).all()

    return SizeList(
        sizes=[_size_to_out(s, db) for s in sizes],
        total=len(sizes)
    )


@admin_sizes_router.post("", response_model=SizeOut, status_code=201)
def create_size(
    payload: SizeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeOut:
    """Create a new size."""
    company = get_or_create_company(db)

    # Verify category exists and belongs to this company
    category = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.id == payload.category_id,
        MenuItemSizeCategory.company_id == company.id
    ).first()
    if not category:
        raise HTTPException(status_code=404, detail="Size category not found")

    # Check for duplicate name within category
    name = payload.name.strip()
    existing = db.query(MenuItemSize).filter(
        MenuItemSize.category_id == payload.category_id,
        MenuItemSize.name == name
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A size with name '{name}' already exists in category '{category.name}'"
        )

    size = MenuItemSize(
        company_id=company.id,
        category_id=payload.category_id,
        name=name,
        display_order=payload.display_order,
    )
    db.add(size)
    db.commit()
    db.refresh(size)

    logger.info("Created size: %s in category %s", size.name, category.name)
    return _size_to_out(size, db)


@admin_sizes_router.get("/{size_id}", response_model=SizeOut)
def get_size(
    size_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeOut:
    """Get a specific size by ID."""
    size = db.query(MenuItemSize).filter(
        MenuItemSize.id == size_id
    ).first()

    if not size:
        raise HTTPException(status_code=404, detail="Size not found")

    return _size_to_out(size, db)


@admin_sizes_router.put("/{size_id}", response_model=SizeOut)
def update_size(
    size_id: int,
    payload: SizeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SizeOut:
    """Update a size."""
    size = db.query(MenuItemSize).filter(
        MenuItemSize.id == size_id
    ).first()

    if not size:
        raise HTTPException(status_code=404, detail="Size not found")

    # Validate category if provided
    if payload.category_id is not None:
        company = get_or_create_company(db)
        category = db.query(MenuItemSizeCategory).filter(
            MenuItemSizeCategory.id == payload.category_id,
            MenuItemSizeCategory.company_id == company.id
        ).first()
        if not category:
            raise HTTPException(status_code=404, detail="Size category not found")

    # Check for duplicate name within category
    if payload.name is not None:
        new_name = payload.name.strip()
        check_category_id = payload.category_id if payload.category_id is not None else size.category_id
        existing = db.query(MenuItemSize).filter(
            MenuItemSize.category_id == check_category_id,
            MenuItemSize.name == new_name,
            MenuItemSize.id != size_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A size with name '{new_name}' already exists in this category"
            )

    # Apply updates with normalization
    apply_payload_updates(size, payload, db, normalize_fields={"name": "strip"})

    db.commit()
    db.refresh(size)

    logger.info("Updated size %d: %s", size.id, size.name)
    return _size_to_out(size, db)


@admin_sizes_router.delete("/{size_id}", status_code=204)
def delete_size(
    size_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a size."""
    size = db.query(MenuItemSize).filter(
        MenuItemSize.id == size_id
    ).first()

    if not size:
        raise HTTPException(status_code=404, detail="Size not found")

    # Check if size is used by any menu items
    price_count = db.query(MenuItemSizePrice).filter(
        MenuItemSizePrice.size_id == size_id
    ).count()

    if price_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete size '{size.name}' - it is used by {price_count} menu items"
        )

    name = size.name
    db.delete(size)
    db.commit()

    logger.info("Deleted size: %s", name)
