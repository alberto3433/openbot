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
- POST /admin/global-attributes/with-options: Create attribute with options
- PUT /admin/global-attributes/{id}: Update a global attribute
- DELETE /admin/global-attributes/{id}: Delete a global attribute

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    GlobalAttribute,
    GlobalAttributeOption,
    GlobalAttributeOptionSkip,
    Ingredient,
    ItemTypeGlobalAttribute,
)
from ..exceptions import ReferentialIntegrityError
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
from .crud_factory import CRUDRouterFactory
from .crud_helpers import check_slug_unique

logger = logging.getLogger(__name__)

# Separate router for item type links (imported by admin_item_type_global_attrs.py)
admin_item_type_global_attrs_router = APIRouter(
    prefix="/admin/item-types",
    tags=["Admin - Item Type Global Attributes"]
)


# =============================================================================
# Factory Callbacks
# =============================================================================

def _to_response(item: GlobalAttribute, db: Session) -> GlobalAttributeOut:
    """Serialize a GlobalAttribute with eager-loaded relationships."""
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
        .filter(GlobalAttribute.id == item.id)
        .first()
    )
    return serialize_global_attribute(attr, db)


def _build_create_kwargs(payload: GlobalAttributeCreate, db: Session) -> dict:
    """Build model kwargs from create payload."""
    return {
        "slug": payload.slug,
        "display_name": payload.display_name,
        "input_type": payload.input_type,
        "description": payload.description,
        "question_text": payload.question_text,
        "offer_question_text": payload.offer_question_text,
        "options_source_category": payload.options_source_category,
    }


def _handle_before_update(item: GlobalAttribute, payload: GlobalAttributeUpdate, db: Session) -> None:
    """Apply update payload to item."""
    if payload.slug is not None and payload.slug != item.slug:
        check_slug_unique(db, GlobalAttribute, payload.slug, exclude_id=item.id)

    if payload.slug:
        item.slug = payload.slug
    if payload.display_name:
        item.display_name = payload.display_name
    if payload.input_type:
        item.input_type = payload.input_type
    if "description" in payload.model_fields_set:
        item.description = payload.description
    if "question_text" in payload.model_fields_set:
        item.question_text = payload.question_text
    if "offer_question_text" in payload.model_fields_set:
        item.offer_question_text = payload.offer_question_text
    if "options_source_category" in payload.model_fields_set:
        item.options_source_category = payload.options_source_category


def _handle_before_delete(item: GlobalAttribute, db: Session) -> None:
    """Check for RESTRICT-protected references before deleting."""
    dependents: list[str] = []

    link_count = db.query(ItemTypeGlobalAttribute).filter(
        ItemTypeGlobalAttribute.global_attribute_id == item.id
    ).count()
    if link_count > 0:
        dependents.append(f"{link_count} item type link(s)")

    option_count = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == item.id
    ).count()
    if option_count > 0:
        dependents.append(f"{option_count} option(s)")

    if dependents:
        raise ReferentialIntegrityError(
            f"Cannot delete attribute '{item.slug}' — it still has: "
            f"{', '.join(dependents)}. Remove these first."
        )


# =============================================================================
# CRUD Factory (create, get, update, delete — list is custom below)
# =============================================================================

_crud = CRUDRouterFactory(
    model=GlobalAttribute,
    create_schema=GlobalAttributeCreate,
    update_schema=GlobalAttributeUpdate,
    response_schema=GlobalAttributeOut,
    prefix="/admin/global-attributes",
    tags=["Admin - Global Attributes"],
    id_param="attr_id",
    not_found_message="Global attribute not found",
    unique_fields=["slug"],
    skip_list=True,
    to_response=_to_response,
    on_before_create=_build_create_kwargs,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
)

# Use factory's router as the main router, add custom endpoints to it
admin_global_attributes_router = _crud.router


# =============================================================================
# Custom Endpoints (list + create-with-options)
# =============================================================================

@admin_global_attributes_router.get("", response_model=list[GlobalAttributeListOut])
def list_global_attributes(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    input_type: str | None = Query(None, description="Filter by input type"),
) -> list[GlobalAttributeListOut]:
    """List all global attributes."""
    query = db.query(GlobalAttribute).options(
        selectinload(GlobalAttribute.options),
        selectinload(GlobalAttribute.item_type_links),
    )

    if input_type:
        query = query.filter(GlobalAttribute.input_type == input_type)

    attrs = query.order_by(GlobalAttribute.display_name).all()
    return [serialize_global_attribute_list(attr, db) for attr in attrs]


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
    check_slug_unique(db, GlobalAttribute, payload.slug)

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
                opt_data.display_name, ingredient.name, ingredient.id
            )

    db.commit()
    db.refresh(attr)

    logger.info(
        "Created global attribute: %s with %d options (id=%d)",
        attr.slug,
        len(payload.options),
        attr.id
    )
    return _to_response(attr, db)
