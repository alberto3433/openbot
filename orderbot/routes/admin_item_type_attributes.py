"""
Admin Item Type Attributes Routes for Orderbot
===================================================

This module contains admin endpoints for managing item type attributes using the
new consolidated schema (item_type_attributes table). This replaces the older
item_type_field and attribute_definitions tables.

Endpoints:
----------
- GET /admin/item-type-attributes: List all attributes
- GET /admin/item-type-attributes/{id}: Get a specific attribute
- POST /admin/item-type-attributes: Create a new attribute
- PUT /admin/item-type-attributes/{id}: Update an attribute
- DELETE /admin/item-type-attributes/{id}: Delete an attribute

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # List all attributes for egg_sandwich
    GET /admin/item-type-attributes?item_type_slug=egg_sandwich

    # Create a new attribute
    POST /admin/item-type-attributes
    {
        "item_type_id": 5,
        "slug": "sauce",
        "display_name": "Sauce",
        "input_type": "single_select",
        "is_required": false,
        "ask_in_conversation": true,
        "question_text": "Would you like any sauce?"
    }
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ItemType, ItemTypeAttribute, ItemTypeIngredient, Ingredient, GlobalAttributeOption
from ..schemas.item_type_attributes import (
    ItemTypeAttributeOut,
    ItemTypeAttributeCreate,
    ItemTypeAttributeUpdate,
    AttributeOptionOut,
    IngredientLinkCreate,
    IngredientLinkUpdate,
    AvailableIngredientOut,
)

logger = logging.getLogger(__name__)

# Router definition
admin_item_type_attributes_router = APIRouter(
    prefix="/admin/item-type-attributes",
    tags=["Admin - Item Type Attributes"]
)


def _serialize_attribute(attr: ItemTypeAttribute, db: Session) -> ItemTypeAttributeOut:
    """Convert ItemTypeAttribute model to response schema with options.

    If loads_from_ingredients=True, options come from item_type_ingredients table
    joined to ingredients. Pricing comes from GlobalAttributeOption.price_modifier
    (where ingredient_id matches).
    """
    options_out = []

    if attr.loads_from_ingredients and attr.ingredient_group:
        # Load options from item_type_ingredients -> ingredients
        ingredient_links = (
            db.query(ItemTypeIngredient)
            .join(Ingredient)
            .filter(
                ItemTypeIngredient.item_type_id == attr.item_type_id,
                ItemTypeIngredient.ingredient_group == attr.ingredient_group,
            )
            .order_by(ItemTypeIngredient.display_order)
            .all()
        )

        # Build price map from GlobalAttributeOption (source of truth for pricing)
        ingredient_ids = [link.ingredient_id for link in ingredient_links]
        price_map = {}
        if ingredient_ids:
            global_options = (
                db.query(GlobalAttributeOption.ingredient_id, GlobalAttributeOption.price_modifier)
                .filter(GlobalAttributeOption.ingredient_id.in_(ingredient_ids))
                .all()
            )
            price_map = {opt.ingredient_id: opt.price_modifier for opt in global_options}

        for link in ingredient_links:
            # Look up price from GlobalAttributeOption (source of truth)
            price = price_map.get(link.ingredient_id, 0.0)
            options_out.append(AttributeOptionOut(
                id=link.id,  # Use ItemTypeIngredient.id as the option ID
                slug=link.ingredient.slug,
                display_name=link.display_name_override or link.ingredient.name,
                price_modifier=float(price),
                is_default=link.is_default,
                is_available=link.is_available and link.ingredient.is_available,
                display_order=link.display_order,
                ingredient_id=link.ingredient_id,
                ingredient_name=link.ingredient.name,
            ))
    else:
        # For ItemTypeAttribute entries that don't load from ingredients
        # (e.g., boolean types like "toasted"), options are not applicable.
        # Select-type attributes should use GlobalAttribute via ItemTypeGlobalAttribute.
        # The attribute_options table has been removed - use global_attribute_options instead.
        pass

    return ItemTypeAttributeOut(
        id=attr.id,
        item_type_id=attr.item_type_id,
        item_type_slug=attr.item_type.slug if attr.item_type else None,
        slug=attr.slug,
        display_name=attr.display_name,
        input_type=attr.input_type,
        is_required=attr.is_required,
        allow_none=attr.allow_none,
        min_selections=attr.min_selections,
        max_selections=attr.max_selections,
        display_order=attr.display_order,
        ask_in_conversation=attr.ask_in_conversation,
        question_text=attr.question_text,
        loads_from_ingredients=attr.loads_from_ingredients,
        ingredient_group=attr.ingredient_group,
        options=options_out,
        created_at=attr.created_at,
        updated_at=attr.updated_at,
    )


@admin_item_type_attributes_router.get("", response_model=List[ItemTypeAttributeOut])
def list_item_type_attributes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    item_type_slug: Optional[str] = Query(None, description="Filter by item type slug"),
    item_type_id: Optional[int] = Query(None, description="Filter by item type ID"),
) -> List[ItemTypeAttributeOut]:
    """List all item type attributes, optionally filtered by item type."""
    query = db.query(ItemTypeAttribute).join(ItemType)

    if item_type_slug:
        query = query.filter(ItemType.slug == item_type_slug)
    if item_type_id:
        query = query.filter(ItemTypeAttribute.item_type_id == item_type_id)

    attrs = query.order_by(ItemType.slug, ItemTypeAttribute.display_order).all()
    return [_serialize_attribute(attr, db) for attr in attrs]


@admin_item_type_attributes_router.get("/{attr_id}", response_model=ItemTypeAttributeOut)
def get_item_type_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Get a specific item type attribute by ID."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")
    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.post("", response_model=ItemTypeAttributeOut, status_code=201)
def create_item_type_attribute(
    payload: ItemTypeAttributeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Create a new item type attribute."""
    # Verify item type exists
    item_type = db.query(ItemType).filter(ItemType.id == payload.item_type_id).first()
    if not item_type:
        raise HTTPException(
            status_code=400,
            detail=f"Item type with ID {payload.item_type_id} not found"
        )

    # Check for duplicate slug for this item_type
    existing = db.query(ItemTypeAttribute).filter(
        ItemTypeAttribute.item_type_id == payload.item_type_id,
        ItemTypeAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Attribute '{payload.slug}' already exists for item type '{item_type.slug}'"
        )

    attr = ItemTypeAttribute(
        item_type_id=payload.item_type_id,
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        is_required=payload.is_required,
        allow_none=payload.allow_none,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        display_order=payload.display_order,
        ask_in_conversation=payload.ask_in_conversation,
        question_text=payload.question_text,
    )
    db.add(attr)
    db.commit()
    db.refresh(attr)

    logger.info(
        "Created item type attribute: %s for %s (id=%d)",
        attr.slug,
        item_type.slug,
        attr.id
    )

    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.put("/{attr_id}", response_model=ItemTypeAttributeOut)
def update_item_type_attribute(
    attr_id: int,
    payload: ItemTypeAttributeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ItemTypeAttributeOut:
    """Update an item type attribute."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    # Check for duplicate slug if changing it
    if payload.slug is not None and payload.slug != attr.slug:
        existing = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == attr.item_type_id,
            ItemTypeAttribute.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Attribute '{payload.slug}' already exists for this item type"
            )

    # Apply updates
    if payload.slug is not None:
        attr.slug = payload.slug
    if payload.display_name is not None:
        attr.display_name = payload.display_name
    if payload.input_type is not None:
        attr.input_type = payload.input_type
    if payload.is_required is not None:
        attr.is_required = payload.is_required
    if payload.allow_none is not None:
        attr.allow_none = payload.allow_none
    if payload.min_selections is not None:
        attr.min_selections = payload.min_selections
    if payload.max_selections is not None:
        attr.max_selections = payload.max_selections
    if payload.display_order is not None:
        attr.display_order = payload.display_order
    if payload.ask_in_conversation is not None:
        attr.ask_in_conversation = payload.ask_in_conversation
    if payload.question_text is not None:
        attr.question_text = payload.question_text

    db.commit()
    db.refresh(attr)

    logger.info("Updated item type attribute: %s (id=%d)", attr.slug, attr.id)

    return _serialize_attribute(attr, db)


@admin_item_type_attributes_router.delete("/{attr_id}", status_code=204)
def delete_item_type_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete an item type attribute."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    logger.info(
        "Deleting item type attribute: %s for %s (id=%d)",
        attr.slug,
        attr.item_type.slug if attr.item_type else "unknown",
        attr.id
    )
    db.delete(attr)
    db.commit()
    return None


# =============================================================================
# Attribute Options Endpoints
# =============================================================================

@admin_item_type_attributes_router.get(
    "/{attr_id}/options",
    response_model=List[AttributeOptionOut],
    summary="List options for an attribute"
)
def list_attribute_options(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[AttributeOptionOut]:
    """List all options for a specific item type attribute.

    If loads_from_ingredients=True, returns options from item_type_ingredients
    joined to ingredients. Otherwise returns options from attribute_options.
    """
    # Verify attribute exists
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    if attr.loads_from_ingredients and attr.ingredient_group:
        # Load options from item_type_ingredients -> ingredients
        ingredient_links = (
            db.query(ItemTypeIngredient)
            .join(Ingredient)
            .filter(
                ItemTypeIngredient.item_type_id == attr.item_type_id,
                ItemTypeIngredient.ingredient_group == attr.ingredient_group,
            )
            .order_by(ItemTypeIngredient.display_order)
            .all()
        )

        # Build price map from GlobalAttributeOption (source of truth for pricing)
        ingredient_ids = [link.ingredient_id for link in ingredient_links]
        price_map = {}
        if ingredient_ids:
            global_options = (
                db.query(GlobalAttributeOption.ingredient_id, GlobalAttributeOption.price_modifier)
                .filter(GlobalAttributeOption.ingredient_id.in_(ingredient_ids))
                .all()
            )
            price_map = {opt.ingredient_id: opt.price_modifier for opt in global_options}

        return [
            AttributeOptionOut(
                id=link.id,
                slug=link.ingredient.slug,
                display_name=link.display_name_override or link.ingredient.name,
                price_modifier=float(price_map.get(link.ingredient_id, 0.0)),
                is_default=link.is_default,
                is_available=link.is_available and link.ingredient.is_available,
                display_order=link.display_order,
                ingredient_id=link.ingredient_id,
                ingredient_name=link.ingredient.name,
            )
            for link in ingredient_links
        ]

    # For non-ingredient attributes, options should be managed via global attributes
    # (GlobalAttributeOption via ItemTypeGlobalAttribute links).
    # The attribute_options table has been removed.
    return []


# =============================================================================
# Ingredient Link Endpoints (for loads_from_ingredients=True attributes)
# =============================================================================

@admin_item_type_attributes_router.get(
    "/{attr_id}/available-ingredients",
    response_model=List[AvailableIngredientOut],
    summary="List ingredients available to link"
)
def list_available_ingredients(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> List[AvailableIngredientOut]:
    """List ingredients that can be linked to this attribute.

    Returns ingredients that are NOT already linked to this attribute's
    ingredient_group for this item type.
    """
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    if not attr.loads_from_ingredients:
        raise HTTPException(
            status_code=400,
            detail="This attribute does not use ingredient-based options"
        )

    # Get IDs of already-linked ingredients
    linked_ids = (
        db.query(ItemTypeIngredient.ingredient_id)
        .filter(
            ItemTypeIngredient.item_type_id == attr.item_type_id,
            ItemTypeIngredient.ingredient_group == attr.ingredient_group,
        )
        .all()
    )
    linked_ingredient_ids = {row[0] for row in linked_ids}

    # Get all ingredients not already linked
    ingredients = (
        db.query(Ingredient)
        .filter(~Ingredient.id.in_(linked_ingredient_ids) if linked_ingredient_ids else True)
        .order_by(Ingredient.category, Ingredient.name)
        .all()
    )

    return [
        AvailableIngredientOut(
            id=ing.id,
            name=ing.name,
            slug=ing.slug,
            category=ing.category,
            is_available=ing.is_available,
        )
        for ing in ingredients
    ]


@admin_item_type_attributes_router.post(
    "/{attr_id}/ingredient-links",
    response_model=AttributeOptionOut,
    status_code=201,
    summary="Link an ingredient to an attribute"
)
def create_ingredient_link(
    attr_id: int,
    payload: IngredientLinkCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeOptionOut:
    """Link an ingredient to an attribute (creates ItemTypeIngredient row)."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    if not attr.loads_from_ingredients or not attr.ingredient_group:
        raise HTTPException(
            status_code=400,
            detail="This attribute does not use ingredient-based options"
        )

    # Verify ingredient exists
    ingredient = db.query(Ingredient).filter(Ingredient.id == payload.ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    # Check if already linked
    existing = db.query(ItemTypeIngredient).filter(
        ItemTypeIngredient.item_type_id == attr.item_type_id,
        ItemTypeIngredient.ingredient_id == payload.ingredient_id,
        ItemTypeIngredient.ingredient_group == attr.ingredient_group,
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ingredient '{ingredient.name}' is already linked to this attribute"
        )

    # Create the link (pricing is managed via GlobalAttributeOption, not here)
    link = ItemTypeIngredient(
        item_type_id=attr.item_type_id,
        ingredient_id=payload.ingredient_id,
        ingredient_group=attr.ingredient_group,
        display_name_override=payload.display_name_override,
        is_default=payload.is_default,
        is_available=payload.is_available,
        display_order=payload.display_order,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    logger.info(
        "Linked ingredient %s to attribute %s (link_id=%d)",
        ingredient.name,
        attr.slug,
        link.id
    )

    # Look up price from GlobalAttributeOption (source of truth)
    global_opt = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.ingredient_id == ingredient.id
    ).first()
    price_modifier = float(global_opt.price_modifier) if global_opt else 0.0

    return AttributeOptionOut(
        id=link.id,
        slug=ingredient.slug,
        display_name=link.display_name_override or ingredient.name,
        price_modifier=price_modifier,
        is_default=link.is_default,
        is_available=link.is_available and ingredient.is_available,
        display_order=link.display_order,
        ingredient_id=ingredient.id,
        ingredient_name=ingredient.name,
    )


@admin_item_type_attributes_router.put(
    "/{attr_id}/ingredient-links/{link_id}",
    response_model=AttributeOptionOut,
    summary="Update an ingredient link"
)
def update_ingredient_link(
    attr_id: int,
    link_id: int,
    payload: IngredientLinkUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> AttributeOptionOut:
    """Update an ingredient link's settings (display name, availability, etc.).

    NOTE: Pricing is managed via GlobalAttributeOption.price_modifier, not here.
    """
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    if not attr.loads_from_ingredients:
        raise HTTPException(
            status_code=400,
            detail="This attribute does not use ingredient-based options"
        )

    # Find the link
    link = db.query(ItemTypeIngredient).filter(
        ItemTypeIngredient.id == link_id,
        ItemTypeIngredient.item_type_id == attr.item_type_id,
        ItemTypeIngredient.ingredient_group == attr.ingredient_group,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ingredient link not found")

    # Apply updates (pricing is managed via GlobalAttributeOption, not here)
    if payload.display_name_override is not None:
        link.display_name_override = payload.display_name_override
    if payload.is_default is not None:
        link.is_default = payload.is_default
    if payload.is_available is not None:
        link.is_available = payload.is_available
    if payload.display_order is not None:
        link.display_order = payload.display_order

    db.commit()
    db.refresh(link)

    logger.info("Updated ingredient link: %s (id=%d)", link.ingredient.name, link.id)

    # Look up price from GlobalAttributeOption (source of truth)
    global_opt = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.ingredient_id == link.ingredient_id
    ).first()
    price_modifier = float(global_opt.price_modifier) if global_opt else 0.0

    return AttributeOptionOut(
        id=link.id,
        slug=link.ingredient.slug,
        display_name=link.display_name_override or link.ingredient.name,
        price_modifier=price_modifier,
        is_default=link.is_default,
        is_available=link.is_available and link.ingredient.is_available,
        display_order=link.display_order,
        ingredient_id=link.ingredient_id,
        ingredient_name=link.ingredient.name,
    )


@admin_item_type_attributes_router.delete(
    "/{attr_id}/ingredient-links/{link_id}",
    status_code=204,
    summary="Remove an ingredient link"
)
def delete_ingredient_link(
    attr_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Remove an ingredient from an attribute (deletes ItemTypeIngredient row)."""
    attr = db.query(ItemTypeAttribute).filter(ItemTypeAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Item type attribute not found")

    if not attr.loads_from_ingredients:
        raise HTTPException(
            status_code=400,
            detail="This attribute does not use ingredient-based options"
        )

    # Find the link
    link = db.query(ItemTypeIngredient).filter(
        ItemTypeIngredient.id == link_id,
        ItemTypeIngredient.item_type_id == attr.item_type_id,
        ItemTypeIngredient.ingredient_group == attr.ingredient_group,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Ingredient link not found")

    logger.info(
        "Removing ingredient link: %s from attribute %s (id=%d)",
        link.ingredient.name,
        attr.slug,
        link.id
    )
    db.delete(link)
    db.commit()
    return None
