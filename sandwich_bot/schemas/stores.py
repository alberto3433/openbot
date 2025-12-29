"""
Store Schemas for Sandwich Bot
==============================

This module defines Pydantic models for store/location management. Stores
represent physical restaurant locations in a multi-tenant setup, each with
its own address, hours, tax rates, and delivery zones.

Endpoint Coverage:
------------------
- GET /admin/stores: List all stores (admin)
- POST /admin/stores: Create a new store (admin)
- GET /admin/stores/{id}: Get store details (admin)
- PUT /admin/stores/{id}: Update a store (admin)
- DELETE /admin/stores/{id}: Soft-delete a store (admin)
- POST /admin/stores/{id}/restore: Restore a deleted store (admin)
- GET /stores: List active stores (public, for customer store selection)

Multi-Tenant Architecture:
--------------------------
The system supports multiple store locations under one company. Each store:
- Has its own address, phone, and hours
- Can have different tax rates (city + state)
- Defines its own delivery zones (by zip code)
- Can 86 items independently of other stores
- Tracks orders and analytics separately

Store Status:
-------------
- "open": Store is operating normally
- "closed": Store is temporarily closed
- "deleted": Soft-deleted (hidden but recoverable)

Tax Configuration:
------------------
Each store has:
- city_tax_rate: Local/city tax percentage (e.g., 0.04 for 4%)
- state_tax_rate: State tax percentage (e.g., 0.0625 for 6.25%)

These are applied to order totals during checkout.

Delivery Zones:
---------------
delivery_zip_codes contains a list of zip codes that the store delivers to.
Used by the chatbot to validate delivery addresses and by the checkout
flow to determine if delivery is available.

Payment Methods:
----------------
payment_methods lists accepted payment types (cash, credit, etc.).
Displayed to customers during checkout.

Timezone:
---------
The timezone field (e.g., "America/New_York") is used for:
- Displaying hours in local time
- Scheduling pickups
- Analytics time bucketing

Usage:
------
    # Create a new store
    new_store = StoreCreate(
        name="Downtown Location",
        address="123 Main St",
        city="New York",
        state="NY",
        zip_code="10001",
        phone="212-555-0100",
        city_tax_rate=0.045,
        state_tax_rate=0.04,
        delivery_zip_codes=["10001", "10002", "10003"]
    )
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class StoreOut(BaseModel):
    """
    Response model for store data.

    Complete store information including address, hours, tax rates,
    and delivery configuration.

    Attributes:
        id: Database primary key
        store_id: Unique string identifier (e.g., "store_nyc_001")
        name: Display name (e.g., "Downtown Location")
        address: Street address
        city: City name
        state: State abbreviation
        zip_code: Postal code
        phone: Contact phone number
        hours: Operating hours description
        timezone: IANA timezone (e.g., "America/New_York")
        status: Current status (open, closed, deleted)
        payment_methods: Accepted payment types
        city_tax_rate: Local tax rate as decimal (0.045 = 4.5%)
        state_tax_rate: State tax rate as decimal
        delivery_zip_codes: Zip codes this store delivers to
        deleted_at: When store was soft-deleted (null if active)
        created_at: When store was created
        updated_at: When store was last updated
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    hours: Optional[str] = None
    timezone: str = "America/New_York"
    status: str
    payment_methods: List[str] = []
    city_tax_rate: float = 0.0
    state_tax_rate: float = 0.0
    delivery_zip_codes: List[str] = []
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StoreCreate(BaseModel):
    """
    Request model for creating a new store.

    Required fields: name, address, city, state, zip_code, phone.
    Other fields have sensible defaults.

    Attributes:
        name: Display name (required)
        address: Street address (required)
        city: City name (required)
        state: State abbreviation (required)
        zip_code: Postal code (required)
        phone: Contact phone (required)
        hours: Operating hours description
        timezone: IANA timezone (default: America/New_York)
        status: Initial status (default: open)
        payment_methods: Accepted payments (default: cash, credit)
        city_tax_rate: Local tax rate (default: 0)
        state_tax_rate: State tax rate (default: 0)
        delivery_zip_codes: Delivery zones (default: empty)

    Example:
        {
            "name": "Midtown Express",
            "address": "456 5th Ave",
            "city": "New York",
            "state": "NY",
            "zip_code": "10018",
            "phone": "212-555-0200",
            "hours": "Mon-Fri 7am-8pm, Sat-Sun 8am-6pm",
            "city_tax_rate": 0.045,
            "state_tax_rate": 0.04,
            "delivery_zip_codes": ["10017", "10018", "10019"]
        }
    """
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    phone: str
    hours: Optional[str] = None
    timezone: str = "America/New_York"
    status: str = "open"
    payment_methods: List[str] = ["cash", "credit"]
    city_tax_rate: float = 0.0
    state_tax_rate: float = 0.0
    delivery_zip_codes: List[str] = []


class StoreUpdate(BaseModel):
    """
    Request model for updating a store.

    All fields are optional - only provided fields will be updated.

    Attributes:
        name: New display name
        address: New street address
        city: New city
        state: New state
        zip_code: New postal code
        phone: New phone number
        hours: New hours description
        timezone: New timezone
        status: New status (open, closed)
        payment_methods: New payment methods list
        city_tax_rate: New local tax rate
        state_tax_rate: New state tax rate
        delivery_zip_codes: New delivery zones

    Example:
        # Update just the hours
        {"hours": "Mon-Sun 6am-10pm"}

        # Update tax rates
        {"city_tax_rate": 0.0475, "state_tax_rate": 0.04}
    """
    name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    hours: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[str] = None
    payment_methods: Optional[List[str]] = None
    city_tax_rate: Optional[float] = None
    state_tax_rate: Optional[float] = None
    delivery_zip_codes: Optional[List[str]] = None
