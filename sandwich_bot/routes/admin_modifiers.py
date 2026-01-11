"""
Admin Modifiers Routes for Sandwich Bot
========================================

This module contains admin endpoints for managing the menu configuration
system: Item Types and Attribute Options. This flexible system allows
configuring what options are available for different types of menu items.

Endpoints:
----------
Item Types:
- GET /admin/modifiers/item-types: List all item types
- POST /admin/modifiers/item-types: Create item type
- GET /admin/modifiers/item-types/{id}: Get item type details
- PUT /admin/modifiers/item-types/{id}: Update item type
- DELETE /admin/modifiers/item-types/{id}: Delete item type

Attribute Options:
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

2. ItemTypeAttribute (e.g., "Size", "Bread", "Milk")
   - Defines a configurable aspect of the item type
   - Managed via seeding migrations

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
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ItemType, AttributeOption, MenuItem, ItemTypeGlobalAttribute
from ..services.item_type_helpers import has_linked_attributes, has_askable_attributes
from ..schemas.modifiers import (
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
    AttributeOptionOut,
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
    """Build full ItemTypeOut response."""
    menu_item_count = db.query(MenuItem).filter(
        MenuItem.item_type_id == item_type.id
    ).count()

    # Count linked global attributes
    global_attribute_count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.item_type_id == item_type.id
    ).count()

    # Derive configurability from linked global attributes
    is_configurable = has_linked_attributes(item_type.id, db)
    skip_config = not has_askable_attributes(item_type.id, db) if is_configurable else True

    return ItemTypeOut(
        id=item_type.id,
        slug=item_type.slug,
        display_name=item_type.display_name,
        is_configurable=is_configurable,
        skip_config=skip_config,
        menu_item_count=menu_item_count,
        global_attribute_count=global_attribute_count,
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

    # Note: is_configurable and skip_config are derived from linked global attributes
    # so we don't set them from the payload anymore
    item_type = ItemType(
        slug=payload.slug,
        display_name=payload.display_name,
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
    # Note: is_configurable and skip_config are derived from linked global attributes
    # so we ignore any values provided in the payload

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
# Attribute Option Endpoints
# =============================================================================

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
