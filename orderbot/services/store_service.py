"""
Store Info Service
==================

Functions for store info lookup, caching, and warming.

Functions:
- get_or_create_company: Get the company record or create default
- build_store_info: Build store info dict with caching
- invalidate_store_cache: Invalidate cache after admin updates
- warmup_store_cache: Pre-warm store cache at startup
"""

import logging
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from ..db.models import Company, Store
from .store_hours import parse_hours_config, is_store_open_now, get_next_open_time_display


logger = logging.getLogger(__name__)


# =============================================================================
# Store Info Cache
# =============================================================================

_store_info_cache: dict[str, dict[str, Any]] = {}
_store_info_cache_time: dict[str, float] = {}
_STORE_CACHE_TTL = 300  # 5 minutes
_store_cache_lock = threading.Lock()


def get_or_create_company(db: Session) -> Company:
    """
    Get the company record or create a default one if none exists.

    This ensures there's always a Company record available for:
    - Bot persona name (used in LLM prompts)
    - Company branding in customer-facing UI
    - Signature item label customization

    Args:
        db: Database session

    Returns:
        The existing or newly created Company record
    """
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


def build_store_info(
    db: Session,
    store_id: str | None,
    company_name: str | None = None,
) -> dict[str, Any]:
    """
    Build store info dict with tax rates, delivery zones, and location details.

    This provides context about the store for order processing, including:
    - Tax rates for price calculations
    - Delivery zip codes for zone validation
    - Store location and contact info
    - All stores list for cross-store delivery lookup

    Uses a TTL cache to avoid repeated database queries. Cache is populated
    at startup via warmup_store_cache() and invalidated when stores are
    updated via invalidate_store_cache().

    Args:
        db: Database session
        store_id: The store ID to look up (optional)
        company_name: Fallback company name if store not found (optional,
                      will be looked up from Company table if not provided)

    Returns:
        Dict with store info including tax rates, delivery zones, and location
    """
    cache_key = store_id or "__default__"

    with _store_cache_lock:
        # Check cache first
        cached = _store_info_cache.get(cache_key)
        cache_time = _store_info_cache_time.get(cache_key, 0)
        if cached and (time.time() - cache_time) < _STORE_CACHE_TTL:
            return cached.copy()

        # Get company name if not provided
        if not company_name:
            company = db.query(Company).first()
            company_name = company.name if company else "OrderBot"

        store_info = {
            "name": company_name,
            "store_id": store_id,
            "city_tax_rate": 0.0,
            "state_tax_rate": 0.0,
            "delivery_zip_codes": [],
            # Store location and contact info
            "address": None,
            "city": None,
            "state": None,
            "zip_code": None,
            "phone": None,
            "hours": None,
            # Store hours / scheduling
            "timezone": "America/New_York",
            "is_open": True,
            "hours_config": None,
            "next_open_time": None,
            # All stores info for cross-store delivery lookup
            "all_stores": [],
        }

        if store_id:
            store = db.query(Store).filter(Store.store_id == store_id).first()
            if store:
                store_info["name"] = store.name or company_name
                store_info["city_tax_rate"] = store.city_tax_rate or 0.0
                store_info["state_tax_rate"] = store.state_tax_rate or 0.0
                store_info["delivery_zip_codes"] = store.delivery_zip_codes or []
                store_info["delivery_fee"] = store.delivery_fee if store.delivery_fee is not None else 0.0
                # Add location and contact info
                store_info["address"] = store.address
                store_info["city"] = store.city
                store_info["state"] = store.state
                store_info["zip_code"] = store.zip_code
                store_info["phone"] = store.phone
                store_info["hours"] = store.hours

                # Store hours / scheduling support
                timezone_str = store.timezone or "America/New_York"
                hours_config = parse_hours_config(store.hours if isinstance(store.hours, dict) else None)
                store_open = is_store_open_now(hours_config, timezone_str)
                store_info["timezone"] = timezone_str
                store_info["is_open"] = store_open
                store_info["hours_config"] = hours_config
                if not store_open:
                    store_info["next_open_time"] = get_next_open_time_display(hours_config, timezone_str)
                else:
                    store_info["next_open_time"] = None

        # Get all stores for delivery zone lookup
        all_stores = db.query(Store).filter(Store.status == "open").all()
        store_info["all_stores"] = [
            {
                "store_id": s.store_id,
                "name": s.name,
                "delivery_zip_codes": s.delivery_zip_codes or [],
                "address": s.address,
                "city": s.city,
                "state": s.state,
                "phone": s.phone,
            }
            for s in all_stores
        ]

        # Cache before returning
        _store_info_cache[cache_key] = store_info
        _store_info_cache_time[cache_key] = time.time()

        return store_info


def invalidate_store_cache(store_id: str | None = None) -> None:
    """
    Invalidate the store info cache.

    Call this after admin store updates to ensure fresh data is loaded.

    Args:
        store_id: Specific store ID to invalidate, or None to clear all
    """
    with _store_cache_lock:
        if store_id:
            _store_info_cache.pop(store_id, None)
            _store_info_cache_time.pop(store_id, None)
            # Also invalidate default since it contains all_stores list
            _store_info_cache.pop("__default__", None)
            _store_info_cache_time.pop("__default__", None)
        else:
            _store_info_cache.clear()
            _store_info_cache_time.clear()
    logger.debug("Store cache invalidated: %s", store_id or "all")


def warmup_store_cache(db: Session) -> None:
    """
    Pre-warm the store info cache at startup.

    Loads store info for all open stores plus the default (no store) case.
    This eliminates cold-start latency for the first requests.

    Args:
        db: Database session
    """
    # Get all open stores
    stores = db.query(Store).filter(Store.status == "open").all()
    for store in stores:
        build_store_info(db, store.store_id)
    # Also cache the default (no store_id) case
    build_store_info(db, None)
    logger.info("Store cache warmed up: %d stores", len(stores) + 1)
