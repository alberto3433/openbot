"""
Admin Modifiers Routes for Orderbot
========================================

This module contains admin endpoints for managing the menu configuration
system: Item Types. Item types define categories of configurable menu items.

Endpoints:
----------
Item Types:
- GET /admin/modifiers/item-types: List all item types
- GET /admin/modifiers/item-types/list: Lightweight list for sidebar
- POST /admin/modifiers/item-types: Create item type
- GET /admin/modifiers/item-types/{id}: Get item type details
- PUT /admin/modifiers/item-types/{id}: Update item type
- DELETE /admin/modifiers/item-types/{id}: Delete item type

Overall Categories:
- GET /admin/modifiers/overall-categories: List all categories

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Structure:
----------
1. ItemType (e.g., "Bagel", "Sandwich", "Coffee")
   - Defines a category of configurable items
   - Links to menu items via MenuItem.item_type_id
   - Links to global attributes via ItemTypeGlobalAttribute
"""

import logging
from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import ItemType, ItemTypeAlias, MenuItem, ItemTypeGlobalAttribute, OverallCategory, GlobalAttribute
from ..services.helpers import validate_aliases
from ..schemas.modifiers import (
    GlobalAttributeRef,
    ItemTypeListOut,
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
    OverallCategoryOut,
)
from .crud_factory import CRUDRouterFactory


logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

def build_item_type_response(item_type: ItemType, db: Session) -> ItemTypeOut:
    """Build full ItemTypeOut response."""
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item_type.id
    ).count()

    # Query linked global attributes with their link details in a single query
    linked_data = (
        db.query(GlobalAttribute, ItemTypeGlobalAttribute)
        .join(ItemTypeGlobalAttribute, ItemTypeGlobalAttribute.global_attribute_id == GlobalAttribute.id)
        .filter(ItemTypeGlobalAttribute.item_type_id == item_type.id)
        .order_by(ItemTypeGlobalAttribute.display_order)
        .all()
    )

    global_attribute_count = len(linked_data)
    global_attributes = [
        GlobalAttributeRef(
            id=attr.id,
            slug=attr.slug,
            display_name=attr.display_name,
        )
        for attr, link in linked_data
    ]

    # Derive configurability from query results (no extra queries needed)
    is_configurable = global_attribute_count > 0
    has_askable = any(link.ask_in_conversation for attr, link in linked_data)
    skip_config = not has_askable if is_configurable else True

    # Get category name if set
    category_name = None
    if item_type.overall_category:
        category_name = item_type.overall_category.display_name

    return ItemTypeOut(
        id=item_type.id,
        slug=item_type.slug,
        display_name=item_type.display_name,
        is_configurable=is_configurable,
        skip_config=skip_config,
        overall_category_id=item_type.overall_category_id,
        overall_category_name=category_name,
        menu_item_count=menu_item_count,
        global_attribute_count=global_attribute_count,
        global_attributes=global_attributes,
        aliases=item_type.aliases,
    )


def _set_item_type_aliases(db: Session, item_type: ItemType, aliases_str: str | None) -> None:
    """
    Set item type aliases from a comma-separated string.
    Clears existing aliases and creates new ones from the input string.
    Validates global uniqueness of aliases before adding.

    Raises:
        HTTPException: If any alias conflicts with an existing alias
    """
    # Clear existing aliases
    for alias in list(item_type.alias_records):
        db.delete(alias)

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            # Exclude current item_type's own ID so re-saving same aliases works
            validated_aliases = validate_aliases(
                db,
                aliases_str,
                exclude_item_type_id=item_type.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            db.add(ItemTypeAlias(item_type=item_type, alias=alias))


def _build_create_kwargs(payload: ItemTypeCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload."""
    # Validate category ID if provided
    if payload.overall_category_id is not None:
        category = db.query(OverallCategory).filter(
            OverallCategory.id == payload.overall_category_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Overall category with id {payload.overall_category_id} not found"
            )

    return {
        "slug": payload.slug,
        "display_name": payload.display_name,
        "overall_category_id": payload.overall_category_id,
    }


def _handle_create_pre_commit(
    item: ItemType,
    payload: ItemTypeCreate,
    db: Session,
) -> None:
    """Add aliases after item has ID but before commit."""
    if payload.aliases is not None:
        _set_item_type_aliases(db, item, payload.aliases)


def _handle_before_update(
    item: ItemType,
    payload: ItemTypeUpdate,
    db: Session,
) -> None:
    """Apply update payload to item."""
    if payload.slug is not None:
        item.slug = payload.slug
    if payload.display_name is not None:
        item.display_name = payload.display_name
    if payload.overall_category_id is not None:
        # Validate category ID
        category = db.query(OverallCategory).filter(
            OverallCategory.id == payload.overall_category_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Overall category with id {payload.overall_category_id} not found"
            )
        item.overall_category_id = payload.overall_category_id
    if payload.aliases is not None:
        _set_item_type_aliases(db, item, payload.aliases)


def _handle_before_delete(item: ItemType, db: Session) -> None:
    """Check if item type can be deleted."""
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item.id
    ).count()
    if menu_item_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {menu_item_count} menu items use this type"
        )


# =============================================================================
# Router Setup
# =============================================================================

# Create the main router for item types
admin_modifiers_router = APIRouter(
    prefix="/admin/modifiers",
    tags=["Admin - Modifiers"]
)

# Create CRUD factory for item types (will be mounted at /item-types)
_item_type_crud = CRUDRouterFactory(
    model=ItemType,
    create_schema=ItemTypeCreate,
    update_schema=ItemTypeUpdate,
    response_schema=ItemTypeOut,
    prefix="/item-types",
    tags=["Admin - Modifiers"],
    id_param="item_type_id",
    not_found_message="Item type not found",
    unique_fields=["slug"],
    order_by=["display_name"],
    to_response=build_item_type_response,
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
)


# =============================================================================
# Additional Endpoints (not covered by factory)
# =============================================================================

@admin_modifiers_router.get("/overall-categories", response_model=List[OverallCategoryOut])
def list_overall_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[OverallCategoryOut]:
    """List all overall categories (e.g., Food, Beverage)."""
    categories = db.query(OverallCategory).order_by(OverallCategory.display_name).all()
    return [OverallCategoryOut.model_validate(c) for c in categories]


@admin_modifiers_router.get("/item-types/list", response_model=List[ItemTypeListOut])
def list_item_types_minimal(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ItemTypeListOut]:
    """Lightweight list for sidebar with counts using efficient subqueries."""
    # Subquery for menu item counts
    menu_count_subq = (
        db.query(
            MenuItem.item_type_id,
            func.count(MenuItem.id).label("menu_count")
        )
        .group_by(MenuItem.item_type_id)
        .subquery()
    )

    # Subquery for global attribute counts
    attr_count_subq = (
        db.query(
            ItemTypeGlobalAttribute.item_type_id,
            func.count(ItemTypeGlobalAttribute.id).label("attr_count")
        )
        .group_by(ItemTypeGlobalAttribute.item_type_id)
        .subquery()
    )

    # Main query with left outer joins to include types with zero counts
    results = (
        db.query(
            ItemType.id,
            ItemType.slug,
            ItemType.display_name,
            func.coalesce(menu_count_subq.c.menu_count, 0).label("menu_item_count"),
            func.coalesce(attr_count_subq.c.attr_count, 0).label("global_attribute_count"),
        )
        .outerjoin(menu_count_subq, ItemType.id == menu_count_subq.c.item_type_id)
        .outerjoin(attr_count_subq, ItemType.id == attr_count_subq.c.item_type_id)
        .order_by(ItemType.display_name)
        .all()
    )

    return [
        ItemTypeListOut(
            id=r.id,
            slug=r.slug,
            display_name=r.display_name,
            menu_item_count=r.menu_item_count,
            global_attribute_count=r.global_attribute_count,
        )
        for r in results
    ]


# Include the CRUD routes
admin_modifiers_router.include_router(_item_type_crud.router)
