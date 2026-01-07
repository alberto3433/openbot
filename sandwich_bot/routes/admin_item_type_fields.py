"""
Admin Item Type Fields Routes for Sandwich Bot
===============================================

This module contains admin endpoints for managing item type field configurations.
Item type fields define which questions to ask for each item type (e.g., bagel_type,
toasted, spread for bagels).

Endpoints:
----------
- GET /admin/item-type-fields: List all fields
- GET /admin/item-type-fields/{id}: Get a specific field
- POST /admin/item-type-fields: Create a new field
- PUT /admin/item-type-fields/{id}: Update a field
- DELETE /admin/item-type-fields/{id}: Delete a field

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # List all fields for bagels
    GET /admin/item-type-fields?item_type_slug=bagel

    # Create a new field
    POST /admin/item-type-fields
    {
        "item_type_id": 1,
        "field_name": "scooped",
        "display_order": 5,
        "required": false,
        "ask": true,
        "question_text": "Would you like it scooped?"
    }
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ItemTypeField, ItemType
from ..schemas.item_type_fields import (
    ItemTypeFieldOut,
    ItemTypeFieldCreate,
    ItemTypeFieldUpdate,
)

logger = logging.getLogger(__name__)

# Router definition
admin_item_type_fields_router = APIRouter(
    prefix="/admin/item-type-fields",
    tags=["Admin - Item Type Fields"]
)


@admin_item_type_fields_router.get("", response_model=List[ItemTypeFieldOut])
def list_item_type_fields(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    item_type_slug: Optional[str] = Query(None, description="Filter by item type slug"),
    item_type_id: Optional[int] = Query(None, description="Filter by item type ID"),
) -> List[ItemTypeFieldOut]:
    """List all item type fields, optionally filtered by item type."""
    query = db.query(ItemTypeField).join(ItemType)

    if item_type_slug:
        query = query.filter(ItemType.slug == item_type_slug)
    if item_type_id:
        query = query.filter(ItemTypeField.item_type_id == item_type_id)

    fields = query.order_by(ItemType.slug, ItemTypeField.display_order).all()

    result = []
    for field in fields:
        result.append(ItemTypeFieldOut(
            id=field.id,
            item_type_id=field.item_type_id,
            item_type_slug=field.item_type.slug,
            field_name=field.field_name,
            display_order=field.display_order,
            required=field.required,
            ask=field.ask,
            question_text=field.question_text,
            created_at=field.created_at,
            updated_at=field.updated_at,
        ))
    return result


@admin_item_type_fields_router.get("/{field_id}", response_model=ItemTypeFieldOut)
def get_item_type_field(
    field_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeFieldOut:
    """Get a specific item type field by ID."""
    field = db.query(ItemTypeField).filter(ItemTypeField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Item type field not found")

    return ItemTypeFieldOut(
        id=field.id,
        item_type_id=field.item_type_id,
        item_type_slug=field.item_type.slug,
        field_name=field.field_name,
        display_order=field.display_order,
        required=field.required,
        ask=field.ask,
        question_text=field.question_text,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )


@admin_item_type_fields_router.post("", response_model=ItemTypeFieldOut, status_code=201)
def create_item_type_field(
    payload: ItemTypeFieldCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeFieldOut:
    """Create a new item type field."""
    # Verify item type exists
    item_type = db.query(ItemType).filter(ItemType.id == payload.item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=400, detail=f"Item type with ID {payload.item_type_id} not found")

    # Check for duplicate field_name for this item_type
    existing = db.query(ItemTypeField).filter(
        ItemTypeField.item_type_id == payload.item_type_id,
        ItemTypeField.field_name == payload.field_name
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Field '{payload.field_name}' already exists for item type '{item_type.slug}'"
        )

    field = ItemTypeField(
        item_type_id=payload.item_type_id,
        field_name=payload.field_name,
        display_order=payload.display_order,
        required=payload.required,
        ask=payload.ask,
        question_text=payload.question_text,
    )
    db.add(field)
    db.commit()
    db.refresh(field)

    logger.info(
        "Created item type field: %s for %s (id=%d)",
        field.field_name,
        item_type.slug,
        field.id
    )

    return ItemTypeFieldOut(
        id=field.id,
        item_type_id=field.item_type_id,
        item_type_slug=item_type.slug,
        field_name=field.field_name,
        display_order=field.display_order,
        required=field.required,
        ask=field.ask,
        question_text=field.question_text,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )


@admin_item_type_fields_router.put("/{field_id}", response_model=ItemTypeFieldOut)
def update_item_type_field(
    field_id: int,
    payload: ItemTypeFieldUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeFieldOut:
    """Update an item type field."""
    field = db.query(ItemTypeField).filter(ItemTypeField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Item type field not found")

    # Check for duplicate field_name if changing it
    if payload.field_name is not None and payload.field_name != field.field_name:
        existing = db.query(ItemTypeField).filter(
            ItemTypeField.item_type_id == field.item_type_id,
            ItemTypeField.field_name == payload.field_name
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{payload.field_name}' already exists for this item type"
            )

    if payload.field_name is not None:
        field.field_name = payload.field_name
    if payload.display_order is not None:
        field.display_order = payload.display_order
    if payload.required is not None:
        field.required = payload.required
    if payload.ask is not None:
        field.ask = payload.ask
    if payload.question_text is not None:
        field.question_text = payload.question_text

    db.commit()
    db.refresh(field)

    logger.info("Updated item type field: %s (id=%d)", field.field_name, field.id)

    return ItemTypeFieldOut(
        id=field.id,
        item_type_id=field.item_type_id,
        item_type_slug=field.item_type.slug,
        field_name=field.field_name,
        display_order=field.display_order,
        required=field.required,
        ask=field.ask,
        question_text=field.question_text,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )


@admin_item_type_fields_router.delete("/{field_id}", status_code=204)
def delete_item_type_field(
    field_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an item type field."""
    field = db.query(ItemTypeField).filter(ItemTypeField.id == field_id).first()
    if not field:
        raise HTTPException(status_code=404, detail="Item type field not found")

    logger.info(
        "Deleting item type field: %s for %s (id=%d)",
        field.field_name,
        field.item_type.slug,
        field.id
    )
    db.delete(field)
    db.commit()
    return None
