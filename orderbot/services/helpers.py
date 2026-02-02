"""
Helper Functions for Orderbot
=================================

This module contains shared utility functions used across multiple routes
and services in the Orderbot application.

Key Functions:
--------------
- get_or_create_company: Get the company record or create default
- lookup_customer_by_phone: Find returning customer by phone number
- get_primary_item_type_name: Get name of primary configurable item type
- build_store_info: Build store info dict with caching
- warmup_store_cache: Pre-warm store cache at startup
- invalidate_store_cache: Invalidate cache after admin updates

Usage:
------
These helpers are imported by route handlers and other services that need
common database lookups or data transformations.

    from orderbot.services.helpers import (
        get_or_create_company,
        lookup_customer_by_phone,
    )

    # In a route handler
    company = get_or_create_company(db)
    customer = lookup_customer_by_phone(db, phone_number)

Company Lookup:
---------------
get_or_create_company ensures there's always a Company record in the database.
If none exists, it creates a default one with generic names. This is used for:
- Bot persona name (for LLM context)
- Company branding in chat
- Signature item labels

Customer Lookup:
----------------
lookup_customer_by_phone normalizes phone numbers and searches order history
to identify returning customers. It handles various phone formats:
- With/without country code (+1)
- With/without dashes and parentheses
- Returns customer info and last order items for "repeat order" feature

Store Info Caching:
-------------------
build_store_info uses a TTL cache to avoid repeated database queries.
Cache is populated at startup via warmup_store_cache() and invalidated
when stores are updated via invalidate_store_cache().
"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..db.models import (
    Company,
    GlobalAttributeOptionAlias,
    IngredientAlias,
    IngredientStoreAvailability,
    ItemType,
    ItemTypeAlias,
    MenuItemAlias,
    MenuItemStoreAvailability,
    ModifierCategoryAlias,
    Order,
    Store,
)
from .item_type_helpers import has_linked_attributes


# =============================================================================
# Entity Type Configuration for Alias Syncing
# =============================================================================

# Maps entity type to (AliasModel, FK column name, validate_aliases exclude param name)
_ALIAS_CONFIG = {
    "ingredient": (IngredientAlias, "ingredient_id", "exclude_ingredient_id"),
    "menu_item": (MenuItemAlias, "menu_item_id", "exclude_menu_item_id"),
    "modifier_category": (ModifierCategoryAlias, "modifier_category_id", "exclude_modifier_category_id"),
    "item_type": (ItemTypeAlias, "item_type_id", "exclude_item_type_id"),
    "global_attribute_option": (GlobalAttributeOptionAlias, "global_attribute_option_id", "exclude_global_attr_option_id"),
}


logger = logging.getLogger(__name__)


# =============================================================================
# Store Info Cache
# =============================================================================

_store_info_cache: Dict[str, Dict[str, Any]] = {}
_store_info_cache_time: Dict[str, float] = {}
_STORE_CACHE_TTL = 300  # 5 minutes


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
    store_id: Optional[str],
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
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


def invalidate_store_cache(store_id: Optional[str] = None) -> None:
    """
    Invalidate the store info cache.

    Call this after admin store updates to ensure fresh data is loaded.

    Args:
        store_id: Specific store ID to invalidate, or None to clear all
    """
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


def lookup_customer_by_phone(db: Session, phone: str) -> Optional[Dict[str, Any]]:
    """
    Look up a returning customer by phone number.

    Normalizes phone numbers to handle various formats:
    - (123) 456-7890
    - 123-456-7890
    - +1 123 456 7890
    - 1234567890

    Uses the last 10 digits for matching to handle country code variations.

    Args:
        db: Database session
        phone: Phone number to look up (any format)

    Returns:
        Dict with customer info if found:
        - name: Customer's name from last order
        - phone: Phone number
        - email: Email if provided
        - order_count: Total number of orders
        - last_order_items: Items from most recent order (for repeat order)
        - last_order_date: ISO date of last order
        - last_order_type: "pickup" or "delivery"
        - last_order_address: Delivery address if applicable

        None if no orders found for this phone number
    """
    if not phone:
        return None

    # Normalize phone number (remove common formatting)
    normalized_phone = phone.replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
    # Use last 10 digits for matching (handles +1 country code)
    phone_suffix = normalized_phone[-10:] if len(normalized_phone) >= 10 else normalized_phone

    # Use SQL func.replace to normalize stored phone numbers for comparison
    normalized_db_phone = func.replace(
        func.replace(
            func.replace(
                func.replace(Order.phone, "-", ""),
                " ", ""
            ),
            "(", ""
        ),
        ")", ""
    )

    # Find most recent order with this phone number
    # Use joinedload to eagerly load items for repeat order functionality
    recent_order = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .order_by(Order.created_at.desc())
        .first()
    )

    if not recent_order:
        return None

    # Get order history count (using same normalized phone matching)
    order_count = (
        db.query(Order)
        .filter(Order.phone.isnot(None))
        .filter(normalized_db_phone.like(f"%{phone_suffix}%"))
        .count()
    )

    # Get last order items for "usual" feature
    last_order_items: List[Dict[str, Any]] = []
    if recent_order.items:
        for item in recent_order.items:
            item_data = {
                "menu_item_name": item.menu_item_name,
                "quantity": item.quantity,
                "price": item.unit_price,  # Unit price for repeat order calculations
            }
            # All item-specific fields (item_type, bread, toasted, etc.) are in item_config
            if item.item_config:
                item_data.update(item.item_config)
            last_order_items.append(item_data)

    return {
        "name": recent_order.customer_name,
        "phone": recent_order.phone,
        "email": recent_order.customer_email,
        "order_count": order_count,
        "last_order_id": recent_order.id,
        "last_order_items": last_order_items,
        "last_order_date": recent_order.created_at.isoformat() if recent_order.created_at else None,
        "last_order_type": recent_order.order_type,  # "pickup" or "delivery"
        "last_order_address": recent_order.delivery_address,  # For repeat delivery orders
    }


def get_primary_item_type_name(db: Session) -> str:
    """
    Get the display name of the primary configurable item type.

    This is used for dynamic greeting messages (e.g., "Would you like
    a signature sandwich?" vs "Would you like a signature pizza?").

    Configurability is derived from linked global attributes.

    Args:
        db: Database session

    Returns:
        Display name of the first configurable item type, or "Sandwich" as default
    """
    # Find the first item type with linked global attributes (configurable)
    item_types = db.query(ItemType).all()
    for it in item_types:
        if has_linked_attributes(it.id, db):
            return it.display_name
    return "Sandwich"


def _check_alias_in_table(
    db: Session,
    alias_model: type,
    alias_lower: str,
    exclude_id: int | None,
    fk_column_name: str,
    entity_type_name: str,
    entity_name_accessor: str,
) -> tuple[bool, str | None]:
    """Check for alias collision in a single alias table.

    Generic helper that checks if an alias already exists in an alias table,
    optionally excluding a specific entity ID (for update operations).

    Args:
        db: Database session
        alias_model: The alias model class (e.g., ItemTypeAlias)
        alias_lower: Lowercase alias to search for
        exclude_id: Entity ID to exclude from search (for updates)
        fk_column_name: Name of the FK column (e.g., "item_type_id")
        entity_type_name: Human-readable entity type (e.g., "ItemType")
        entity_name_accessor: Attribute path to get entity name (e.g., "item_type.slug")

    Returns:
        Tuple of (is_unique, conflict_message)
        - (True, None) if no collision
        - (False, message) if collision found
    """
    query = db.query(alias_model).filter(
        func.lower(alias_model.alias) == alias_lower
    )
    if exclude_id:
        query = query.filter(getattr(alias_model, fk_column_name) != exclude_id)
    existing = query.first()
    if existing:
        # Navigate the attribute path (e.g., "item_type.slug" or "option.display_name")
        entity_name = existing
        for attr in entity_name_accessor.split("."):
            entity_name = getattr(entity_name, attr, None)
        return False, f"Alias already exists on {entity_type_name} '{entity_name}'"
    return True, None


def check_alias_uniqueness(
    db: Session,
    alias: str,
    exclude_item_type_id: int | None = None,
    exclude_menu_item_id: int | None = None,
    exclude_modifier_category_id: int | None = None,
    exclude_ingredient_id: int | None = None,
    exclude_global_attr_option_id: int | None = None,
) -> tuple[bool, str | None]:
    """
    Check if an alias is globally unique across all alias tables.

    Aliases must be unique across all entity types (ItemType, MenuItem,
    ModifierCategory, Ingredient, GlobalAttributeOption) to prevent ambiguous lookups.

    Args:
        db: Database session
        alias: The alias to check (case-insensitive)
        exclude_item_type_id: ItemType ID to exclude (for updates)
        exclude_menu_item_id: MenuItem ID to exclude (for updates)
        exclude_modifier_category_id: ModifierCategory ID to exclude (for updates)
        exclude_ingredient_id: Ingredient ID to exclude (for updates)
        exclude_global_attr_option_id: GlobalAttributeOption ID to exclude (for updates)

    Returns:
        Tuple of (is_unique, conflict_message)
        - (True, None) if alias is unique
        - (False, "Alias 'x' already exists on ItemType 'y'") if duplicate found
    """
    alias_lower = alias.strip().lower()
    if not alias_lower:
        return True, None

    # Configuration for each alias table to check
    alias_tables = [
        (ItemTypeAlias, exclude_item_type_id, "item_type_id", "ItemType", "item_type.slug"),
        (MenuItemAlias, exclude_menu_item_id, "menu_item_id", "MenuItem", "menu_item.name"),
        (ModifierCategoryAlias, exclude_modifier_category_id, "modifier_category_id", "ModifierCategory", "modifier_category.slug"),
        (IngredientAlias, exclude_ingredient_id, "ingredient_id", "Ingredient", "ingredient.name"),
        (GlobalAttributeOptionAlias, exclude_global_attr_option_id, "global_attribute_option_id", "GlobalAttributeOption", "option.display_name"),
    ]

    for alias_model, exclude_id, fk_column, entity_type, name_accessor in alias_tables:
        is_unique, message = _check_alias_in_table(
            db, alias_model, alias_lower, exclude_id, fk_column, entity_type, name_accessor
        )
        if not is_unique:
            return False, message

    return True, None


def validate_aliases(
    db: Session,
    aliases_str: str | None,
    exclude_item_type_id: int | None = None,
    exclude_menu_item_id: int | None = None,
    exclude_modifier_category_id: int | None = None,
    exclude_ingredient_id: int | None = None,
    exclude_global_attr_option_id: int | None = None,
) -> list[str]:
    """
    Validate and return list of globally unique aliases.

    Parses comma-separated aliases string, validates each is globally unique,
    and returns the list of valid aliases. Raises ValueError if any alias
    is a duplicate.

    Args:
        db: Database session
        aliases_str: Comma-separated aliases string
        exclude_item_type_id: ItemType ID to exclude (for updates)
        exclude_menu_item_id: MenuItem ID to exclude (for updates)
        exclude_modifier_category_id: ModifierCategory ID to exclude (for updates)
        exclude_ingredient_id: Ingredient ID to exclude (for updates)
        exclude_global_attr_option_id: GlobalAttributeOption ID to exclude (for updates)

    Returns:
        List of validated aliases

    Raises:
        ValueError if any alias is not globally unique
    """
    if not aliases_str:
        return []

    aliases = []
    errors = []
    for alias in aliases_str.split(","):
        alias = alias.strip()
        if not alias:
            continue

        is_unique, error_msg = check_alias_uniqueness(
            db,
            alias,
            exclude_item_type_id=exclude_item_type_id,
            exclude_menu_item_id=exclude_menu_item_id,
            exclude_modifier_category_id=exclude_modifier_category_id,
            exclude_ingredient_id=exclude_ingredient_id,
            exclude_global_attr_option_id=exclude_global_attr_option_id,
        )
        if not is_unique:
            errors.append(error_msg)
        else:
            aliases.append(alias)

    if errors:
        raise ValueError("; ".join(errors))

    return aliases


def sync_entity_aliases(
    db: Session,
    entity: Any,
    aliases_str: Optional[str],
    entity_type: str,
) -> None:
    """
    Sync aliases for any entity type from a comma-separated string.

    This is a generic helper that consolidates the duplicate alias-handling
    logic across multiple admin routes. It:
    1. Clears existing aliases via the entity's `alias_records` relationship
    2. Flushes to avoid unique constraint violations
    3. Validates new aliases are globally unique
    4. Creates new alias records

    Args:
        db: Database session
        entity: The parent entity (Ingredient, MenuItem, ItemType, etc.)
        aliases_str: Comma-separated aliases string (or None to clear all)
        entity_type: One of "ingredient", "menu_item", "modifier_category",
                     "item_type", or "global_attribute_option"

    Raises:
        HTTPException: If any alias conflicts with an existing alias
        ValueError: If entity_type is not recognized

    Example:
        >>> sync_entity_aliases(db, ingredient, "swiss, swiss cheese", "ingredient")
    """
    if entity_type not in _ALIAS_CONFIG:
        raise ValueError(f"Unknown entity_type: {entity_type}. Must be one of {list(_ALIAS_CONFIG.keys())}")

    alias_model, fk_column, exclude_param = _ALIAS_CONFIG[entity_type]

    # Clear existing aliases via the entity's alias_records relationship
    for alias_record in list(entity.alias_records):
        db.delete(alias_record)

    # Flush deletes before inserting new records to avoid unique constraint violations
    db.flush()

    # Validate and add new aliases if provided
    if aliases_str:
        try:
            # Pass the entity's ID as the exclude parameter so re-saving same aliases works
            validated_aliases = validate_aliases(
                db,
                aliases_str,
                **{exclude_param: entity.id},
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        for alias in validated_aliases:
            # Create alias record using the FK column name
            alias_record = alias_model(**{fk_column: entity.id, "alias": alias})
            db.add(alias_record)


def batch_load_store_availability(
    db: Session,
    store_id: Optional[str],
    entity_type: str,
) -> Dict[int, bool]:
    """
    Batch-load store availability for a list of entities in a single query.

    This eliminates N+1 queries when loading store-specific availability
    for multiple entities at once.

    Args:
        db: Database session
        store_id: Store ID to check availability for (or None for global)
        entity_type: One of "ingredient" or "menu_item"

    Returns:
        Dict mapping entity ID to availability status.
        If store_id is None, returns empty dict (caller should use default).

    Example:
        >>> avail_map = batch_load_store_availability(db, "store_123", "ingredient")
        >>> is_available = avail_map.get(ing.id, ing.is_available)
    """
    if not store_id:
        return {}

    if entity_type == "ingredient":
        store_avails = db.query(IngredientStoreAvailability).filter(
            IngredientStoreAvailability.store_id == store_id
        ).all()
        return {sa.ingredient_id: sa.is_available for sa in store_avails}
    elif entity_type == "menu_item":
        store_avails = db.query(MenuItemStoreAvailability).filter(
            MenuItemStoreAvailability.store_id == store_id
        ).all()
        return {sa.menu_item_id: sa.is_available for sa in store_avails}
    else:
        raise ValueError(f"Unknown entity_type: {entity_type}. Must be 'ingredient' or 'menu_item'")
