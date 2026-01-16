"""
Admin Modifiers Routes for Sandwich Bot
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

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Structure:
----------
1. ItemType (e.g., "Bagel", "Sandwich", "Coffee")
   - Defines a category of configurable items
   - Links to menu items via MenuItem.item_type_id
   - Links to global attributes via ItemTypeGlobalAttribute

2. GlobalAttribute / GlobalAttributeOption
   - Shared attribute definitions (e.g., "Size", "Bread")
   - Options with price modifiers (e.g., "Small", "Large")
   - Linked to item types via ItemTypeGlobalAttribute junction table
   - Managed via separate admin routes (/admin/global-attributes)

Example:
--------
    ItemType: "Coffee"
    └── Linked GlobalAttributes:
        ├── "Size" (via ItemTypeGlobalAttribute)
        │   ├── Option: "Small" (+$0)
        │   ├── Option: "Medium" (+$0.50)
        │   └── Option: "Large" (+$1.00)
        └── "Milk" (via ItemTypeGlobalAttribute)
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
from ..models import ItemType, ItemTypeAlias, MenuItem, ItemTypeGlobalAttribute, ItemTypeCategory
from ..services.item_type_helpers import has_linked_attributes, has_askable_attributes
from ..services.helpers import validate_aliases
from ..schemas.modifiers import (
    ItemTypeListOut,
    ItemTypeOut,
    ItemTypeCreate,
    ItemTypeUpdate,
    ItemTypeCategoryOut,
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

    # Get category name if set
    category_name = None
    if item_type.item_type_category:
        category_name = item_type.item_type_category.display_name

    return ItemTypeOut(
        id=item_type.id,
        slug=item_type.slug,
        display_name=item_type.display_name,
        is_configurable=is_configurable,
        skip_config=skip_config,
        item_type_category_id=item_type.item_type_category_id,
        item_type_category_name=category_name,
        menu_item_count=menu_item_count,
        global_attribute_count=global_attribute_count,
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


# =============================================================================
# Item Type Category Endpoints
# =============================================================================

@admin_modifiers_router.get("/item-type-categories", response_model=List[ItemTypeCategoryOut])
def list_item_type_categories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ItemTypeCategoryOut]:
    """List all item type categories (e.g., Food, Beverage)."""
    categories = db.query(ItemTypeCategory).order_by(ItemTypeCategory.display_name).all()
    return [ItemTypeCategoryOut.model_validate(c) for c in categories]


# =============================================================================
# Item Type Endpoints
# =============================================================================

@admin_modifiers_router.get("/item-types/list", response_model=List[ItemTypeListOut])
def list_item_types_minimal(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[ItemTypeListOut]:
    """Lightweight list for sidebar - no counts, no derived fields."""
    item_types = db.query(ItemType).order_by(ItemType.display_name).all()
    return [
        ItemTypeListOut(id=it.id, slug=it.slug, display_name=it.display_name)
        for it in item_types
    ]


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

    # Validate category ID if provided
    if payload.item_type_category_id is not None:
        category = db.query(ItemTypeCategory).filter(
            ItemTypeCategory.id == payload.item_type_category_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Item type category with id {payload.item_type_category_id} not found"
            )

    # Note: is_configurable and skip_config are derived from linked global attributes
    # so we don't set them from the payload anymore
    item_type = ItemType(
        slug=payload.slug,
        display_name=payload.display_name,
        item_type_category_id=payload.item_type_category_id,
    )
    db.add(item_type)
    db.flush()  # Get the item ID before adding aliases

    # Add aliases if provided
    if payload.aliases is not None:
        _set_item_type_aliases(db, item_type, payload.aliases)

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
    if payload.item_type_category_id is not None:
        # Validate category ID
        category = db.query(ItemTypeCategory).filter(
            ItemTypeCategory.id == payload.item_type_category_id
        ).first()
        if not category:
            raise HTTPException(
                status_code=400,
                detail=f"Item type category with id {payload.item_type_category_id} not found"
            )
        item_type.item_type_category_id = payload.item_type_category_id
    if payload.aliases is not None:
        _set_item_type_aliases(db, item_type, payload.aliases)
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
