"""
Admin Item Type Attributes Routes for Sandwich Bot
===================================================

This module contains admin endpoints for managing item type attributes using the
new consolidated schema (item_type_attributes table). This replaces the older
item_type_field and attribute_definitions tables.

Endpoints:
----------
- GET /admin/item-type-attributes: List all attributes
- GET /admin/item-type-attributes/{id}: Get a specific attribute
- POST /admin/item-type-attributes: Create a new attribute
- PUT /admin/item-type-attributes/{id}: Update an attribute
- DELETE /admin/item-type-attributes/{id}: Delete an attribute

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # List all attributes for egg_sandwich
    GET /admin/item-type-attributes?item_type_slug=egg_sandwich

    # Create a new attribute
    POST /admin/item-type-attributes
    {
        "item_type_id": 5,
        "slug": "sauce",
        "display_name": "Sauce",
        "input_type": "single_select",
        "is_required": false,
        "ask_in_conversation": true,
        "question_text": "Would you like any sauce?"
    }
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ItemType, ItemTypeAttribute, AttributeOption
from ..schemas.item_type_attributes import (
    ItemTypeAttributeOut,
    ItemTypeAttributeCreate,
    ItemTypeAttributeUpdate,
    AttributeOptionOut,
)

logger = logging.getLogger(__name__)

# Router definition
admin_item_type_attributes_router = APIRouter(
    prefix="/admin/item-type-attributes",
    tags=["Admin - Item Type Attributes"]
)


def _serialize_attribute(attr: ItemTypeAttribute, db: Session) -> ItemTypeAttributeOut:
    """Convert ItemTypeAttribute model to response schema with options."""
    # Get options linked via item_type_attribute_id
    options = (
        db.query(AttributeOption)
        .filter(AttributeOption.item_type_attribute_id == attr.id)
        .order_by(AttributeOption.display_order)
        .all()
    )

    return ItemTypeAttributeOut(
        id=attr.id,
        item_type_id=attr.item_type_id,
        item_type_slug=attr.item_type.slug if attr.item_type else None,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        is_required=attr.is_required,
        allow_none=attr.allow_none,
        min_selections=attr.min_selections,
        max_selections=attr.max_selections,
        display_order=attr.display_order,
        ask_in_conversation=attr.ask_in_conversation,
        question_text=attr.question_text,
        options=[
            AttributeOptionOut(
                id=opt.id,
                slug=opt.slug,
                display_name=opt.display_name,
                price_modifier=float(opt.price_modifier or 0),
                is_default=opt.is_default,
                is_available=opt.is_available,
                display_order=opt.display_order,
            )
            for opt in options
        ],
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


@admin_item_type_attributes_router.get("", response_model=List[ItemTypeAttributeOut])
def list_item_type_attributes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    item_type_slug: Optional[str] = Query(None, description="Filter by item type slug"),
    item_type_id: Optional[int] = Query(None, description="Filter by item type ID"),
) -> List[ItemTypeAttributeOut]:
    """List all item type attributes, optionally filtered by item type."""
    query = db.query(ItemTypeAttribute).join(ItemType)

    if item_type_slug:
        query = query.filter(ItemType.slug == item_type_slug)
    if item_type_id:
        query = query.filter(ItemTypeAttribute.item_type_id == item_type_id)

    attrs = query.order_by(ItemType.slug, ItemTypeAttribute.display_order).all()
    return [_serialize_attribute(attr, db) for attr in attrs]


@admin_item_type_attributes_router.get("/{attr_id}", response_model=ItemTypeAttributeOut)
def get_item_type_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Get a specific item type attribute by ID."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")
    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.post("", response_model=ItemTypeAttributeOut, status_code=201)
def create_item_type_attribute(
    payload: ItemTypeAttributeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Create a new item type attribute."""
    # Verify item type exists
    item_type = db.query(ItemType).filter(ItemType.id == payload.item_type_id).first()
    if not item_type:
        raise HTTPException(
            status_code=400,
            detail=f"Item type with ID {payload.item_type_id} not found"
        )

    # Check for duplicate slug for this item_type
    existing = db.query(ItemTypeAttribute).filter(
        ItemTypeAttribute.item_type_id == payload.item_type_id,
        ItemTypeAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Attribute '{payload.slug}' already exists for item type '{item_type.slug}'"
        )

    attr = ItemTypeAttribute(
        item_type_id=payload.item_type_id,
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        is_required=payload.is_required,
        allow_none=payload.allow_none,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        display_order=payload.display_order,
        ask_in_conversation=payload.ask_in_conversation,
        question_text=payload.question_text,
    )
    db.add(attr)
    db.commit()
    db.refresh(attr)

    logger.info(
        "Created item type attribute: %s for %s (id=%d)",
        attr.slug,
        item_type.slug,
        attr.id
    )

    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.put("/{attr_id}", response_model=ItemTypeAttributeOut)
def update_item_type_attribute(
    attr_id: int,
    payload: ItemTypeAttributeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Update an item type attribute."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    # Check for duplicate slug if changing it
    if payload.slug is not None and payload.slug != attr.slug:
        existing = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == attr.item_type_id,
            ItemTypeAttribute.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Attribute '{payload.slug}' already exists for this item type"
            )

    # Apply updates
    if payload.slug is not None:
        attr.slug = payload.slug
    if payload.display_name is not None:
        attr.display_name = payload.display_name
    if payload.input_type is not None:
        attr.input_type = payload.input_type
    if payload.is_required is not None:
        attr.is_required = payload.is_required
    if payload.allow_none is not None:
        attr.allow_none = payload.allow_none
    if payload.min_selections is not None:
        attr.min_selections = payload.min_selections
    if payload.max_selections is not None:
        attr.max_selections = payload.max_selections
    if payload.display_order is not None:
        attr.display_order = payload.display_order
    if payload.ask_in_conversation is not None:
        attr.ask_in_conversation = payload.ask_in_conversation
    if payload.question_text is not None:
        attr.question_text = payload.question_text

    db.commit()
    db.refresh(attr)

    logger.info("Updated item type attribute: %s (id=%d)", attr.slug, attr.id)

    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.delete("/{attr_id}", status_code=204)
def delete_item_type_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an item type attribute."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    logger.info(
        "Deleting item type attribute: %s for %s (id=%d)",
        attr.slug,
        attr.item_type.slug if attr.item_type else "unknown",
        attr.id
    )
    db.delete(attr)
    db.commit()
    return None
