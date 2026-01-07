"""
Admin Menu Routes for Sandwich Bot
===================================

This module contains admin endpoints for managing menu items. Menu items are
the products customers can order (sandwiches, drinks, sides, etc.).

Endpoints:
----------
- GET /admin/menu: List all menu items
- POST /admin/menu: Create a new menu item
- GET /admin/menu/{id}: Get a specific menu item
- PUT /admin/menu/{id}: Update a menu item
- DELETE /admin/menu/{id}: Delete a menu item

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
See auth.py for credential verification.

Menu Item Structure:
--------------------
Menu items have:
- name: Display name (e.g., "Turkey Club")
- category: Grouping (sandwiches, drinks, sides)
- is_signature: Pre-configured items on the speed menu
- base_price: Starting price before modifiers
- metadata: Additional data (description, defaults, allergens)
- item_type_id: Links to ItemType for configuration options

Metadata Field:
---------------
The metadata field stores JSON data including:
- description: Item description for display
- default_config: Default selections for signature items
- allergens: List of allergen warnings
- calories: Nutritional information

Usage:
------
    # Create a signature sandwich
    POST /admin/menu
    {
        "name": "The Italian",
        "category": "sandwiches",
        "is_signature": true,
        "base_price": 12.99,
        "metadata": {
            "description": "Salami, capicola, and provolone",
            "default_config": {"bread": "italian", "toasted": true}
        }
    }
"""

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import (
    MenuItem,
    ItemTypeAttribute,
    MenuItemAttributeValue,
    MenuItemAttributeSelection,
    AttributeOption,
)
from ..schemas.menu import MenuItemOut, MenuItemCreate, MenuItemUpdate
from ..schemas.item_type_attributes import (
    MenuItemAttributesOut,
    MenuItemAttributeValueOut,
    MenuItemAttributesUpdate,
    MenuItemEditForm,
    AttributeFormField,
    AttributeOptionOut,
)


logger = logging.getLogger(__name__)

# Router definition
admin_menu_router = APIRouter(prefix="/admin/menu", tags=["Admin - Menu"])


# =============================================================================
# Helper Functions
# =============================================================================

def serialize_menu_item(item: MenuItem) -> MenuItemOut:
    """Convert MenuItem model to response schema."""
    try:
        meta = json.loads(item.extra_metadata) if item.extra_metadata else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}

    return MenuItemOut(
        id=item.id,
        name=item.name,
        category=item.category,
        is_signature=item.is_signature,
        base_price=float(item.base_price),
        available_qty=item.available_qty,
        metadata=meta,
        item_type_id=item.item_type_id,
        aliases=item.aliases,
        abbreviation=item.abbreviation,
        required_match_phrases=item.required_match_phrases,
    )


# =============================================================================
# Menu Endpoints
# =============================================================================

@admin_menu_router.get("", response_model=List[MenuItemOut])
def admin_menu(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[MenuItemOut]:
    """List all menu items. Requires admin authentication."""
    items = db.query(MenuItem).order_by(MenuItem.id.asc()).all()
    return [serialize_menu_item(m) for m in items]


@admin_menu_router.post("", response_model=MenuItemOut)
def create_menu_item(
    payload: MenuItemCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Create a new menu item. Requires admin authentication."""
    item = MenuItem(
        name=payload.name,
        category=payload.category,
        is_signature=payload.is_signature,
        base_price=payload.base_price,
        available_qty=payload.available_qty,
        extra_metadata=json.dumps(payload.metadata or {}),
        item_type_id=payload.item_type_id,
        aliases=payload.aliases,
        abbreviation=payload.abbreviation,
        required_match_phrases=payload.required_match_phrases,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    logger.info("Created menu item: %s (id=%d)", item.name, item.id)
    return serialize_menu_item(item)


@admin_menu_router.get("/{item_id}", response_model=MenuItemOut)
def get_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Get a specific menu item by ID. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return serialize_menu_item(item)


@admin_menu_router.put("/{item_id}", response_model=MenuItemOut)
def update_menu_item(
    item_id: int,
    payload: MenuItemUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemOut:
    """Update a menu item. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if payload.name is not None:
        item.name = payload.name
    if payload.category is not None:
        item.category = payload.category
    if payload.is_signature is not None:
        item.is_signature = payload.is_signature
    if payload.base_price is not None:
        item.base_price = payload.base_price
    if payload.available_qty is not None:
        item.available_qty = payload.available_qty
    if payload.metadata is not None:
        item.extra_metadata = json.dumps(payload.metadata)
    if payload.item_type_id is not None:
        item.item_type_id = payload.item_type_id
    if payload.aliases is not None:
        item.aliases = payload.aliases
    if payload.abbreviation is not None:
        item.abbreviation = payload.abbreviation
    if payload.required_match_phrases is not None:
        item.required_match_phrases = payload.required_match_phrases

    db.commit()
    db.refresh(item)
    logger.info("Updated menu item: %s (id=%d)", item.name, item.id)
    return serialize_menu_item(item)


@admin_menu_router.delete("/{item_id}", status_code=204)
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a menu item and its related data. Requires admin authentication."""
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    logger.info("Deleting menu item: %s (id=%d)", item.name, item.id)

    # Delete related attribute values and selections first
    db.query(MenuItemAttributeValue).filter(
        MenuItemAttributeValue.menu_item_id == item_id
    ).delete()
    db.query(MenuItemAttributeSelection).filter(
        MenuItemAttributeSelection.menu_item_id == item_id
    ).delete()

    # Now delete the menu item
    db.delete(item)
    db.commit()
    return None


# =============================================================================
# Cache Management Endpoints
# =============================================================================

@admin_menu_router.get("/cache/status", response_model=Dict[str, Any])
def get_cache_status(
    _admin: str = Depends(verify_admin_credentials),
) -> Dict[str, Any]:
    """
    Get menu data cache status.

    Returns information about the cache including:
    - Whether it's loaded
    - Last refresh timestamp
    - Item counts by category
    - Keyword index sizes

    Requires admin authentication.
    """
    from ..menu_data_cache import menu_cache
    return menu_cache.get_status()


@admin_menu_router.post("/cache/refresh", response_model=Dict[str, Any])
def refresh_cache(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> Dict[str, Any]:
    """
    Manually refresh the menu data cache.

    Reloads all menu data from the database including:
    - Spread types and varieties
    - Bagel types
    - Proteins, toppings, and cheeses
    - Coffee and soda types
    - Known menu items

    This is useful after making menu changes that should take effect
    immediately without waiting for the scheduled 3 AM refresh.

    Requires admin authentication.

    Returns:
        Cache status after refresh
    """
    from ..menu_data_cache import menu_cache

    logger.info("Manual cache refresh triggered by admin")
    menu_cache.load_from_db(db, fail_on_error=False)

    return {
        "message": "Cache refreshed successfully",
        "status": menu_cache.get_status(),
    }


# =============================================================================
# Menu Item Attribute Value Endpoints
# =============================================================================

def _get_attribute_value_out(
    attr: ItemTypeAttribute,
    value: MenuItemAttributeValue | None,
    selections: List[MenuItemAttributeSelection],
    db: Session,
) -> MenuItemAttributeValueOut:
    """Convert attribute and its value to response schema."""
    # Get options for this attribute
    options = (
        db.query(AttributeOption)
        .filter(AttributeOption.item_type_attribute_id == attr.id)
        .order_by(AttributeOption.display_order)
        .all()
    )

    selected_options = []
    if attr.input_type == "multi_select" and selections:
        for sel in selections:
            if sel.option:
                selected_options.append(AttributeOptionOut(
                    id=sel.option.id,
                    slug=sel.option.slug,
                    display_name=sel.option.display_name,
                    price_modifier=float(sel.option.price_modifier or 0),
                    is_default=sel.option.is_default,
                    is_available=sel.option.is_available,
                    display_order=sel.option.display_order,
                ))

    return MenuItemAttributeValueOut(
        id=value.id if value else 0,
        attribute_id=attr.id,
        attribute_slug=attr.slug,
        attribute_display_name=attr.display_name,
        input_type=attr.input_type,
        option_id=value.option_id if value else None,
        option_display_name=value.option.display_name if value and value.option else None,
        value_boolean=value.value_boolean if value else None,
        value_text=value.value_text if value else None,
        selected_options=selected_options,
        still_ask=value.still_ask if value else False,
    )


@admin_menu_router.get("/{item_id}/attributes", response_model=MenuItemAttributesOut)
def get_menu_item_attributes(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemAttributesOut:
    """
    Get all attribute values for a menu item.

    Returns the current configuration values for all attributes defined
    for this menu item's item type.

    Requires admin authentication.
    """
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if not item.item_type_id:
        return MenuItemAttributesOut(
            menu_item_id=item.id,
            menu_item_name=item.name,
            item_type_slug=None,
            attributes=[],
        )

    # Get all attributes for this item type
    attrs = (
        db.query(ItemTypeAttribute)
        .filter(ItemTypeAttribute.item_type_id == item.item_type_id)
        .order_by(ItemTypeAttribute.display_order)
        .all()
    )

    # Get all attribute values for this menu item
    values = (
        db.query(MenuItemAttributeValue)
        .filter(MenuItemAttributeValue.menu_item_id == item_id)
        .all()
    )
    values_by_attr = {v.attribute_id: v for v in values}

    # Get all multi-select selections for this menu item
    selections = (
        db.query(MenuItemAttributeSelection)
        .filter(MenuItemAttributeSelection.menu_item_id == item_id)
        .all()
    )
    selections_by_attr: Dict[int, List[MenuItemAttributeSelection]] = {}
    for sel in selections:
        if sel.attribute_id not in selections_by_attr:
            selections_by_attr[sel.attribute_id] = []
        selections_by_attr[sel.attribute_id].append(sel)

    # Build response
    attribute_values = []
    for attr in attrs:
        value = values_by_attr.get(attr.id)
        attr_selections = selections_by_attr.get(attr.id, [])
        attribute_values.append(_get_attribute_value_out(attr, value, attr_selections, db))

    return MenuItemAttributesOut(
        menu_item_id=item.id,
        menu_item_name=item.name,
        item_type_slug=item.item_type.slug if item.item_type else None,
        attributes=attribute_values,
    )


@admin_menu_router.get("/{item_id}/edit-form", response_model=MenuItemEditForm)
def get_menu_item_edit_form(
    item_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemEditForm:
    """
    Get form data for editing a menu item's attributes.

    Returns all attributes for this item type along with their available
    options and current values. This is designed to populate an admin edit form.

    Requires admin authentication.
    """
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if not item.item_type_id:
        return MenuItemEditForm(
            menu_item_id=item.id,
            menu_item_name=item.name,
            item_type_id=None,
            item_type_slug=None,
            fields=[],
        )

    # Get all attributes for this item type
    attrs = (
        db.query(ItemTypeAttribute)
        .filter(ItemTypeAttribute.item_type_id == item.item_type_id)
        .order_by(ItemTypeAttribute.display_order)
        .all()
    )

    # Get all attribute values for this menu item
    values = (
        db.query(MenuItemAttributeValue)
        .filter(MenuItemAttributeValue.menu_item_id == item_id)
        .all()
    )
    values_by_attr = {v.attribute_id: v for v in values}

    # Get all multi-select selections for this menu item
    selections = (
        db.query(MenuItemAttributeSelection)
        .filter(MenuItemAttributeSelection.menu_item_id == item_id)
        .all()
    )
    selections_by_attr: Dict[int, List[int]] = {}
    for sel in selections:
        if sel.attribute_id not in selections_by_attr:
            selections_by_attr[sel.attribute_id] = []
        selections_by_attr[sel.attribute_id].append(sel.option_id)

    # Build form fields
    fields = []
    for attr in attrs:
        # Get options for this attribute
        options = (
            db.query(AttributeOption)
            .filter(AttributeOption.item_type_attribute_id == attr.id)
            .order_by(AttributeOption.display_order)
            .all()
        )

        value = values_by_attr.get(attr.id)

        field = AttributeFormField(
            attribute_id=attr.id,
            slug=attr.slug,
            display_name=attr.display_name,
            input_type=attr.input_type,
            is_required=attr.is_required,
            allow_none=attr.allow_none,
            question_text=attr.question_text,
            options=[
                AttributeOptionOut(
                    id=opt.id,
                    slug=opt.slug,
                    display_name=opt.display_name,
                    price_modifier=float(opt.price_modifier or 0),
                    is_default=opt.is_default,
                    is_available=opt.is_available,
                    display_order=opt.display_order,
                )
                for opt in options
            ],
            current_option_id=value.option_id if value else None,
            current_option_ids=selections_by_attr.get(attr.id, []),
            current_boolean=value.value_boolean if value else None,
            current_text=value.value_text if value else None,
            still_ask=value.still_ask if value else False,
        )
        fields.append(field)

    return MenuItemEditForm(
        menu_item_id=item.id,
        menu_item_name=item.name,
        item_type_id=item.item_type_id,
        item_type_slug=item.item_type.slug if item.item_type else None,
        fields=fields,
    )


@admin_menu_router.put("/{item_id}/attributes", response_model=MenuItemAttributesOut)
def update_menu_item_attributes(
    item_id: int,
    payload: MenuItemAttributesUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> MenuItemAttributesOut:
    """
    Update attribute values for a menu item.

    Accepts a dictionary of attribute slugs to their new values.
    Creates or updates MenuItemAttributeValue records as needed.

    Example payload:
        {
            "attributes": {
                "bread": {"option_id": 5, "still_ask": true},
                "protein": {"option_id": 12},
                "toppings": {"selected_option_ids": [20, 21]},
                "toasted": {"value_boolean": true}
            }
        }

    Requires admin authentication.
    """
    item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")

    if not item.item_type_id:
        raise HTTPException(
            status_code=400,
            detail="Menu item has no item type - cannot set attributes"
        )

    # Get all attributes for this item type
    attrs = (
        db.query(ItemTypeAttribute)
        .filter(ItemTypeAttribute.item_type_id == item.item_type_id)
        .all()
    )
    attrs_by_slug = {a.slug: a for a in attrs}

    # Process each attribute update
    for slug, update in payload.attributes.items():
        attr = attrs_by_slug.get(slug)
        if not attr:
            logger.warning(
                "Ignoring unknown attribute '%s' for menu item %d",
                slug, item_id
            )
            continue

        # Get or create the value record
        value = (
            db.query(MenuItemAttributeValue)
            .filter(
                MenuItemAttributeValue.menu_item_id == item_id,
                MenuItemAttributeValue.attribute_id == attr.id
            )
            .first()
        )

        if not value:
            value = MenuItemAttributeValue(
                menu_item_id=item_id,
                attribute_id=attr.id,
            )
            db.add(value)

        # Update based on input type
        if attr.input_type == "single_select":
            if update.option_id is not None:
                value.option_id = update.option_id
                value.value_boolean = None
                value.value_text = None
        elif attr.input_type == "boolean":
            if update.value_boolean is not None:
                value.value_boolean = update.value_boolean
                value.option_id = None
                value.value_text = None
        elif attr.input_type == "text":
            if update.value_text is not None:
                value.value_text = update.value_text
                value.option_id = None
                value.value_boolean = None
        elif attr.input_type == "multi_select":
            # Handle multi-select: update the selections table
            if update.selected_option_ids is not None:
                # Delete existing selections
                db.query(MenuItemAttributeSelection).filter(
                    MenuItemAttributeSelection.menu_item_id == item_id,
                    MenuItemAttributeSelection.attribute_id == attr.id
                ).delete()

                # Create new selections
                for opt_id in update.selected_option_ids:
                    selection = MenuItemAttributeSelection(
                        menu_item_id=item_id,
                        attribute_id=attr.id,
                        option_id=opt_id,
                    )
                    db.add(selection)

        # Update still_ask if provided
        if update.still_ask is not None:
            value.still_ask = update.still_ask

    db.commit()

    logger.info(
        "Updated attributes for menu item: %s (id=%d), attributes: %s",
        item.name, item.id, list(payload.attributes.keys())
    )

    # Return updated attributes
    return get_menu_item_attributes(item_id, db, _admin)
