"""
Public Routes for Sandwich Bot
==============================

This module contains public endpoints that don't require authentication.
These provide information needed by customer-facing interfaces.

Endpoints:
----------
- GET /stores: List active store locations
- GET /company: Get company branding information

No Authentication:
------------------
These endpoints are intentionally public to support:
- Store selector in the chat widget
- Branding display in customer UI
- Location information for customers

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
"""

import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Store, Company
from ..schemas.stores import StoreOut
from ..schemas.company import CompanyOut


logger = logging.getLogger(__name__)

# Router definitions
public_stores_router = APIRouter(prefix="/stores", tags=["Stores"])
public_company_router = APIRouter(prefix="/company", tags=["Company"])


# =============================================================================
# Helper Functions
# =============================================================================

def get_or_create_company(db: Session) -> Company:
    """Get the company record or create a default one."""
    company = db.query(Company).first()
    if not company:
        company = Company(
            name="OrderBot Restaurant",
            bot_persona_name="OrderBot",
        )
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


# =============================================================================
# Public Store Endpoints
# =============================================================================

@public_stores_router.get("", response_model=List[StoreOut])
def list_public_stores(
    db: Session = Depends(get_db),
) -> List[StoreOut]:
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
