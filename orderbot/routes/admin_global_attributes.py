"""
Admin Global Attributes Routes for Orderbot
================================================

This module contains admin endpoints for managing global (normalized) attributes
that are shared across item types.

Related modules:
- admin_global_attribute_options.py: Options and skip rule endpoints
- admin_item_type_global_attrs.py: Item type link endpoints

Endpoints:
----------
Global Attributes:
- GET /admin/global-attributes: List all global attributes
- GET /admin/global-attributes/{id}: Get a specific global attribute with options
- POST /admin/global-attributes: Create a new global attribute
- PUT /admin/global-attributes/{id}: Update a global attribute
- DELETE /admin/global-attributes/{id}: Delete a global attribute

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, selectinload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    GlobalAttribute,
    GlobalAttributeOption,
    GlobalAttributeOptionSkip,
    Ingredient,
    ItemTypeGlobalAttribute,
)
from ..schemas.global_attributes import (
    GlobalAttributeOut,
    GlobalAttributeListOut,
    GlobalAttributeCreate,
    GlobalAttributeUpdate,
    GlobalAttributeWithOptionsCreate,
)
from ..schemas.serializers import (
    serialize_global_attribute,
    serialize_global_attribute_list,
)
from .crud_helpers import get_or_404

logger = logging.getLogger(__name__)

# Router definition
admin_global_attributes_router = APIRouter(
    prefix="/admin/global-attributes",
    tags=["Admin - Global Attributes"]
)

# Separate router for item type links
admin_item_type_global_attrs_router = APIRouter(
    prefix="/admin/item-types",
    tags=["Admin - Item Type Global Attributes"]
)


# =============================================================================
# Global Attribute Endpoints
# =============================================================================

@admin_global_attributes_router.get("", response_model=list[GlobalAttributeListOut])
def list_global_attributes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    input_type: str | None = Query(None, description="Filter by input type"),
) -> list[GlobalAttributeListOut]:
    """List all global attributes."""
    # Eager load relationships to get counts without N+1 queries
    query = db.query(GlobalAttribute).options(
        selectinload(GlobalAttribute.options),
        selectinload(GlobalAttribute.item_type_links),
    )

    if input_type:
        query = query.filter(GlobalAttribute.input_type == input_type)

    attrs = query.order_by(GlobalAttribute.display_name).all()
    return [serialize_global_attribute_list(attr, db) for attr in attrs]


@admin_global_attributes_router.get("/{attr_id}", response_model=GlobalAttributeOut)
def get_global_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Get a specific global attribute by ID, including all options."""
    # Eager load all relationships to avoid N+1 queries
    attr = (
        db.query(GlobalAttribute)
        .options(
            selectinload(GlobalAttribute.options)
            .joinedload(GlobalAttributeOption.ingredient)
            .joinedload(Ingredient.modifier_category),
            selectinload(GlobalAttribute.options)
            .selectinload(GlobalAttributeOption.skip_rules)
            .joinedload(GlobalAttributeOptionSkip.skipped_attribute),
            selectinload(GlobalAttribute.options)
            .joinedload(GlobalAttributeOption.forward_to_attribute),
            selectinload(GlobalAttribute.item_type_links)
            .joinedload(ItemTypeGlobalAttribute.item_type),
        )
        .filter(GlobalAttribute.id == attr_id)
        .first()
    )
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")
    return serialize_global_attribute(attr, db)


@admin_global_attributes_router.post("", response_model=GlobalAttributeOut, status_code=201)
def create_global_attribute(
    payload: GlobalAttributeCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Create a new global attribute."""
    # Check for duplicate slug
    existing = db.query(GlobalAttribute).filter(
        GlobalAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Global attribute with slug '{payload.slug}' already exists"
        )

    attr = GlobalAttribute(
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        description=payload.description,
        question_text=payload.question_text,
        offer_question_text=payload.offer_question_text,
        options_source_category=payload.options_source_category,
    )
    db.add(attr)
    db.commit()
    db.refresh(attr)

    logger.info("Created global attribute: %s (id=%d)", attr.slug, attr.id)
    return serialize_global_attribute(attr, db)


@admin_global_attributes_router.post(
    "/with-options",
    response_model=GlobalAttributeOut,
    status_code=201,
    summary="Create attribute with options"
)
def create_global_attribute_with_options(
    payload: GlobalAttributeWithOptionsCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Create a new global attribute with options in one call."""
    # Check for duplicate slug
    existing = db.query(GlobalAttribute).filter(
        GlobalAttribute.slug == payload.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Global attribute with slug '{payload.slug}' already exists"
        )

    attr = GlobalAttribute(
        slug=payload.slug,
        display_name=payload.display_name,
        input_type=payload.input_type,
        description=payload.description,
        question_text=payload.question_text,
        offer_question_text=payload.offer_question_text,
        options_source_category=payload.options_source_category,
    )
    db.add(attr)
    db.flush()  # Get the ID

    # Add options
    for i, opt_data in enumerate(payload.options):
        # Auto-find matching ingredient by name or slug
        ingredient = None
        if opt_data.ingredient_id:
            ingredient = db.query(Ingredient).filter(Ingredient.id == opt_data.ingredient_id).first()
        elif opt_data.slug and opt_data.display_name:
            ingredient = db.query(Ingredient).filter(
                (Ingredient.name == opt_data.display_name) |
                (Ingredient.slug == opt_data.slug)
            ).first()
        ingredient_id = ingredient.id if ingredient else None

        # Ingredient-linked: store NULL (derived at read time)
        db_slug = None if ingredient else opt_data.slug
        db_display_name = None if ingredient else opt_data.display_name

        option = GlobalAttributeOption(
            global_attribute_id=attr.id,
            slug=db_slug,
            display_name=db_display_name,
            price_modifier=opt_data.price_modifier,
            is_default=opt_data.is_default,
            is_available=opt_data.is_available,
            display_order=opt_data.display_order if opt_data.display_order else i,
            ingredient_id=ingredient_id,
        )
        db.add(option)
        if ingredient:
            logger.info(
                "Auto-linked option '%s' to Ingredient '%s' (id=%d)",
                display_name, ingredient.name, ingredient.id
            )

    db.commit()
    db.refresh(attr)

    logger.info(
        "Created global attribute: %s with %d options (id=%d)",
        attr.slug,
        len(payload.options),
        attr.id
    )
    return serialize_global_attribute(attr, db)


@admin_global_attributes_router.put("/{attr_id}", response_model=GlobalAttributeOut)
def update_global_attribute(
    attr_id: int,
    payload: GlobalAttributeUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOut:
    """Update a global attribute."""
    attr = get_or_404(db, GlobalAttribute, attr_id, detail="Global attribute not found")

    # Check for duplicate slug if changing
    if payload.slug is not None and payload.slug != attr.slug:
        existing = db.query(GlobalAttribute).filter(
            GlobalAttribute.slug == payload.slug
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Global attribute with slug '{payload.slug}' already exists"
            )

    # Apply updates - use model_fields_set to detect explicit null (clearing a field)
    # For string fields, also skip empty strings (treat "" same as None for updates)
    if payload.slug:
        attr.slug = payload.slug
    if payload.display_name:
        attr.display_name = payload.display_name
    if payload.input_type:
        attr.input_type = payload.input_type
    if "description" in payload.model_fields_set:
        attr.description = payload.description
    if "question_text" in payload.model_fields_set:
        attr.question_text = payload.question_text
    if "offer_question_text" in payload.model_fields_set:
        attr.offer_question_text = payload.offer_question_text
    if "options_source_category" in payload.model_fields_set:
        attr.options_source_category = payload.options_source_category

    db.commit()
    db.refresh(attr)

    logger.info("Updated global attribute: %s (id=%d)", attr.slug, attr.id)
    return serialize_global_attribute(attr, db)


@admin_global_attributes_router.delete("/{attr_id}", status_code=204)
def delete_global_attribute(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a global attribute (and all its options)."""
    attr = get_or_404(db, GlobalAttribute, attr_id, detail="Global attribute not found")

    # Check for RESTRICT-protected references before attempting delete
    dependents: list[str] = []

    link_count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.global_attribute_id == attr_id
    ).count()
    if link_count > 0:
        dependents.append(f"{link_count} item type link(s)")

    option_count = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id
    ).count()
    if option_count > 0:
        dependents.append(f"{option_count} option(s)")

    if dependents:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete attribute '{attr.slug}' — it still has: "
                   f"{', '.join(dependents)}. Remove these first."
        )

    logger.info("Deleting global attribute: %s (id=%d)", attr.slug, attr.id)
    db.delete(attr)
    db.commit()
    return None
