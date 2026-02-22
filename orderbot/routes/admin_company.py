"""
Admin Company Routes for Orderbot
======================================

This module contains admin endpoints for managing company-wide settings.
The Company entity represents the business as a whole with settings that
apply across all store locations.

Endpoints:
----------
- GET /admin/company: Get company settings
- PUT /admin/company: Update company settings

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Company Settings:
-----------------
The company record includes:
- name: Business/brand name
- bot_persona_name: Name the chatbot uses (e.g., "Sammy", "Ziggy")
- tagline: Company slogan
- Contact information (address, phone, email, website)
- logo_url: URL to company logo
- business_hours: Default operating hours
- signature_item_label: Custom label for featured items

Bot Persona:
------------
The bot_persona_name affects how the chatbot introduces itself and signs
messages. Changing this updates the experience across all channels.

Single Record:
--------------
There is only one Company record per deployment. The GET endpoint returns
it (creating a default if none exists) and PUT updates it.

Usage:
------
    # Update bot persona
    PUT /admin/company
    {
        "bot_persona_name": "Ziggy",
        "tagline": "NYC's Best Bagels"
    }
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..schemas.company import CompanyOut, CompanyUpdate
from ..services.store_service import get_or_create_company
from .crud_helpers import apply_payload_updates


logger = logging.getLogger(__name__)

# Router definition
admin_company_router = APIRouter(prefix="/admin/company", tags=["Admin - Company"])


# =============================================================================
# Company Endpoints
# =============================================================================

@admin_company_router.get("", response_model=CompanyOut)
def get_company(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CompanyOut:
    """Get company settings."""
    company = get_or_create_company(db)
    return CompanyOut.model_validate(company)


@admin_company_router.put("", response_model=CompanyOut)
def update_company(
    payload: CompanyUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> CompanyOut:
    """Update company settings."""
    company = get_or_create_company(db)

    # Track whether TTS provider is changing
    old_tts_provider = company.tts_provider

    apply_payload_updates(company, payload, db)

    db.commit()
    db.refresh(company)
    logger.info("Updated company settings: %s", company.name)

    # If TTS provider changed, invalidate and re-initialize the singleton
    if payload.tts_provider is not None and payload.tts_provider != old_tts_provider:
        from ..services.tts import invalidate_tts_provider, get_tts_provider
        invalidate_tts_provider()
        try:
            get_tts_provider(company.tts_provider)
            logger.info("TTS provider switched to: %s", company.tts_provider)
        except (ValueError, ImportError, OSError) as e:
            logger.warning("New TTS provider '%s' failed to initialize: %s", company.tts_provider, e)

    return CompanyOut.model_validate(company)
