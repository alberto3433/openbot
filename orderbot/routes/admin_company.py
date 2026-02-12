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

    if payload.name is not None:
        company.name = payload.name
    if payload.bot_persona_name is not None:
        company.bot_persona_name = payload.bot_persona_name
    # Use model_fields_set for clearable string fields (allows setting to null)
    if "tagline" in payload.model_fields_set:
        company.tagline = payload.tagline
    if "headquarters_address" in payload.model_fields_set:
        company.headquarters_address = payload.headquarters_address
    if "corporate_phone" in payload.model_fields_set:
        company.corporate_phone = payload.corporate_phone
    if "corporate_email" in payload.model_fields_set:
        company.corporate_email = payload.corporate_email
    if "website" in payload.model_fields_set:
        company.website = payload.website
    if "instagram_handle" in payload.model_fields_set:
        company.instagram_handle = payload.instagram_handle
    if "feedback_form_url" in payload.model_fields_set:
        company.feedback_form_url = payload.feedback_form_url
    if "logo_url" in payload.model_fields_set:
        company.logo_url = payload.logo_url
    if "business_hours" in payload.model_fields_set:
        company.business_hours = payload.business_hours
    if "signature_item_label" in payload.model_fields_set:
        company.signature_item_label = payload.signature_item_label

    # Payment Methods
    if payload.accepts_credit_cards is not None:
        company.accepts_credit_cards = payload.accepts_credit_cards
    if payload.accepts_debit_cards is not None:
        company.accepts_debit_cards = payload.accepts_debit_cards
    if payload.accepts_cash is not None:
        company.accepts_cash = payload.accepts_cash
    if payload.accepts_apple_pay is not None:
        company.accepts_apple_pay = payload.accepts_apple_pay
    if payload.accepts_google_pay is not None:
        company.accepts_google_pay = payload.accepts_google_pay
    if payload.accepts_venmo is not None:
        company.accepts_venmo = payload.accepts_venmo
    if payload.accepts_paypal is not None:
        company.accepts_paypal = payload.accepts_paypal

    # Dietary & Certification Info
    if payload.is_kosher is not None:
        company.is_kosher = payload.is_kosher
    if "kosher_certification" in payload.model_fields_set:
        company.kosher_certification = payload.kosher_certification
    if payload.is_halal is not None:
        company.is_halal = payload.is_halal
    if payload.has_vegetarian_options is not None:
        company.has_vegetarian_options = payload.has_vegetarian_options
    if payload.has_vegan_options is not None:
        company.has_vegan_options = payload.has_vegan_options
    if payload.has_gluten_free_options is not None:
        company.has_gluten_free_options = payload.has_gluten_free_options

    # Amenities
    if payload.wifi_available is not None:
        company.wifi_available = payload.wifi_available
    if payload.wheelchair_accessible is not None:
        company.wheelchair_accessible = payload.wheelchair_accessible
    if payload.outdoor_seating is not None:
        company.outdoor_seating = payload.outdoor_seating

    # Catering
    if payload.offers_catering is not None:
        company.offers_catering = payload.offers_catering
    if payload.catering_minimum_order is not None:
        company.catering_minimum_order = payload.catering_minimum_order
    if payload.catering_advance_notice_hours is not None:
        company.catering_advance_notice_hours = payload.catering_advance_notice_hours
    if "catering_phone" in payload.model_fields_set:
        company.catering_phone = payload.catering_phone
    if "catering_email" in payload.model_fields_set:
        company.catering_email = payload.catering_email

    db.commit()
    db.refresh(company)
    logger.info("Updated company settings: %s", company.name)
    return CompanyOut.model_validate(company)
