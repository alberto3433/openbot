"""
Admin Global Attribute Options Routes for Orderbot
======================================================

This module contains admin endpoints for managing global attribute options
and skip rules. Split from admin_global_attributes.py for maintainability.

Endpoints:
----------
Global Attribute Options:
- GET /admin/global-attributes/{id}/options: List options for an attribute
- POST /admin/global-attributes/{id}/options: Add an option to an attribute
- PUT /admin/global-attributes/{id}/options/{option_id}: Update an option
- DELETE /admin/global-attributes/{id}/options/{option_id}: Delete an option
- POST /admin/global-attributes/{id}/options/auto-link-ingredients: Auto-link by slug
- POST /admin/global-attributes/{id}/options/from-ingredient/{ingredient_id}: Create from ingredient
- GET /admin/global-attributes/{id}/unlinked-ingredients: List unlinked ingredients

Skip Rules:
- GET /admin/global-attributes/{id}/options/{option_id}/skip-rules: List skip rules
- POST /admin/global-attributes/{id}/options/{option_id}/skip-rules: Add a skip rule
- DELETE /admin/global-attributes/{id}/options/{option_id}/skip-rules/{rule_id}: Delete

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.
"""

import logging

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from ..auth import verify_admin_credentials
from ..db import get_db
from ..db.models import (
    GlobalAttribute,
    GlobalAttributeOption,
    GlobalAttributeOptionSkip,
    Ingredient,
)
from ..services.alias_service import sync_entity_aliases
from ..schemas.global_attributes import (
    GlobalAttributeOptionOut,
    GlobalAttributeOptionCreate,
    GlobalAttributeOptionUpdate,
    GlobalAttributeOptionFromIngredientCreate,
    SkipRuleOut,
    SkipRuleCreate,
)
from ..schemas.serializers import serialize_global_attribute_option
from .admin_global_attributes import admin_global_attributes_router

logger = logging.getLogger(__name__)


# =============================================================================
# Global Attribute Option Endpoints
# =============================================================================

@admin_global_attributes_router.get(
    "/{attr_id}/options",
    response_model=list[GlobalAttributeOptionOut],
    summary="List options for an attribute"
)
def list_global_attribute_options(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[GlobalAttributeOptionOut]:
    """List all options for a global attribute."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    return [serialize_global_attribute_option(opt, db) for opt in attr.options]


@admin_global_attributes_router.post(
    "/{attr_id}/options",
    response_model=GlobalAttributeOptionOut,
    status_code=201,
    summary="Add an option to an attribute"
)
def create_global_attribute_option(
    attr_id: int,
    payload: GlobalAttributeOptionCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOptionOut:
    """Add a new option to a global attribute."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Determine ingredient_id: use provided value, or auto-find matching ingredient
    ingredient_id = payload.ingredient_id
    ingredient = None
    if ingredient_id is not None:
        # Validate provided ingredient_id
        ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
        if not ingredient:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient with id {ingredient_id} not found"
            )
    elif payload.slug and payload.display_name:
        # Auto-find matching ingredient by name or slug
        ingredient = db.query(Ingredient).filter(
            (Ingredient.name == payload.display_name) |
            (Ingredient.slug == payload.slug)
        ).first()
        if ingredient:
            ingredient_id = ingredient.id
            logger.info(
                "Auto-linked new option '%s' to Ingredient '%s' (id=%d)",
                payload.display_name, ingredient.name, ingredient.id
            )

    # When ingredient-linked: store NULL, derive at read time
    # When not linked: require slug/display_name from payload
    if ingredient:
        effective_slug = ingredient.slug
        db_slug = None
        db_display_name = None
    else:
        if not payload.slug or not payload.display_name:
            raise HTTPException(
                status_code=400,
                detail="Slug and display name are required (or link an ingredient)"
            )
        effective_slug = payload.slug
        db_slug = payload.slug
        db_display_name = payload.display_name

    # Check for duplicate slug (using ingredient slug or payload slug)
    existing = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.slug == effective_slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Option with slug '{effective_slug}' already exists for this attribute"
        )

    # Also check for duplicate ingredient link
    if ingredient_id:
        existing_link = db.query(GlobalAttributeOption).filter(
            GlobalAttributeOption.global_attribute_id == attr_id,
            GlobalAttributeOption.ingredient_id == ingredient_id
        ).first()
        if existing_link:
            raise HTTPException(
                status_code=400,
                detail=f"Ingredient '{ingredient.name}' is already linked to an option for this attribute"
            )

    # Validate forward_to_attribute_id if provided
    forward_to_attribute_id = payload.forward_to_attribute_id
    if forward_to_attribute_id is not None:
        forward_attr = db.query(GlobalAttribute).filter(
            GlobalAttribute.id == forward_to_attribute_id
        ).first()
        if not forward_attr:
            raise HTTPException(
                status_code=400,
                detail=f"Forward-to attribute with id {forward_to_attribute_id} not found"
            )

    option = GlobalAttributeOption(
        global_attribute_id=attr_id,
        slug=db_slug,
        display_name=db_display_name,
        price_modifier=payload.price_modifier,
        is_default=payload.is_default,
        is_available=payload.is_available,
        display_order=payload.display_order,
        ingredient_id=ingredient_id,
        forward_to_attribute_id=forward_to_attribute_id,
    )
    db.add(option)
    db.flush()  # Get the ID before syncing aliases

    # Handle aliases if provided
    if payload.aliases is not None:
        try:
            sync_entity_aliases(db, option, payload.aliases, "global_attribute_option")
        except ValueError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(option)

    logger.info(
        "Created global attribute option: %s for %s (id=%d, ingredient_id=%s)",
        option.slug,
        attr.slug,
        option.id,
        option.ingredient_id,
    )
    return serialize_global_attribute_option(option, db)


@admin_global_attributes_router.put(
    "/{attr_id}/options/{option_id}",
    response_model=GlobalAttributeOptionOut,
    summary="Update an option"
)
def update_global_attribute_option(
    attr_id: int,
    option_id: int,
    payload: GlobalAttributeOptionUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOptionOut:
    """Update a global attribute option."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Determine effective ingredient_id after this update
    effective_ingredient_id = option.ingredient_id
    if "ingredient_id" in payload.model_fields_set:
        effective_ingredient_id = payload.ingredient_id

    # Only allow slug/display_name changes for non-ingredient-linked options
    if not effective_ingredient_id:
        if payload.slug is not None and payload.slug != option.slug:
            existing = db.query(GlobalAttributeOption).filter(
                GlobalAttributeOption.global_attribute_id == attr_id,
                GlobalAttributeOption.slug == payload.slug
            ).first()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Option with slug '{payload.slug}' already exists"
                )
        if payload.slug is not None:
            option.slug = payload.slug
        if payload.display_name is not None:
            option.display_name = payload.display_name

    # Apply updates
    if payload.price_modifier is not None:
        option.price_modifier = payload.price_modifier
    if payload.is_default is not None:
        option.is_default = payload.is_default
    if payload.is_available is not None:
        option.is_available = payload.is_available
    if payload.display_order is not None:
        option.display_order = payload.display_order

    # Handle ingredient_id - check model_fields_set to distinguish None from not provided
    if "ingredient_id" in payload.model_fields_set:
        if payload.ingredient_id is not None:
            # Validate ingredient exists
            ingredient = db.query(Ingredient).filter(Ingredient.id == payload.ingredient_id).first()
            if not ingredient:
                raise HTTPException(
                    status_code=400,
                    detail=f"Ingredient with id {payload.ingredient_id} not found"
                )
            # Ingredient-linked: NULL out slug/display_name (derived at read time)
            option.slug = None
            option.display_name = None
        else:
            # Unlinking ingredient: slug/display_name must be provided
            if not option.slug:
                if payload.slug:
                    option.slug = payload.slug
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Slug is required when unlinking an ingredient"
                    )
            if not option.display_name:
                if payload.display_name:
                    option.display_name = payload.display_name
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Display name is required when unlinking an ingredient"
                    )
        option.ingredient_id = payload.ingredient_id

    # Handle forward_to_attribute_id - check model_fields_set to distinguish None from not provided
    if "forward_to_attribute_id" in payload.model_fields_set:
        if payload.forward_to_attribute_id is not None:
            # Validate forward-to attribute exists
            forward_attr = db.query(GlobalAttribute).filter(
                GlobalAttribute.id == payload.forward_to_attribute_id
            ).first()
            if not forward_attr:
                raise HTTPException(
                    status_code=400,
                    detail=f"Forward-to attribute with id {payload.forward_to_attribute_id} not found"
                )
        option.forward_to_attribute_id = payload.forward_to_attribute_id

    # Handle aliases - check model_fields_set to distinguish None from not provided
    if "aliases" in payload.model_fields_set:
        try:
            sync_entity_aliases(db, option, payload.aliases, "global_attribute_option")
        except ValueError as e:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(option)

    logger.info(
        "Updated global attribute option: %s (id=%d, ingredient_id=%s)",
        option.slug,
        option.id,
        option.ingredient_id,
    )
    return serialize_global_attribute_option(option, db)


@admin_global_attributes_router.delete(
    "/{attr_id}/options/{option_id}",
    status_code=204,
    summary="Delete an option"
)
def delete_global_attribute_option(
    attr_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a global attribute option."""
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    logger.info(
        "Deleting global attribute option: %s from %s (id=%d)",
        option.slug,
        attr.slug,
        option.id
    )
    db.delete(option)
    db.commit()
    return None


@admin_global_attributes_router.post(
    "/{attr_id}/options/auto-link-ingredients",
    summary="Auto-link options to ingredients by matching slug"
)
def auto_link_options_to_ingredients(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> dict:
    """
    Automatically link unlinked options to ingredients by matching slugs.

    For each option without an ingredient_id, attempts to find an ingredient
    with a matching slug and links them.

    Returns:
        Dict with counts of linked and unmatched options.
    """
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Get unlinked options for this attribute
    unlinked_options = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.ingredient_id.is_(None),
    ).all()

    linked = []
    unmatched = []

    for option in unlinked_options:
        # Try to find ingredient with matching slug
        ingredient = db.query(Ingredient).filter(Ingredient.slug == option.slug).first()
        if ingredient:
            linked.append({
                "option_slug": option.slug,
                "ingredient_id": ingredient.id,
                "ingredient_name": ingredient.name,
            })
            # Link and NULL out slug/display_name (derived from ingredient at read time)
            option.ingredient_id = ingredient.id
            option.slug = None
            option.display_name = None
        else:
            unmatched.append(option.slug)

    db.commit()

    logger.info(
        "Auto-linked %d options to ingredients for attribute %s, %d unmatched",
        len(linked),
        attr.slug,
        len(unmatched),
    )

    return {
        "linked_count": len(linked),
        "unmatched_count": len(unmatched),
        "linked": linked,
        "unmatched": unmatched,
    }


@admin_global_attributes_router.post(
    "/{attr_id}/options/from-ingredient/{ingredient_id}",
    response_model=GlobalAttributeOptionOut,
    status_code=201,
    summary="Create option from ingredient"
)
def create_option_from_ingredient(
    attr_id: int,
    ingredient_id: int,
    payload: GlobalAttributeOptionFromIngredientCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> GlobalAttributeOptionOut:
    """
    Create a new option from an existing ingredient.

    This reduces duplicate data entry by auto-populating:
    - slug from ingredient.slug
    - display_name from ingredient.name
    - ingredient_id link

    User only needs to specify price_modifier and display_order.
    """
    # Verify attribute exists
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Verify ingredient exists
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingredient not found")

    # Check if this ingredient is already linked to an option for this attribute
    already_linked = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.ingredient_id == ingredient_id
    ).first()
    if already_linked:
        raise HTTPException(
            status_code=400,
            detail=f"Ingredient '{ingredient.name}' is already linked to an option for this attribute"
        )

    # Check if a non-ingredient option with the same slug already exists
    existing = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.slug == ingredient.slug
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Option with slug '{ingredient.slug}' already exists for this attribute"
        )

    # Create the option - slug/display_name are NULL (derived from ingredient at read time)
    # modifier_category is also derived from ingredient.category at runtime
    option = GlobalAttributeOption(
        global_attribute_id=attr_id,
        slug=None,
        display_name=None,
        price_modifier=payload.price_modifier,
        is_default=payload.is_default,
        is_available=payload.is_available,
        display_order=payload.display_order,
        ingredient_id=ingredient_id,
    )
    db.add(option)
    db.commit()
    db.refresh(option)

    logger.info(
        "Created option '%s' from ingredient '%s' for attribute %s (option_id=%d)",
        option.slug,
        ingredient.name,
        attr.slug,
        option.id,
    )
    return serialize_global_attribute_option(option, db)


@admin_global_attributes_router.get(
    "/{attr_id}/unlinked-ingredients",
    summary="List ingredients not yet linked to this attribute"
)
def list_unlinked_ingredients(
    attr_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[dict]:
    """
    List all ingredients that are NOT yet linked to options for this attribute.

    Useful for the "Create from Ingredient" dropdown in the UI.
    Returns ingredients sorted by name.
    """
    # Verify attribute exists
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Get IDs of already-linked ingredients
    linked_ingredient_ids = db.query(GlobalAttributeOption.ingredient_id).filter(
        GlobalAttributeOption.global_attribute_id == attr_id,
        GlobalAttributeOption.ingredient_id.isnot(None)
    ).all()
    linked_ids = {row[0] for row in linked_ingredient_ids}

    # Get all ingredients not in the linked set
    ingredients = db.query(Ingredient).filter(
        ~Ingredient.id.in_(linked_ids) if linked_ids else True
    ).order_by(Ingredient.name).all()

    return [
        {
            "id": ing.id,
            "slug": ing.slug,
            "name": ing.name,
            "category": ing.category,
        }
        for ing in ingredients
    ]


# =============================================================================
# Skip Rule Endpoints
# =============================================================================

@admin_global_attributes_router.get(
    "/{attr_id}/options/{option_id}/skip-rules",
    response_model=list[SkipRuleOut],
    summary="List skip rules for an option"
)
def list_option_skip_rules(
    attr_id: int,
    option_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> list[SkipRuleOut]:
    """List all skip rules for a global attribute option."""
    # Verify attribute exists
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Get skip rules with skipped_attribute relationship
    rules = (
        db.query(GlobalAttributeOptionSkip)
        .options(joinedload(GlobalAttributeOptionSkip.skipped_attribute))
        .filter(GlobalAttributeOptionSkip.triggering_option_id == option_id)
        .all()
    )

    return [
        SkipRuleOut(
            id=rule.id,
            skipped_attribute_id=rule.skipped_attribute_id,
            skipped_attribute_slug=rule.skipped_attribute.slug,
            skipped_attribute_name=rule.skipped_attribute.display_name,
        )
        for rule in rules
    ]


@admin_global_attributes_router.post(
    "/{attr_id}/options/{option_id}/skip-rules",
    response_model=SkipRuleOut,
    status_code=201,
    summary="Add a skip rule to an option"
)
def create_option_skip_rule(
    attr_id: int,
    option_id: int,
    payload: SkipRuleCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> SkipRuleOut:
    """Add a skip rule to a global attribute option."""
    # Verify attribute exists
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Verify skipped attribute exists
    skipped_attr = db.query(GlobalAttribute).filter(
        GlobalAttribute.id == payload.skipped_attribute_id
    ).first()
    if not skipped_attr:
        raise HTTPException(status_code=404, detail="Skipped attribute not found")

    # Check if skip rule already exists
    existing = db.query(GlobalAttributeOptionSkip).filter(
        GlobalAttributeOptionSkip.triggering_option_id == option_id,
        GlobalAttributeOptionSkip.skipped_attribute_id == payload.skipped_attribute_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Skip rule for attribute '{skipped_attr.display_name}' already exists"
        )

    # Create the skip rule
    rule = GlobalAttributeOptionSkip(
        triggering_option_id=option_id,
        skipped_attribute_id=payload.skipped_attribute_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    logger.info(
        "Created skip rule: option %d (%s) skips attribute %d (%s)",
        option_id,
        option.slug or f"option_{option.id}",
        skipped_attr.id,
        skipped_attr.slug,
    )

    return SkipRuleOut(
        id=rule.id,
        skipped_attribute_id=rule.skipped_attribute_id,
        skipped_attribute_slug=skipped_attr.slug,
        skipped_attribute_name=skipped_attr.display_name,
    )


@admin_global_attributes_router.delete(
    "/{attr_id}/options/{option_id}/skip-rules/{rule_id}",
    status_code=204,
    summary="Delete a skip rule"
)
def delete_option_skip_rule(
    attr_id: int,
    option_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a skip rule from a global attribute option."""
    # Verify attribute exists
    attr = db.query(GlobalAttribute).filter(GlobalAttribute.id == attr_id).first()
    if not attr:
        raise HTTPException(status_code=404, detail="Global attribute not found")

    # Verify option exists and belongs to attribute
    option = db.query(GlobalAttributeOption).filter(
        GlobalAttributeOption.id == option_id,
        GlobalAttributeOption.global_attribute_id == attr_id
    ).first()
    if not option:
        raise HTTPException(status_code=404, detail="Option not found")

    # Find and delete the skip rule
    rule = db.query(GlobalAttributeOptionSkip).filter(
        GlobalAttributeOptionSkip.id == rule_id,
        GlobalAttributeOptionSkip.triggering_option_id == option_id
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Skip rule not found")

    logger.info(
        "Deleting skip rule %d from option %d",
        rule_id,
        option_id,
    )
    db.delete(rule)
    db.commit()
    return None
