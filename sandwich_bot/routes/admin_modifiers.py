"""
Admin Modifiers Routes for Sandwich Bot
========================================

This module contains admin endpoints for managing the menu configuration
system: Item Types, Attribute Definitions, and Attribute Options. This
flexible system allows configuring what options are available for different
types of menu items.

Endpoints:
----------
Item Types:
- GET /admin/modifiers/item-types: List all item types
- POST /admin/modifiers/item-types: Create item type
- GET /admin/modifiers/item-types/{id}: Get item type details
- PUT /admin/modifiers/item-types/{id}: Update item type
- DELETE /admin/modifiers/item-types/{id}: Delete item type

Attribute Definitions:
- POST /admin/modifiers/item-types/{id}/attributes: Add attribute
- PUT /admin/modifiers/attributes/{id}: Update attribute
- DELETE /admin/modifiers/attributes/{id}: Delete attribute

Attribute Options:
- POST /admin/modifiers/attributes/{id}/options: Add option
- PUT /admin/modifiers/options/{id}: Update option
- DELETE /admin/modifiers/options/{id}: Delete option

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Hierarchical Structure:
-----------------------
1. ItemType (e.g., "Bagel", "Sandwich", "Coffee")
   - Defines a category of configurable items
   - Links to menu items via MenuItem.item_type_id

2. AttributeDefinition (e.g., "Size", "Bread", "Milk")
   - Defines a configurable aspect of the item type
   - Specifies input type (single_select, multi_select)

3. AttributeOption (e.g., "Small", "Medium", "Large")
   - Individual choices for an attribute
   - Can have price modifiers

Example:
--------
    ItemType: "Coffee"
    ├── Attribute: "Size"
    │   ├── Option: "Small" (+$0)
    │   ├── Option: "Medium" (+$0.50)
    │   └── Option: "Large" (+$1.00)
    └── Attribute: "Milk"
        ├── Option: "None" (default)
        ├── Option: "Whole"
        └── Option: "Oat" (+$0.75)

Usage:
------
    # Create a size attribute for coffees
    POST /admin/modifiers/item-types/1/attributes
    {
        "slug": "size",
        "display_name": "Size",
        "input_type": "single_select",
        "is_required": true
    }
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ItemType, AttributeDefinition, AttributeOption, MenuItem
from ..schemas.modifiers import (
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
    AttributeDefinitionOut,
    AttributeDefinitionCreate,
    AttributeDefinitionUpdate,
    AttributeOptionOut,
    AttributeOptionCreate,
    AttributeOptionUpdate,
)


logger = logging.getLogger(__name__)

# Router definition
admin_modifiers_router = APIRouter(
    prefix="/admin/modifiers",
    tags=["Admin - Modifiers"]
)


# =============================================================================
# Helper Functions
# =============================================================================

def build_item_type_response(item_type: ItemType, db: Session) -> ItemTypeOut:
    """Build full ItemTypeOut with nested attributes and options."""
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item_type.id
    ).count()

    attributes = []
    for attr in item_type.attribute_definitions:
        options = [AttributeOptionOut.model_validate(opt) for opt in attr.options]
        attributes.append(AttributeDefinitionOut(
            id=attr.id,
            slug=attr.slug,
            display_name=attr.display_name,
            input_type=attr.input_type,
            is_required=attr.is_required,
            allow_none=attr.allow_none,
            min_selections=attr.min_selections,
            max_selections=attr.max_selections,
            display_order=attr.display_order,
            options=options,
        ))

    return ItemTypeOut(
        id=item_type.id,
        slug=item_type.slug,
        display_name=item_type.display_name,
        is_configurable=item_type.is_configurable,
        skip_config=item_type.skip_config,
        attribute_definitions=attributes,
        menu_item_count=menu_item_count,
    )


# =============================================================================
# Item Type Endpoints
# =============================================================================

@admin_modifiers_router.get("/item-types", response_model=List[ItemTypeOut])
def list_item_types(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ItemTypeOut]:
    """List all item types with their attributes and options."""
    item_types = db.query(ItemType).order_by(ItemType.display_name).all()
    return [build_item_type_response(it, db) for it in item_types]


@admin_modifiers_router.post("/item-types", response_model=ItemTypeOut, status_code=201)
def create_item_type(
    payload: ItemTypeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeOut:
    """Create a new item type."""
    existing = db.query(ItemType).filter(ItemType.slug == payload.slug).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Item type '{payload.slug}' already exists")

    item_type = ItemType(
        slug=payload.slug,
        display_name=payload.display_name,
        is_configurable=payload.is_configurable,
        skip_config=payload.skip_config,
    )
    db.add(item_type)
    db.commit()
    db.refresh(item_type)
    logger.info("Created item type: %s", item_type.slug)
    return build_item_type_response(item_type, db)


@admin_modifiers_router.get("/item-types/{item_type_id}", response_model=ItemTypeOut)
def get_item_type(
    item_type_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeOut:
    """Get a specific item type with attributes and options."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")
    return build_item_type_response(item_type, db)


@admin_modifiers_router.put("/item-types/{item_type_id}", response_model=ItemTypeOut)
def update_item_type(
    item_type_id: int,
    payload: ItemTypeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeOut:
    """Update an item type."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    if payload.slug is not None:
        item_type.slug = payload.slug
    if payload.display_name is not None:
        item_type.display_name = payload.display_name
    if payload.is_configurable is not None:
        item_type.is_configurable = payload.is_configurable
    if payload.skip_config is not None:
        item_type.skip_config = payload.skip_config

    db.commit()
    db.refresh(item_type)
    logger.info("Updated item type: %s", item_type.slug)
    return build_item_type_response(item_type, db)


@admin_modifiers_router.delete("/item-types/{item_type_id}", status_code=204)
def delete_item_type(
    item_type_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an item type and its attributes/options."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    # Check if any menu items use this type
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item_type_id
    ).count()
    if menu_item_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {menu_item_count} menu items use this type"
        )

    logger.info("Deleting item type: %s", item_type.slug)
    db.delete(item_type)
    db.commit()
    return None


# =============================================================================
# Attribute Definition Endpoints
# =============================================================================

@admin_modifiers_router.post("/item-types/{item_type_id}/attributes", response_model=AttributeDefinitionOut, status_code=201)
def create_attribute(
    item_type_id: int,
    payload: AttributeDefinitionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeDefinitionOut:
    """Add an attribute to an item type."""
    item_type = db.query(ItemType).filter(ItemType.id == item_type_id).first()
    if not item_type:
        raise HTTPException(status_code=404, detail="Item type not found")

    attribute = AttributeDefinition(
        item_type_id=item_type_id,
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        is_required=payload.is_required,
        allow_none=payload.allow_none,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        display_order=payload.display_order,
    )
    db.add(attribute)
    db.commit()
    db.refresh(attribute)
    logger.info("Created attribute: %s for item type %s", attribute.slug, item_type.slug)

    return AttributeDefinitionOut(
        id=attribute.id,
        slug=attribute.slug,
        display_name=attribute.display_name,
        input_type=attribute.input_type,
        is_required=attribute.is_required,
        allow_none=attribute.allow_none,
        min_selections=attribute.min_selections,
        max_selections=attribute.max_selections,
        display_order=attribute.display_order,
        options=[],
    )


@admin_modifiers_router.put("/attributes/{attribute_id}", response_model=AttributeDefinitionOut)
def update_attribute(
    attribute_id: int,
    payload: AttributeDefinitionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeDefinitionOut:
    """Update an attribute definition."""
    attribute = db.query(AttributeDefinition).filter(
        AttributeDefinition.id == attribute_id
    ).first()
    if not attribute:
        raise HTTPException(status_code=404, detail="Attribute not found")

    if payload.slug is not None:
        attribute.slug = payload.slug
    if payload.display_name is not None:
        attribute.display_name = payload.display_name
    if payload.input_type is not None:
        attribute.input_type = payload.input_type
    if payload.is_required is not None:
        attribute.is_required = payload.is_required
    if payload.allow_none is not None:
        attribute.allow_none = payload.allow_none
    if payload.min_selections is not None:
        attribute.min_selections = payload.min_selections
    if payload.max_selections is not None:
        attribute.max_selections = payload.max_selections
    if payload.display_order is not None:
        attribute.display_order = payload.display_order

    db.commit()
    db.refresh(attribute)
    logger.info("Updated attribute: %s", attribute.slug)

    options = [AttributeOptionOut.model_validate(opt) for opt in attribute.options]
    return AttributeDefinitionOut(
        id=attribute.id,
        slug=attribute.slug,
        display_name=attribute.display_name,
        input_type=attribute.input_type,
        is_required=attribute.is_required,
        allow_none=attribute.allow_none,
        min_selections=attribute.min_selections,
        max_selections=attribute.max_selections,
        display_order=attribute.display_order,
        options=options,
    )


@admin_modifiers_router.delete("/attributes/{attribute_id}", status_code=204)
def delete_attribute(
    attribute_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an attribute and its options."""
    attribute = db.query(AttributeDefinition).filter(
        AttributeDefinition.id == attribute_id
    ).first()
    if not attribute:
        raise HTTPException(status_code=404, detail="Attribute not found")

    logger.info("Deleting attribute: %s", attribute.slug)
    db.delete(attribute)
    db.commit()
    return None


# =============================================================================
# Attribute Option Endpoints
# =============================================================================

@admin_modifiers_router.post("/attributes/{attribute_id}/options", response_model=AttributeOptionOut, status_code=201)
def create_option(
    attribute_id: int,
    payload: AttributeOptionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeOptionOut:
    """Add an option to an attribute."""
    attribute = db.query(AttributeDefinition).filter(
        AttributeDefinition.id == attribute_id
    ).first()
    if not attribute:
        raise HTTPException(status_code=404, detail="Attribute not found")

    option = AttributeOption(
        attribute_id=attribute_id,
        slug=payload.slug,
        display_name=payload.display_name,
        price_modifier=payload.price_modifier,
        is_default=payload.is_default,
        is_available=payload.is_available,
        display_order=payload.display_order,
    )
    db.add(option)
    db.commit()
    db.refresh(option)
    logger.info("Created option: %s for attribute %s", option.slug, attribute.slug)
    return AttributeOptionOut.model_validate(option)


@admin_modifiers_router.put("/options/{option_id}", response_model=AttributeOptionOut)
def update_option(
    option_id: int,
    payload: AttributeOptionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeOptionOut:
    """Update an attribute option."""
    option = db.query(AttributeOption).filter(AttributeOption.id == option_id).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    if payload.slug is not None:
        option.slug = payload.slug
    if payload.display_name is not None:
        option.display_name = payload.display_name
    if payload.price_modifier is not None:
        option.price_modifier = payload.price_modifier
    if payload.is_default is not None:
        option.is_default = payload.is_default
    if payload.is_available is not None:
        option.is_available = payload.is_available
    if payload.display_order is not None:
        option.display_order = payload.display_order

    db.commit()
    db.refresh(option)
    logger.info("Updated option: %s", option.slug)
    return AttributeOptionOut.model_validate(option)


@admin_modifiers_router.delete("/options/{option_id}", status_code=204)
def delete_option(
    option_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an attribute option."""
    option = db.query(AttributeOption).filter(AttributeOption.id == option_id).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    logger.info("Deleting option: %s", option.slug)
    db.delete(option)
    db.commit()
    return None
