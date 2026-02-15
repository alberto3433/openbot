"""
Admin Menu Display Groups Routes for Orderbot
===============================================

This module contains admin endpoints for managing menu display groups.
Display groups consolidate item types into user-friendly categories for
menu listing. When a user asks "what's on your menu?", we show these
groups instead of granular item types.

Endpoints:
----------
- GET /admin/menu-display-groups: List all groups
- POST /admin/menu-display-groups: Create a new group
- GET /admin/menu-display-groups/{id}: Get a specific group
- PUT /admin/menu-display-groups/{id}: Update a group
- DELETE /admin/menu-display-groups/{id}: Delete a group

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

from fastapi import HTTPException

from ..db.models import MenuDisplayGroup, MenuDisplayGroupAlias, ItemType, OverallCategory
from ..schemas.menu_display_groups import (
    MenuDisplayGroupCreate,
    MenuDisplayGroupUpdate,
    MenuDisplayGroupOut,
    MenuDisplayGroupList,
)
from .crud_factory import CRUDRouterFactory
from .crud_helpers import make_list_builder


def _group_to_out(group, db):
    """Convert a MenuDisplayGroup model to MenuDisplayGroupOut with item_type_count and aliases."""
    item_type_count = db.query(ItemType).filter(
        ItemType.menu_display_group_id == group.id
    ).count()

    # Get category name if set
    category_name = None
    if group.overall_category:
        category_name = group.overall_category.display_name

    # Get parent name if set
    parent_name = None
    if group.parent:
        parent_name = group.parent.display_name

    return MenuDisplayGroupOut(
        id=group.id,
        slug=group.slug,
        display_name=group.display_name,
        display_order=group.display_order,
        overall_category_id=group.overall_category_id,
        overall_category_name=category_name,
        parent_id=group.parent_id,
        parent_name=parent_name,
        item_type_count=item_type_count,
        aliases=group.aliases,
    )


def _validate_aliases(aliases: list[str], db, exclude_group_id: int | None = None) -> list[str]:
    """Validate and normalize aliases, checking for duplicates."""
    normalized = []
    for alias in aliases:
        alias = alias.lower().strip()
        if not alias:
            continue
        if alias in normalized:
            continue  # Skip duplicates in the same request

        # Check if alias already exists for another group
        query = db.query(MenuDisplayGroupAlias).filter(MenuDisplayGroupAlias.alias == alias)
        if exclude_group_id is not None:
            query = query.filter(MenuDisplayGroupAlias.menu_display_group_id != exclude_group_id)
        existing = query.first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Alias '{alias}' is already used by another display group"
            )
        normalized.append(alias)
    return normalized


def _build_create_kwargs(payload, db):
    """Build model kwargs from create payload with normalization."""
    slug = payload.slug.lower().strip()
    display_name = payload.display_name.strip()

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

    # Validate parent_id if provided
    if payload.parent_id is not None:
        parent = db.query(MenuDisplayGroup).filter(
            MenuDisplayGroup.id == payload.parent_id
        ).first()
        if not parent:
            raise HTTPException(
                status_code=400,
                detail=f"Parent display group with id {payload.parent_id} not found"
            )

    # Validate aliases (will be added in pre_commit hook)
    if payload.aliases:
        _validate_aliases(payload.aliases, db)

    return {
        "slug": slug,
        "display_name": display_name,
        "display_order": payload.display_order,
        "overall_category_id": payload.overall_category_id,
        "parent_id": payload.parent_id,
    }


def _handle_create_pre_commit(item, payload, db):
    """Add aliases after the group is created (has ID) but before commit."""
    if payload.aliases:
        for alias in payload.aliases:
            alias = alias.lower().strip()
            if alias:
                db.add(MenuDisplayGroupAlias(
                    menu_display_group_id=item.id,
                    alias=alias
                ))


def _handle_before_update(item, payload, db):
    """Apply update payload to item."""
    if payload.slug is not None:
        item.slug = payload.slug.lower().strip()

    if payload.display_name is not None:
        item.display_name = payload.display_name.strip()

    if payload.display_order is not None:
        item.display_order = payload.display_order

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

    # Handle parent_id update
    update_data = payload.model_dump(exclude_unset=True)
    if "parent_id" in update_data:
        new_parent_id = update_data["parent_id"]
        if new_parent_id is not None:
            # Prevent self-reference
            if new_parent_id == item.id:
                raise HTTPException(status_code=400, detail="A group cannot be its own parent")
            # Validate parent exists
            parent = db.query(MenuDisplayGroup).filter(
                MenuDisplayGroup.id == new_parent_id
            ).first()
            if not parent:
                raise HTTPException(
                    status_code=400,
                    detail=f"Parent display group with id {new_parent_id} not found"
                )
        item.parent_id = new_parent_id

    # Handle aliases if provided (replaces all existing aliases)
    if payload.aliases is not None:
        # Validate new aliases
        normalized_aliases = _validate_aliases(payload.aliases, db, exclude_group_id=item.id)

        # Delete existing aliases
        db.query(MenuDisplayGroupAlias).filter(
            MenuDisplayGroupAlias.menu_display_group_id == item.id
        ).delete()

        # Add new aliases
        for alias in normalized_aliases:
            db.add(MenuDisplayGroupAlias(
                menu_display_group_id=item.id,
                alias=alias
            ))


def _handle_before_delete(item, db):
    """Check if group can be deleted."""
    item_type_count = db.query(ItemType).filter(ItemType.menu_display_group_id == item.id).count()
    if item_type_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete group '{item.display_name}' - it has {item_type_count} item types assigned"
        )


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=MenuDisplayGroup,
    create_schema=MenuDisplayGroupCreate,
    update_schema=MenuDisplayGroupUpdate,
    response_schema=MenuDisplayGroupOut,
    prefix="/admin/menu-display-groups",
    tags=["Admin - Menu Display Groups"],
    id_param="group_id",
    not_found_message="Menu display group not found",
    unique_fields=["slug"],
    order_by=["display_order", "display_name"],
    to_response=_group_to_out,
    on_before_create=_build_create_kwargs,
    on_create_pre_commit=_handle_create_pre_commit,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
    list_response_schema=MenuDisplayGroupList,
    list_response_builder=make_list_builder(MenuDisplayGroupList, "groups"),
)

# Export the router
admin_menu_display_groups_router = _crud.router
