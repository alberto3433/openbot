"""
Admin Global Attributes Routes for Sandwich Bot
================================================

This module contains admin endpoints for managing global (normalized) attributes
that are shared across item types.

Endpoints:
----------
Global Attributes:
- GET /admin/global-attributes: List all global attributes
- GET /admin/global-attributes/{id}: Get a specific global attribute with options
- POST /admin/global-attributes: Create a new global attribute
- PUT /admin/global-attributes/{id}: Update a global attribute
- DELETE /admin/global-attributes/{id}: Delete a global attribute

Global Attribute Options:
- GET /admin/global-attributes/{id}/options: List options for an attribute
- POST /admin/global-attributes/{id}/options: Add an option to an attribute
- PUT /admin/global-attributes/{id}/options/{option_id}: Update an option
- DELETE /admin/global-attributes/{id}/options/{option_id}: Delete an option

Item Type Links:
- GET /admin/item-types/{id}/global-attributes: List global attributes linked to item type
- POST /admin/item-types/{id}/global-attributes: Link a global attribute to item type
- PUT /admin/item-types/{id}/global-attributes/{link_id}: Update link settings
- DELETE /admin/item-types/{id}/global-attributes/{link_id}: Unlink global attribute

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import (
    GlobalAttribute,
    GlobalAttributeOption,
    ItemType,
    ItemTypeGlobalAttribute,
)
from ..schemas.global_attributes import (
    GlobalAttributeOut,
    GlobalAttributeListOut,
    GlobalAttributeCreate,
    GlobalAttributeUpdate,
    GlobalAttributeOptionOut,
    GlobalAttributeOptionCreate,
    GlobalAttributeOptionUpdate,
    ItemTypeGlobalAttributeOut,
    ItemTypeGlobalAttributeLinkCreate,
    ItemTypeGlobalAttributeLinkUpdate,
    GlobalAttributeWithOptionsCreate,
    LinkedItemTypeInfo,
)

logger = logging.getLogger(__name__)

# Router definition
admin_global_attributes_router = APIRouter(
    prefix="/admin/global-attributes",
    tags=["Admin - Global Attributes"]
)

# Separate router for item type links
admin_item_type_global_attrs_router = APIRouter(
    prefix="/admin/item-types",
    tags=["Admin - Item Type Global Attributes"]
)


# =============================================================================
# Helper Functions
# =============================================================================

def _serialize_option(opt: GlobalAttributeOption) -> GlobalAttributeOptionOut:
    """Convert GlobalAttributeOption model to response schema."""
    return GlobalAttributeOptionOut(
        id=opt.id,
        slug=opt.slug,
        display_name=opt.display_name,
        price_modifier=float(opt.price_modifier or 0),
        iced_price_modifier=float(opt.iced_price_modifier or 0),
        is_default=opt.is_default,
        is_available=opt.is_available,
        display_order=opt.display_order,
        created_at=opt.created_at,
        updated_at=opt.updated_at,
    )


def _serialize_attribute(attr: GlobalAttribute, db: Session) -> GlobalAttributeOut:
    """Convert GlobalAttribute model to response schema with options."""
    options_out = [_serialize_option(opt) for opt in attr.options]

    # Get item types using this attribute
    links = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.global_attribute_id == attr.id
    ).all()

    linked_item_types = []
    for link in links:
        item_type = db.query(ItemType).filter(ItemType.id == link.item_type_id).first()
        if item_type:
            linked_item_types.append(LinkedItemTypeInfo(
                id=item_type.id,
                slug=item_type.slug,
                display_name=item_type.display_name or item_type.slug.replace('_', ' ').title(),
            ))

    return GlobalAttributeOut(
        id=attr.id,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        description=attr.description,
        options=options_out,
        item_type_count=len(linked_item_types),
        linked_item_types=linked_item_types,
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


def _serialize_attribute_list(attr: GlobalAttribute, db: Session) -> GlobalAttributeListOut:
    """Convert GlobalAttribute model to list response schema (no options)."""
    option_count = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr.id
    ).count()

    item_type_count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.global_attribute_id == attr.id
    ).count()

    return GlobalAttributeListOut(
        id=attr.id,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        description=attr.description,
        option_count=option_count,
        item_type_count=item_type_count,
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


def _serialize_item_type_link(
    link: ItemTypeGlobalAttribute,
    db: Session
) -> ItemTypeGlobalAttributeOut:
    """Convert ItemTypeGlobalAttribute link to response schema."""
    global_attr = link.global_attribute
    options_out = [_serialize_option(opt) for opt in global_attr.options]

    return ItemTypeGlobalAttributeOut(
        id=link.id,
        item_type_id=link.item_type_id,
        item_type_slug=link.item_type.slug if link.item_type else None,
        global_attribute_id=link.global_attribute_id,
        global_attribute_slug=global_attr.slug,
        global_attribute_display_name=global_attr.display_name,
        input_type=global_attr.input_type,
        display_order=link.display_order,
        is_required=link.is_required,
        allow_none=link.allow_none,
        ask_in_conversation=link.ask_in_conversation,
        question_text=link.question_text,
        min_selections=link.min_selections,
        max_selections=link.max_selections,
        options=options_out,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


# =============================================================================
# Global Attribute Endpoints
# =============================================================================

@admin_global_attributes_router.get("", response_model=List[GlobalAttributeListOut])
def list_global_attributes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    input_type: Optional[str] = Query(None, description="Filter by input type"),
) -> List[GlobalAttributeListOut]:
    """List all global attributes."""
    query = db.query(GlobalAttribute)

    if input_type:
        query = query.filter(GlobalAttribute.input_type == input_type)

    attrs = query.order_by(GlobalAttribute.display_name).all()
    return [_serialize_attribute_list(attr, db) for attr in attrs]


@admin_global_attributes_router.get("/{attr_id}", response_model=GlobalAttributeOut)
def get_global_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Get a specific global attribute by ID, including all options."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")
    return _serialize_attribute(attr, db)


@admin_global_attributes_router.post("", response_model=GlobalAttributeOut, status_code=201)
def create_global_attribute(
    payload: GlobalAttributeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Create a new global attribute."""
    # Check for duplicate slug
    existing = db.query(GlobalAttribute).filter(
        GlobalAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Global attribute with slug '{payload.slug}' already exists"
        )

    attr = GlobalAttribute(
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        description=payload.description,
    )
    db.add(attr)
    db.commit()
    db.refresh(attr)

    logger.info("Created global attribute: %s (id=%d)", attr.slug, attr.id)
    return _serialize_attribute(attr, db)


@admin_global_attributes_router.post(
    "/with-options",
    response_model=GlobalAttributeOut,
    status_code=201,
    summary="Create attribute with options"
)
def create_global_attribute_with_options(
    payload: GlobalAttributeWithOptionsCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Create a new global attribute with options in one call."""
    # Check for duplicate slug
    existing = db.query(GlobalAttribute).filter(
        GlobalAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Global attribute with slug '{payload.slug}' already exists"
        )

    attr = GlobalAttribute(
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        description=payload.description,
    )
    db.add(attr)
    db.flush()  # Get the ID

    # Add options
    for i, opt_data in enumerate(payload.options):
        option = GlobalAttributeOption(
            global_attribute_id=attr.id,
            slug=opt_data.slug,
            display_name=opt_data.display_name,
            price_modifier=opt_data.price_modifier,
            iced_price_modifier=opt_data.iced_price_modifier,
            is_default=opt_data.is_default,
            is_available=opt_data.is_available,
            display_order=opt_data.display_order if opt_data.display_order else i,
        )
        db.add(option)

    db.commit()
    db.refresh(attr)

    logger.info(
        "Created global attribute: %s with %d options (id=%d)",
        attr.slug,
        len(payload.options),
        attr.id
    )
    return _serialize_attribute(attr, db)


@admin_global_attributes_router.put("/{attr_id}", response_model=GlobalAttributeOut)
def update_global_attribute(
    attr_id: int,
    payload: GlobalAttributeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Update a global attribute."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Check for duplicate slug if changing
    if payload.slug is not None and payload.slug != attr.slug:
        existing = db.query(GlobalAttribute).filter(
            GlobalAttribute.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Global attribute with slug '{payload.slug}' already exists"
            )

    # Apply updates
    if payload.slug is not None:
        attr.slug = payload.slug
    if payload.display_name is not None:
        attr.display_name = payload.display_name
    if payload.input_type is not None:
        attr.input_type = payload.input_type
    if payload.description is not None:
        attr.description = payload.description

    db.commit()
    db.refresh(attr)

    logger.info("Updated global attribute: %s (id=%d)", attr.slug, attr.id)
    return _serialize_attribute(attr, db)


@admin_global_attributes_router.delete("/{attr_id}", status_code=204)
def delete_global_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a global attribute (and all its options)."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Check if any item types are using this attribute
    link_count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.global_attribute_id == attr_id
    ).count()
    if link_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {link_count} item type(s) are using this attribute. "
                   "Unlink them first."
        )

    logger.info("Deleting global attribute: %s (id=%d)", attr.slug, attr.id)
    db.delete(attr)
    db.commit()
    return None


# =============================================================================
# Global Attribute Option Endpoints
# =============================================================================

@admin_global_attributes_router.get(
    "/{attr_id}/options",
    response_model=List[GlobalAttributeOptionOut],
    summary="List options for an attribute"
)
def list_global_attribute_options(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[GlobalAttributeOptionOut]:
    """List all options for a global attribute."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    return [_serialize_option(opt) for opt in attr.options]


@admin_global_attributes_router.post(
    "/{attr_id}/options",
    response_model=GlobalAttributeOptionOut,
    status_code=201,
    summary="Add an option to an attribute"
)
def create_global_attribute_option(
    attr_id: int,
    payload: GlobalAttributeOptionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOptionOut:
    """Add a new option to a global attribute."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Check for duplicate slug
    existing = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Option with slug '{payload.slug}' already exists for this attribute"
        )

    option = GlobalAttributeOption(
        global_attribute_id=attr_id,
        slug=payload.slug,
        display_name=payload.display_name,
        price_modifier=payload.price_modifier,
        iced_price_modifier=payload.iced_price_modifier,
        is_default=payload.is_default,
        is_available=payload.is_available,
        display_order=payload.display_order,
    )
    db.add(option)
    db.commit()
    db.refresh(option)

    logger.info(
        "Created global attribute option: %s for %s (id=%d)",
        option.slug,
        attr.slug,
        option.id
    )
    return _serialize_option(option)


@admin_global_attributes_router.put(
    "/{attr_id}/options/{option_id}",
    response_model=GlobalAttributeOptionOut,
    summary="Update an option"
)
def update_global_attribute_option(
    attr_id: int,
    option_id: int,
    payload: GlobalAttributeOptionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOptionOut:
    """Update a global attribute option."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Check for duplicate slug if changing
    if payload.slug is not None and payload.slug != option.slug:
        existing = db.query(GlobalAttributeOption).filter(
            GlobalAttributeOption.global_attribute_id == attr_id,
            GlobalAttributeOption.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Option with slug '{payload.slug}' already exists"
            )

    # Apply updates
    if payload.slug is not None:
        option.slug = payload.slug
    if payload.display_name is not None:
        option.display_name = payload.display_name
    if payload.price_modifier is not None:
        option.price_modifier = payload.price_modifier
    if payload.iced_price_modifier is not None:
        option.iced_price_modifier = payload.iced_price_modifier
    if payload.is_default is not None:
        option.is_default = payload.is_default
    if payload.is_available is not None:
        option.is_available = payload.is_available
    if payload.display_order is not None:
        option.display_order = payload.display_order

    db.commit()
    db.refresh(option)

    logger.info("Updated global attribute option: %s (id=%d)", option.slug, option.id)
    return _serialize_option(option)


@admin_global_attributes_router.delete(
    "/{attr_id}/options/{option_id}",
    status_code=204,
    summary="Delete an option"
)
def delete_global_attribute_option(
    attr_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a global attribute option."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    logger.info(
        "Deleting global attribute option: %s from %s (id=%d)",
        option.slug,
        attr.slug,
        option.id
    )
    db.delete(option)
    db.commit()
    return None


# =============================================================================
# Item Type Global Attribute Link Endpoints
# =============================================================================

@admin_item_type_global_attrs_router.get(
    "/{item_type_id}/global-attributes",
    response_model=List[ItemTypeGlobalAttributeOut],
    summary="List global attributes linked to item type"
)
def list_item_type_global_attributes(
    item_type_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ItemTypeGlobalAttributeOut]:
    """List all global attributes linked to an item type."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    links = (
        db.query(ItemTypeGlobalAttribute)
        .filter(ItemTypeGlobalAttribute.item_type_id == item_type_id)
        .order_by(ItemTypeGlobalAttribute.display_order)
        .all()
    )

    return [_serialize_item_type_link(link, db) for link in links]


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
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    global_attr = db.query(GlobalAttribute).filter(
        GlobalAttribute.id == payload.global_attribute_id
    ).first()
    if not global_attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

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
        question_text=payload.question_text,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
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
    return _serialize_item_type_link(link, db)


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
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

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
    if payload.question_text is not None:
        link.question_text = payload.question_text
    if payload.min_selections is not None:
        link.min_selections = payload.min_selections
    if payload.max_selections is not None:
        link.max_selections = payload.max_selections

    db.commit()
    db.refresh(link)

    logger.info(
        "Updated global attribute link for %s on %s (link_id=%d)",
        link.global_attribute.slug,
        item_type.slug,
        link.id
    )
    return _serialize_item_type_link(link, db)


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
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

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
