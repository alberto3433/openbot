"""
Admin Stores Routes for Sandwich Bot
=====================================

This module contains admin endpoints for managing store locations. Each store
represents a physical restaurant location with its own address, hours, tax
rates, and delivery zones.

Endpoints:
----------
- GET /admin/stores: List all stores
- POST /admin/stores: Create a new store
- GET /admin/stores/{id}: Get store details
- PUT /admin/stores/{id}: Update a store
- DELETE /admin/stores/{id}: Soft-delete a store
- POST /admin/stores/{id}/restore: Restore a deleted store

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Multi-Tenant Architecture:
--------------------------
Each store location can have:
- Unique address, phone, and operating hours
- Different tax rates (city and state)
- Custom delivery zones (by zip code)
- Independent 86 status for ingredients/items
- Separate order and analytics tracking

Store Status:
-------------
- "open": Operating normally
- "closed": Temporarily closed
- Soft-deleted stores have deleted_at timestamp set

Soft Delete:
------------
Stores are soft-deleted (deleted_at set) rather than removed from the
database. This preserves order history and allows restoration.

Tax Configuration:
------------------
Each store has city_tax_rate and state_tax_rate as decimals.
Example: 0.045 = 4.5% tax rate

Delivery Zones:
---------------
delivery_zip_codes is a list of zip codes the store delivers to.
Used to validate delivery addresses during checkout.

Usage:
------
    # Create a new store
    POST /admin/stores
    {
        "name": "Downtown Location",
        "address": "123 Main St",
        "city": "New York",
        "state": "NY",
        "zip_code": "10001",
        "phone": "212-555-0100",
        "city_tax_rate": 0.045,
        "state_tax_rate": 0.04
    }
"""

import logging
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import Store
from ..schemas.stores import StoreOut, StoreCreate, StoreUpdate


logger = logging.getLogger(__name__)

# Router definition
admin_stores_router = APIRouter(prefix="/admin/stores", tags=["Admin - Stores"])


# =============================================================================
# Store Endpoints
# =============================================================================

@admin_stores_router.get("", response_model=List[StoreOut])
def list_stores(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[StoreOut]:
    """List all stores including soft-deleted ones."""
    stores = db.query(Store).order_by(Store.name).all()
    return [StoreOut.model_validate(s) for s in stores]


@admin_stores_router.post("", response_model=StoreOut, status_code=201)
def create_store(
    payload: StoreCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Create a new store location."""
    # Generate unique store_id
    store_id = f"store_{uuid.uuid4().hex[:8]}"

    store = Store(
        store_id=store_id,
        name=payload.name,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        zip_code=payload.zip_code,
        phone=payload.phone,
        hours=payload.hours,
        timezone=payload.timezone,
        status=payload.status,
        payment_methods=payload.payment_methods,
        city_tax_rate=payload.city_tax_rate,
        state_tax_rate=payload.state_tax_rate,
        delivery_zip_codes=payload.delivery_zip_codes,
    )
    db.add(store)
    db.commit()
    db.refresh(store)
    logger.info("Created store: %s (id=%s)", store.name, store.store_id)
    return StoreOut.model_validate(store)


@admin_stores_router.get("/{store_id}", response_model=StoreOut)
def get_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Get a specific store by ID."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")
    return StoreOut.model_validate(store)


@admin_stores_router.put("/{store_id}", response_model=StoreOut)
def update_store(
    store_id: str,
    payload: StoreUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Update a store's information."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    if payload.name is not None:
        store.name = payload.name
    if payload.address is not None:
        store.address = payload.address
    if payload.city is not None:
        store.city = payload.city
    if payload.state is not None:
        store.state = payload.state
    if payload.zip_code is not None:
        store.zip_code = payload.zip_code
    if payload.phone is not None:
        store.phone = payload.phone
    if payload.hours is not None:
        store.hours = payload.hours
    if payload.timezone is not None:
        store.timezone = payload.timezone
    if payload.status is not None:
        store.status = payload.status
    if payload.payment_methods is not None:
        store.payment_methods = payload.payment_methods
    if payload.city_tax_rate is not None:
        store.city_tax_rate = payload.city_tax_rate
    if payload.state_tax_rate is not None:
        store.state_tax_rate = payload.state_tax_rate
    if payload.delivery_zip_codes is not None:
        store.delivery_zip_codes = payload.delivery_zip_codes

    db.commit()
    db.refresh(store)
    logger.info("Updated store: %s (id=%s)", store.name, store.store_id)
    return StoreOut.model_validate(store)


@admin_stores_router.delete("/{store_id}", status_code=204)
def delete_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Soft-delete a store (sets deleted_at timestamp)."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.deleted_at = datetime.utcnow()
    store.status = "deleted"
    db.commit()
    logger.info("Soft-deleted store: %s (id=%s)", store.name, store.store_id)
    return None


@admin_stores_router.post("/{store_id}/restore", response_model=StoreOut)
def restore_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Restore a soft-deleted store."""
    store = db.query(Store).filter(Store.store_id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Store not found")

    store.deleted_at = None
    store.status = "open"
    db.commit()
    db.refresh(store)
    logger.info("Restored store: %s (id=%s)", store.name, store.store_id)
    return StoreOut.model_validate(store)
