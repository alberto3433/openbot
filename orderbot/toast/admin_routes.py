"""
Toast Admin Routes
=======================

CRUD endpoints for managing Toast GUID mappings at /admin/toast/mappings.
Protected by admin authentication.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models.toast import ToastGuidMap
from ..db.models.menu import MenuItem
from ..db.models.ingredients import Ingredient

logger = logging.getLogger(__name__)

toast_admin_router = APIRouter(
    prefix="/admin/toast",
    tags=["Admin - Toast POS"],
    dependencies=[Depends(verify_admin_credentials)],
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class GuidMappingCreate(BaseModel):
    entity_type: str
    local_id: int
    toast_guid: str
    toast_name: Optional[str] = None
    store_id: Optional[str] = None


class GuidMappingUpdate(BaseModel):
    toast_guid: Optional[str] = None
    toast_name: Optional[str] = None
    store_id: Optional[str] = None


class GuidMappingResponse(BaseModel):
    id: int
    entity_type: str
    local_id: int
    toast_guid: str
    toast_name: Optional[str]
    store_id: Optional[str]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------

@toast_admin_router.get("/mappings", response_model=List[GuidMappingResponse])
def list_mappings(
    entity_type: Optional[str] = Query(None),
    store_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """List all Toast GUID mappings, optionally filtered by type/store."""
    query = db.query(ToastGuidMap)
    if entity_type:
        query = query.filter(ToastGuidMap.entity_type == entity_type)
    if store_id:
        query = query.filter(ToastGuidMap.store_id == store_id)
    return query.order_by(ToastGuidMap.entity_type, ToastGuidMap.local_id).all()


@toast_admin_router.post("/mappings", response_model=GuidMappingResponse, status_code=201)
def create_mapping(
    data: GuidMappingCreate,
    db: Session = Depends(get_db),
):
    """Create a new Toast GUID mapping."""
    # Check for duplicate
    existing = (
        db.query(ToastGuidMap)
        .filter(
            ToastGuidMap.entity_type == data.entity_type,
            ToastGuidMap.local_id == data.local_id,
            ToastGuidMap.store_id == data.store_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Mapping already exists for {data.entity_type}:{data.local_id} "
                   f"(store: {data.store_id})",
        )

    mapping = ToastGuidMap(
        entity_type=data.entity_type,
        local_id=data.local_id,
        toast_guid=data.toast_guid,
        toast_name=data.toast_name,
        store_id=data.store_id,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


@toast_admin_router.put("/mappings/{mapping_id}", response_model=GuidMappingResponse)
def update_mapping(
    mapping_id: int,
    data: GuidMappingUpdate,
    db: Session = Depends(get_db),
):
    """Update an existing Toast GUID mapping."""
    mapping = db.get(ToastGuidMap, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    if data.toast_guid is not None:
        mapping.toast_guid = data.toast_guid
    if data.toast_name is not None:
        mapping.toast_name = data.toast_name
    if data.store_id is not None:
        mapping.store_id = data.store_id

    db.commit()
    db.refresh(mapping)
    return mapping


@toast_admin_router.delete("/mappings/{mapping_id}")
def delete_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
):
    """Delete a Toast GUID mapping."""
    mapping = db.get(ToastGuidMap, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")

    db.delete(mapping)
    db.commit()
    return {"status": "deleted", "id": mapping_id}


# ---------------------------------------------------------------------------
# Diagnostic endpoints
# ---------------------------------------------------------------------------

@toast_admin_router.get("/unmapped")
def get_unmapped_items(
    store_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
) -> Dict[str, List[Dict[str, Any]]]:
    """List local menu items and ingredients without Toast GUID mappings.

    Useful for seeing what still needs to be mapped before Toast orders work.
    """
    # Get all mapped local IDs
    mapped_menu_ids = {
        row.local_id
        for row in db.query(ToastGuidMap.local_id)
        .filter(ToastGuidMap.entity_type == "menu_item")
        .all()
    }
    mapped_ingredient_ids = {
        row.local_id
        for row in db.query(ToastGuidMap.local_id)
        .filter(ToastGuidMap.entity_type == "ingredient")
        .all()
    }

    # Find unmapped menu items
    unmapped_menu = []
    for item in db.query(MenuItem).filter(MenuItem.is_available.is_(True)).all():
        if item.id not in mapped_menu_ids:
            unmapped_menu.append({
                "id": item.id,
                "name": item.name,
            })

    # Find unmapped ingredients
    unmapped_ingredients = []
    for ing in db.query(Ingredient).all():
        if ing.id not in mapped_ingredient_ids:
            unmapped_ingredients.append({
                "id": ing.id,
                "name": ing.name,
            })

    return {
        "unmapped_menu_items": unmapped_menu,
        "unmapped_ingredients": unmapped_ingredients,
        "summary": {
            "menu_items_unmapped": len(unmapped_menu),
            "ingredients_unmapped": len(unmapped_ingredients),
        },
    }


@toast_admin_router.post("/sync")
def sync_toast_menu(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Pull Toast menu and auto-match items to local menu.

    Fetches the Toast restaurant menu, then fuzzy-matches Toast item names
    to our local menu_items. Creates mappings for confident matches.
    """
    from .menu_sync import sync_menus
    return sync_menus(db)
