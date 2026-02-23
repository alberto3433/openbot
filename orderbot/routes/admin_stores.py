"""
Admin Stores Routes for Orderbot
=====================================

This module contains admin endpoints for managing store locations. Each store
represents a physical restaurant location with its own address, hours, tax
rates, and delivery zones.

Endpoints:
----------
- GET /admin/stores: List all stores
- POST /admin/stores: Create a new store
- GET /admin/stores/{store_id}: Get store details
- PUT /admin/stores/{store_id}: Update a store
- DELETE /admin/stores/{store_id}: Soft-delete a store
- POST /admin/stores/{store_id}/restore: Restore a deleted store

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Soft Delete:
------------
Stores are soft-deleted (deleted_at set) rather than removed from the
database. This preserves order history and allows restoration.
"""

import logging
import uuid

from fastapi import Depends
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import Store
from ..schemas.stores import StoreOut, StoreCreate, StoreUpdate
from ..services.store_service import invalidate_store_cache
from ..utils.datetime_helpers import utc_now
from .crud_factory import CRUDRouterFactory
from .crud_helpers import apply_payload_updates, get_or_404


logger = logging.getLogger(__name__)


# =============================================================================
# Factory hooks
# =============================================================================

def _before_create(payload: StoreCreate, db: Session) -> dict:
    """Generate a unique store_id and build model kwargs from the payload."""
    kwargs = payload.model_dump()
    kwargs["store_id"] = f"store_{uuid.uuid4().hex[:8]}"
    return kwargs


def _after_create(store: Store, db: Session) -> None:
    invalidate_store_cache(store.store_id)


def _after_update(store: Store, db: Session) -> None:
    invalidate_store_cache(store.store_id)


def _before_update(store: Store, payload: StoreUpdate, db: Session) -> None:
    apply_payload_updates(store, payload, db)


# =============================================================================
# CRUD factory (handles list, create, get, update)
# =============================================================================

_crud = CRUDRouterFactory(
    model=Store,
    create_schema=StoreCreate,
    update_schema=StoreUpdate,
    response_schema=StoreOut,
    prefix="/admin/stores",
    tags=["Admin - Stores"],
    id_param="store_id",
    id_column="store_id",
    id_type=str,
    not_found_message="Store not found",
    order_by=["name"],
    on_before_create=_before_create,
    on_after_create=_after_create,
    on_before_update=_before_update,
    on_after_update=_after_update,
    skip_delete=True,  # Stores use soft-delete below
)

admin_stores_router = _crud.router


# =============================================================================
# Manual endpoints: soft-delete + restore
# =============================================================================

@admin_stores_router.delete("/{store_id}", status_code=204)
def delete_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Soft-delete a store (sets deleted_at timestamp)."""
    store = get_or_404(db, Store, store_id, id_column="store_id")
    store.deleted_at = utc_now()
    store.status = "deleted"
    db.commit()
    invalidate_store_cache(store_id)
    logger.info("Soft-deleted store: %s (id=%s)", store.name, store.store_id)


@admin_stores_router.post("/{store_id}/restore", response_model=StoreOut)
def restore_store(
    store_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> StoreOut:
    """Restore a soft-deleted store."""
    store = get_or_404(db, Store, store_id, id_column="store_id")
    store.deleted_at = None
    store.status = "open"
    db.commit()
    db.refresh(store)
    invalidate_store_cache(store_id)
    logger.info("Restored store: %s (id=%s)", store.name, store.store_id)
    return StoreOut.model_validate(store)
