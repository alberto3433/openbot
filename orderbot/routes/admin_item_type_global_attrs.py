"""
Admin Item Type Global Attribute Link Routes for Orderbot
=============================================================

This module contains admin endpoints for managing the links between
item types and global attributes. Split from admin_global_attributes.py
for maintainability.

Endpoints:
----------
- GET /admin/item-types/{id}/global-attributes: List linked global attributes
- POST /admin/item-types/{id}/global-attributes: Link a global attribute
- PUT /admin/item-types/{id}/global-attributes/{link_id}: Update link settings
- DELETE /admin/item-types/{id}/global-attributes/{link_id}: Unlink

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    GlobalAttribute,
    GlobalAttributeOption,
    Ingredient,
    ItemType,
    ItemTypeGlobalAttribute,
)
from ..schemas.global_attributes import (
    ItemTypeGlobalAttributeOut,
    ItemTypeGlobalAttributeLinkCreate,
    ItemTypeGlobalAttributeLinkUpdate,
)
from ..schemas.serializers import serialize_item_type_link
from .admin_global_attributes import admin_item_type_global_attrs_router
from .crud_helpers import get_or_404

logger = logging.getLogger(__name__)


# =============================================================================
# Item Type Global Attribute Link Endpoints
# =============================================================================

@admin_item_type_global_attrs_router.get(
    "/{item_type_id}/global-attributes",
    response_model=list[ItemTypeGlobalAttributeOut],
    summary="List global attributes linked to item type"
)
def list_item_type_global_attributes(
    item_type_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[ItemTypeGlobalAttributeOut]:
    """List all global attributes linked to an item type."""
    item_type = get_or_404(db, ItemType, item_type_id, detail="Item type not found")

    # Eager load all relationships to avoid N+1 queries
    # modifier_category is derived from ingredient at runtime
    links = (
        db.query(ItemTypeGlobalAttribute)
        .options(
            joinedload(ItemTypeGlobalAttribute.item_type),
            joinedload(ItemTypeGlobalAttribute.global_attribute)
            .selectinload(GlobalAttribute.options)
            .joinedload(GlobalAttributeOption.ingredient)
            .joinedload(Ingredient.modifier_category),
        )
        .filter(ItemTypeGlobalAttribute.item_type_id == item_type_id)
        .order_by(ItemTypeGlobalAttribute.display_order)
        .all()
    )

    return [serialize_item_type_link(link, db) for link in links]


@admin_item_type_global_attrs_router.post(
    "/{item_type_id}/global-attributes",
    response_model=ItemTypeGlobalAttributeOut,
    status_code=201,
    summary="Link a global attribute to item type"
)
def link_global_attribute_to_item_type(
    item_type_id: int,
    payload: ItemTypeGlobalAttributeLinkCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeGlobalAttributeOut:
    """Link a global attribute to an item type."""
    item_type = get_or_404(db, ItemType, item_type_id, detail="Item type not found")

    global_attr = get_or_404(db, GlobalAttribute, payload.global_attribute_id, detail="Global attribute not found")

    # Check if already linked
    existing = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.item_type_id == item_type_id,
        ItemTypeGlobalAttribute.global_attribute_id == payload.global_attribute_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Global attribute '{global_attr.slug}' is already linked to this item type"
        )

    link = ItemTypeGlobalAttribute(
        item_type_id=item_type_id,
        global_attribute_id=payload.global_attribute_id,
        display_order=payload.display_order,
        is_required=payload.is_required,
        allow_none=payload.allow_none,
        ask_in_conversation=payload.ask_in_conversation,
        listen_only=payload.listen_only,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        option_subcategory_filter=payload.option_subcategory_filter,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    logger.info(
        "Linked global attribute %s to item type %s (link_id=%d)",
        global_attr.slug,
        item_type.slug,
        link.id
    )
    return serialize_item_type_link(link, db)


@admin_item_type_global_attrs_router.put(
    "/{item_type_id}/global-attributes/{link_id}",
    response_model=ItemTypeGlobalAttributeOut,
    summary="Update link settings"
)
def update_item_type_global_attribute_link(
    item_type_id: int,
    link_id: int,
    payload: ItemTypeGlobalAttributeLinkUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeGlobalAttributeOut:
    """Update an item type's global attribute link settings."""
    item_type = get_or_404(db, ItemType, item_type_id, detail="Item type not found")

    link = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.id == link_id,
        ItemTypeGlobalAttribute.item_type_id == item_type_id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    # Apply updates
    if payload.display_order is not None:
        link.display_order = payload.display_order
    if payload.is_required is not None:
        link.is_required = payload.is_required
    if payload.allow_none is not None:
        link.allow_none = payload.allow_none
    if payload.ask_in_conversation is not None:
        link.ask_in_conversation = payload.ask_in_conversation
    if payload.listen_only is not None:
        link.listen_only = payload.listen_only
    if payload.min_selections is not None:
        link.min_selections = payload.min_selections
    if payload.max_selections is not None:
        link.max_selections = payload.max_selections
    if "option_subcategory_filter" in payload.model_fields_set:
        link.option_subcategory_filter = payload.option_subcategory_filter

    db.commit()
    db.refresh(link)

    logger.info(
        "Updated global attribute link for %s on %s (link_id=%d)",
        link.global_attribute.slug,
        item_type.slug,
        link.id
    )
    return serialize_item_type_link(link, db)


@admin_item_type_global_attrs_router.delete(
    "/{item_type_id}/global-attributes/{link_id}",
    status_code=204,
    summary="Unlink global attribute from item type"
)
def unlink_global_attribute_from_item_type(
    item_type_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Unlink a global attribute from an item type."""
    item_type = get_or_404(db, ItemType, item_type_id, detail="Item type not found")

    link = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.id == link_id,
        ItemTypeGlobalAttribute.item_type_id == item_type_id
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    logger.info(
        "Unlinking global attribute %s from item type %s (link_id=%d)",
        link.global_attribute.slug,
        item_type.slug,
        link.id
    )
    db.delete(link)
    db.commit()
    return None
