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

from fastapi import Depends
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import MenuItemSizeCategory, MenuItemSize, MenuItemSizePrice
from ..exceptions import ReferentialIntegrityError, ValidationError
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
from ..cache.base import normalize_text
from ..services.store_service import get_or_create_company
from .crud_factory import CRUDRouterFactory, reorder_routes_static_first
from .crud_helpers import apply_payload_updates, check_slug_unique, make_list_builder


logger = logging.getLogger(__name__)


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
# Size Category CRUD Hooks
# =============================================================================

def _cat_before_create(payload: SizeCategoryCreate, db: Session) -> dict:
    company = get_or_create_company(db)
    slug = normalize_text(payload.slug)
    existing = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.company_id == company.id,
        MenuItemSizeCategory.slug == slug
    ).first()
    if existing:
        raise ValidationError(f"A size category with slug '{slug}' already exists")
    return {
        "company_id": company.id,
        "name": payload.name.strip(),
        "slug": slug,
        "question_text": payload.question_text.strip() if payload.question_text else None,
    }


def _cat_before_update(
    item: MenuItemSizeCategory, payload: SizeCategoryUpdate, db: Session
) -> None:
    if payload.slug is not None:
        new_slug = normalize_text(payload.slug)
        check_slug_unique(
            db, MenuItemSizeCategory, new_slug,
            exclude_id=item.id,
            scope_filters={"company_id": item.company_id},
            detail=f"A size category with slug '{new_slug}' already exists",
        )
    apply_payload_updates(
        item, payload, db,
        normalize_fields={"slug": "lower_strip", "name": "strip", "question_text": "strip"}
    )


def _cat_before_delete(item: MenuItemSizeCategory, db: Session) -> None:
    size_count = db.query(MenuItemSize).filter(
        MenuItemSize.category_id == item.id
    ).count()
    if size_count > 0:
        raise ReferentialIntegrityError(
            f"Cannot delete category '{item.name}' - it has {size_count} sizes. "
            f"Delete the sizes first."
        )


# =============================================================================
# Size Category Router (factory + custom endpoints)
# =============================================================================

_cat_crud = CRUDRouterFactory(
    model=MenuItemSizeCategory,
    create_schema=SizeCategoryCreate,
    update_schema=SizeCategoryUpdate,
    response_schema=SizeCategoryOut,
    prefix="/admin/size-categories",
    tags=["Admin - Size Categories"],
    id_param="category_id",
    not_found_message="Size category not found",
    on_before_create=_cat_before_create,
    on_before_update=_cat_before_update,
    on_before_delete=_cat_before_delete,
    to_response=_category_to_out,
    list_response_schema=SizeCategoryList,
    list_response_builder=make_list_builder(SizeCategoryList, "categories"),
)
admin_size_categories_router = _cat_crud.router

# Remove the factory's default list endpoint (we need company-scoped queries)
admin_size_categories_router.routes.pop(0)


# Custom list endpoint: company-scoped
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


# Custom endpoint: categories with their sizes included
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


# Fix route ordering: static GET paths (/with-sizes) must be matched
# before the factory's GET /{category_id} to prevent 422 errors.
reorder_routes_static_first(admin_size_categories_router)


# =============================================================================
# Size CRUD Hooks
# =============================================================================

def _size_before_create(payload: SizeCreate, db: Session) -> dict:
    company = get_or_create_company(db)
    category = db.query(MenuItemSizeCategory).filter(
        MenuItemSizeCategory.id == payload.category_id,
        MenuItemSizeCategory.company_id == company.id
    ).first()
    if not category:
        raise ValidationError("Size category not found")
    name = payload.name.strip()
    existing = db.query(MenuItemSize).filter(
        MenuItemSize.category_id == payload.category_id,
        MenuItemSize.name == name
    ).first()
    if existing:
        raise ValidationError(
            f"A size with name '{name}' already exists in category '{category.name}'"
        )
    return {
        "company_id": company.id,
        "category_id": payload.category_id,
        "name": name,
        "display_order": payload.display_order,
    }


def _size_before_update(item: MenuItemSize, payload: SizeUpdate, db: Session) -> None:
    if payload.category_id is not None:
        company = get_or_create_company(db)
        category = db.query(MenuItemSizeCategory).filter(
            MenuItemSizeCategory.id == payload.category_id,
            MenuItemSizeCategory.company_id == company.id
        ).first()
        if not category:
            raise ValidationError("Size category not found")
    if payload.name is not None:
        new_name = payload.name.strip()
        check_category_id = (
            payload.category_id if payload.category_id is not None else item.category_id
        )
        existing = db.query(MenuItemSize).filter(
            MenuItemSize.category_id == check_category_id,
            MenuItemSize.name == new_name,
            MenuItemSize.id != item.id
        ).first()
        if existing:
            raise ValidationError(
                f"A size with name '{new_name}' already exists in this category"
            )
    apply_payload_updates(item, payload, db, normalize_fields={"name": "strip"})


def _size_before_delete(item: MenuItemSize, db: Session) -> None:
    price_count = db.query(MenuItemSizePrice).filter(
        MenuItemSizePrice.size_id == item.id
    ).count()
    if price_count > 0:
        raise ReferentialIntegrityError(
            f"Cannot delete size '{item.name}' - it is used by {price_count} menu items"
        )


# =============================================================================
# Size Router (factory + custom list endpoint)
# =============================================================================

_size_crud = CRUDRouterFactory(
    model=MenuItemSize,
    create_schema=SizeCreate,
    update_schema=SizeUpdate,
    response_schema=SizeOut,
    prefix="/admin/sizes",
    tags=["Admin - Sizes"],
    id_param="size_id",
    not_found_message="Size not found",
    on_before_create=_size_before_create,
    on_before_update=_size_before_update,
    on_before_delete=_size_before_delete,
    to_response=_size_to_out,
    list_response_schema=SizeList,
    list_response_builder=make_list_builder(SizeList, "sizes"),
)
admin_sizes_router = _size_crud.router

# Remove the factory's default list endpoint (we need company-scoped + category filter)
admin_sizes_router.routes.pop(0)


# Custom list endpoint: company-scoped with optional category filter
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
