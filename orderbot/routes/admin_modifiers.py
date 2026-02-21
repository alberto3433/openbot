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
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import ItemType, MenuItem, ItemTypeGlobalAttribute, GlobalAttribute, MenuDisplayGroup, OverallCategory
from ..exceptions import ReferentialIntegrityError, ValidationError
from ..services.alias_service import sync_entity_aliases
from ..schemas.modifiers import (
    GlobalAttributeRef,
    ItemTypeListOut,
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
    OverallCategoryOut,
)
from ..schemas.serializers import serialize_item_type
from .crud_factory import CRUDRouterFactory
from .crud_helpers import apply_payload_updates


logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================

def _build_create_kwargs(payload: ItemTypeCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload."""
    # Validate display group ID (required)
    display_group = db.query(MenuDisplayGroup).filter(
        MenuDisplayGroup.id == payload.menu_display_group_id
    ).first()
    if not display_group:
        raise ValidationError(
            f"Menu display group with id {payload.menu_display_group_id} not found"
        )

    return {
        "slug": payload.slug,
        "display_name": payload.display_name,
        "menu_display_group_id": payload.menu_display_group_id,
    }


def _handle_create_pre_commit(
    item: ItemType,
    payload: ItemTypeCreate,
    db: Session,
) -> None:
    """Add aliases after item has ID but before commit."""
    if payload.aliases is not None:
        sync_entity_aliases(db, item, payload.aliases, "item_type")


def _handle_before_update(
    item: ItemType,
    payload: ItemTypeUpdate,
    db: Session,
) -> None:
    """Apply update payload to item."""
    apply_payload_updates(
        item, payload, db,
        skip_fields={"aliases", "menu_display_group_id"},
    )
    if payload.menu_display_group_id is not None:
        # Validate display group ID
        display_group = db.query(MenuDisplayGroup).filter(
            MenuDisplayGroup.id == payload.menu_display_group_id
        ).first()
        if not display_group:
            raise ValidationError(
                f"Menu display group with id {payload.menu_display_group_id} not found"
            )
        item.menu_display_group_id = payload.menu_display_group_id
    if payload.aliases is not None:
        sync_entity_aliases(db, item, payload.aliases, "item_type")


def _handle_before_delete(item: ItemType, db: Session) -> None:
    """Check if item type can be deleted."""
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item.id
    ).count()
    if menu_item_count > 0:
        raise ReferentialIntegrityError(
            f"Cannot delete: {menu_item_count} menu items use this type"
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
    to_response=serialize_item_type,
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
)


# =============================================================================
# Additional Endpoints (not covered by factory)
# =============================================================================

@admin_modifiers_router.get("/overall-categories", response_model=list[OverallCategoryOut])
def list_overall_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[OverallCategoryOut]:
    """List all overall categories (e.g., Food, Beverage)."""
    categories = db.query(OverallCategory).order_by(OverallCategory.display_name).all()
    return [OverallCategoryOut.model_validate(c) for c in categories]


@admin_modifiers_router.get("/menu-display-groups", response_model=list[dict])
def list_menu_display_groups(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """List all menu display groups for dropdown selection."""
    groups = db.query(MenuDisplayGroup).order_by(MenuDisplayGroup.display_order).all()
    return [
        {"id": g.id, "slug": g.slug, "display_name": g.display_name}
        for g in groups
    ]


@admin_modifiers_router.get("/item-types/list", response_model=list[ItemTypeListOut])
def list_item_types_minimal(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[ItemTypeListOut]:
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
