"""
Public Routes for Orderbot
==============================

This module contains public endpoints that don't require authentication.
These provide information needed by customer-facing interfaces.

Endpoints:
----------
- GET /stores: List active store locations
- GET /company: Get company branding information
- GET /menu: Full public menu with pricing and availability

No Authentication:
------------------
These endpoints are intentionally public to support:
- Store selector in the chat widget
- Branding display in customer UI
- Location information for customers
- Customer-facing menu page

Data Filtering:
---------------
These endpoints return limited data compared to admin endpoints:
- Only active (non-deleted) stores are shown
- Sensitive business information is excluded
- Only fields needed for customer display are returned

Usage:
------
    # Get list of stores for location selector
    GET /stores
    [
        {"store_id": "store_nyc_001", "name": "Downtown", ...},
        {"store_id": "store_nyc_002", "name": "Midtown", ...}
    ]

    # Get company info for branding
    GET /company
    {
        "name": "Zucker's Bagels",
        "bot_persona_name": "Ziggy",
        ...
    }

    # Get public menu
    GET /menu?store_id=store_nyc_001
    {
        "categories": [...],
        "store_id": "store_nyc_001",
        "store_name": "Downtown"
    }
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..db.models import (
    MenuItem,
    MenuItemSizePrice,
    MenuItemStoreAvailability,
    MenuDisplayGroup,
    OverallCategory,
    Store,
)
from ..schemas.stores import StoreOut
from ..schemas.company import CompanyOut
from ..schemas.public_menu import (
    PublicMenuItemOut,
    PublicMenuResponse,
    PublicOverallCategoryOut,
    PublicDisplayGroupOut,
    PublicSizePriceOut,
)
from ..services.store_service import get_or_create_company


logger = logging.getLogger(__name__)

# Router definitions
public_stores_router = APIRouter(prefix="/stores", tags=["Stores"])
public_company_router = APIRouter(prefix="/company", tags=["Company"])
public_menu_router = APIRouter(prefix="/menu", tags=["Menu"])


# =============================================================================
# Public Store Endpoints
# =============================================================================

@public_stores_router.get("", response_model=list[StoreOut])
def list_public_stores(
    db: Session = Depends(get_db),
) -> list[StoreOut]:
    """
    List active store locations (public).

    Returns only stores that are not soft-deleted.
    No authentication required - used by customer-facing store selector.
    """
    stores = db.query(Store).filter(
        Store.deleted_at.is_(None)
    ).order_by(Store.name).all()

    return [StoreOut.model_validate(s) for s in stores]


# =============================================================================
# Public Company Endpoints
# =============================================================================

@public_company_router.get("", response_model=CompanyOut)
def get_public_company(
    db: Session = Depends(get_db),
) -> CompanyOut:
    """
    Get company branding information (public).

    Returns company name, bot persona, and other branding details.
    No authentication required - used for customer UI branding.
    """
    company = get_or_create_company(db)
    return CompanyOut.model_validate(company)


# =============================================================================
# Public Menu Endpoint
# =============================================================================

@public_menu_router.get("", response_model=PublicMenuResponse)
def get_public_menu(
    store_id: Optional[str] = Query(None, description="Store ID to check item availability"),
    db: Session = Depends(get_db),
) -> PublicMenuResponse:
    """
    Get the full public menu organized by category and display group.

    Returns all menu items with pricing, dietary info, and optional
    per-store availability annotations.
    """
    # Load unavailable item IDs for the given store
    unavailable_item_ids: set[int] = set()
    store_name: str | None = None
    if store_id:
        store = db.query(Store).filter(
            Store.store_id == store_id,
            Store.deleted_at.is_(None),
        ).first()
        if store:
            store_name = store.name
        rows = db.query(MenuItemStoreAvailability.menu_item_id).filter(
            MenuItemStoreAvailability.store_id == store_id,
            MenuItemStoreAvailability.is_available.is_(False),
        ).all()
        unavailable_item_ids = {r[0] for r in rows}

    # Load all overall categories with their display groups
    overall_cats = (
        db.query(OverallCategory)
        .options(
            joinedload(OverallCategory.menu_display_groups)
            .joinedload(MenuDisplayGroup.item_types)
        )
        .order_by(OverallCategory.slug)
        .all()
    )

    # Load all menu items with size prices and their size names eagerly
    all_items = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.size_prices).joinedload(MenuItemSizePrice.size)
        )
        .filter(MenuItem.item_type_id.isnot(None))
        .all()
    )

    # Build item_type_id -> list[MenuItem] lookup
    items_by_type: dict[int, list[MenuItem]] = {}
    for item in all_items:
        items_by_type.setdefault(item.item_type_id, []).append(item)

    # Assemble hierarchical response
    categories_out: list[PublicOverallCategoryOut] = []
    for oc in overall_cats:
        groups_out: list[PublicDisplayGroupOut] = []
        # Only top-level display groups (no parent)
        top_groups = sorted(
            [g for g in oc.menu_display_groups if g.parent_id is None],
            key=lambda g: g.display_order,
        )
        for group in top_groups:
            # Collect items from all item types in this group
            group_items: list[PublicMenuItemOut] = []
            for item_type in group.item_types:
                for mi in items_by_type.get(item_type.id, []):
                    # Build size prices sorted by display_order
                    size_prices = sorted(
                        [
                            PublicSizePriceOut(
                                size_name=sp.size.name if sp.size else "Default",
                                price=sp.price,
                                display_order=sp.size.display_order if sp.size else 0,
                            )
                            for sp in mi.size_prices
                        ],
                        key=lambda sp: sp.display_order,
                    )
                    group_items.append(PublicMenuItemOut(
                        id=mi.id,
                        name=mi.name,
                        description=mi.description,
                        is_signature=mi.is_signature,
                        size_prices=size_prices,
                        is_available=mi.id not in unavailable_item_ids,
                        is_vegan=mi.is_vegan,
                        is_vegetarian=mi.is_vegetarian,
                        is_gluten_free=mi.is_gluten_free,
                        is_dairy_free=mi.is_dairy_free,
                        is_kosher=mi.is_kosher,
                        contains_eggs=mi.contains_eggs,
                        contains_fish=mi.contains_fish,
                        contains_sesame=mi.contains_sesame,
                        contains_nuts=mi.contains_nuts,
                    ))

            if not group_items:
                continue

            # Sort: signature first, then alphabetical
            group_items.sort(key=lambda i: (not i.is_signature, i.name))

            groups_out.append(PublicDisplayGroupOut(
                slug=group.slug,
                display_name=group.display_name,
                display_order=group.display_order,
                items=group_items,
            ))

        if not groups_out:
            continue

        categories_out.append(PublicOverallCategoryOut(
            slug=oc.slug,
            display_name=oc.display_name,
            display_groups=groups_out,
        ))

    return PublicMenuResponse(
        categories=categories_out,
        store_id=store_id,
        store_name=store_name,
    )
