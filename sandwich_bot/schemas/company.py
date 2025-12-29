"""
Company Schemas for Sandwich Bot
=================================

This module defines Pydantic models for company-wide settings. The Company
entity represents the business as a whole, with settings that apply across
all store locations.

Endpoint Coverage:
------------------
- GET /admin/company: Get company settings (admin)
- PUT /admin/company: Update company settings (admin)
- GET /company: Get company info (public, for branding)

Company vs Store:
-----------------
- **Company**: Single record for the entire business. Contains branding,
  contact info, and bot persona settings.
- **Store**: Multiple records, one per physical location. Contains address,
  hours, and location-specific settings.

Bot Persona:
------------
The chatbot's personality is configured at the company level:
- bot_persona_name: The name the bot uses (e.g., "Sammy", "OrderBot")
- This name appears in greetings and throughout conversations
- Changing this affects all stores immediately

Primary Item Type:
------------------
Restaurants specialize in different items. The primary_item_type field
indicates what the business focuses on:
- "Sandwich" - Sandwich shop
- "Pizza" - Pizza restaurant
- "Bagel" - Bagel shop
- "Taco" - Taco restaurant

This affects:
- Default greetings and prompts
- Menu organization
- Chatbot conversation flow

Signature Item Label:
---------------------
Custom label for featured/signature items. For example:
- A bagel shop might use "speed menu bagel"
- A sandwich shop might use "signature sandwich"
- A pizza place might use "specialty pizza"

If not set, defaults to "signature {primary_item_type}s".

Usage:
------
    # Get company for branding
    company = CompanyOut.model_validate(db_company)
    greeting = f"Welcome to {company.name}!"

    # Update bot name
    update = CompanyUpdate(bot_persona_name="Ziggy")
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict


class CompanyOut(BaseModel):
    """
    Response model for company settings.

    Contains all company-wide configuration including branding,
    contact information, and bot persona settings.

    Attributes:
        id: Database primary key
        name: Company/brand name (e.g., "Zucker's Bagels")
        bot_persona_name: Name the chatbot uses (e.g., "Ziggy")
        tagline: Company tagline/slogan
        headquarters_address: Corporate address
        corporate_phone: Main phone number
        corporate_email: Main email address
        website: Company website URL
        logo_url: URL to company logo image
        business_hours: Default hours (may be overridden per-store)
        primary_item_type: Main product type (Sandwich, Pizza, etc.)
        signature_item_label: Custom label for signature items
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    bot_persona_name: str
    tagline: Optional[str] = None
    headquarters_address: Optional[str] = None
    corporate_phone: Optional[str] = None
    corporate_email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    primary_item_type: str = "Sandwich"
    signature_item_label: Optional[str] = None


class CompanyUpdate(BaseModel):
    """
    Request model for updating company settings.

    All fields are optional - only provided fields will be updated.

    Attributes:
        name: New company name
        bot_persona_name: New bot name
        tagline: New tagline
        headquarters_address: New corporate address
        corporate_phone: New phone
        corporate_email: New email
        website: New website URL
        logo_url: New logo URL
        business_hours: New default hours
        signature_item_label: New signature item label

    Example:
        # Rebrand the bot
        {
            "bot_persona_name": "Ziggy",
            "tagline": "NYC's Best Bagels Since 1999"
        }

        # Update contact info
        {
            "corporate_phone": "212-555-0000",
            "corporate_email": "hello@zuckers.com",
            "website": "https://zuckersbagels.com"
        }
    """
    name: Optional[str] = None
    bot_persona_name: Optional[str] = None
    tagline: Optional[str] = None
    headquarters_address: Optional[str] = None
    corporate_phone: Optional[str] = None
    corporate_email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    signature_item_label: Optional[str] = None
