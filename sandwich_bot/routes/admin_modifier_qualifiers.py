"""
Admin Modifier Qualifiers Routes for Sandwich Bot
==================================================

This module contains admin endpoints for managing modifier qualifiers.
Qualifiers are patterns like "extra", "light", "on the side" that modify
how customers want their food prepared.

Endpoints:
----------
- GET /admin/modifier-qualifiers: List all qualifiers
- POST /admin/modifier-qualifiers: Create a new qualifier
- GET /admin/modifier-qualifiers/{id}: Get a specific qualifier
- PUT /admin/modifier-qualifiers/{id}: Update a qualifier
- DELETE /admin/modifier-qualifiers/{id}: Delete a qualifier

Categories:
-----------
Qualifiers are organized into categories for conflict detection:
- **amount**: Quantity modifiers (extra, light, double) - can conflict
- **position**: Location modifiers (on the side) - no conflict with amount
- **preparation**: How to prepare (crispy, well done) - no conflict with amount

Authentication:
---------------
All endpoints require admin authentication via HTTP Basic Auth.

Usage:
------
    # Add a new qualifier
    POST /admin/modifier-qualifiers
    {
        "pattern": "super extra",
        "normalized_form": "extra",
        "category": "amount"
    }

    # Update a qualifier
    PUT /admin/modifier-qualifiers/5
    {
        "is_active": false
    }
"""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_admin_credentials
from ..db import get_db
from ..models import ModifierQualifier
from ..schemas.modifier_qualifiers import (
    ModifierQualifierCreate,
    ModifierQualifierUpdate,
    ModifierQualifierOut,
    ModifierQualifierList,
)


logger = logging.getLogger(__name__)

# Router definition
admin_modifier_qualifiers_router = APIRouter(
    prefix="/admin/modifier-qualifiers",
    tags=["Admin - Modifier Qualifiers"]
)


# =============================================================================
# Modifier Qualifier Endpoints
# =============================================================================

@admin_modifier_qualifiers_router.get("", response_model=ModifierQualifierList)
def list_modifier_qualifiers(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierQualifierList:
    """List all modifier qualifiers."""
    qualifiers = db.query(ModifierQualifier).order_by(
        ModifierQualifier.category,
        ModifierQualifier.normalized_form,
        ModifierQualifier.pattern
    ).all()

    return ModifierQualifierList(
        qualifiers=[ModifierQualifierOut.model_validate(q) for q in qualifiers],
        total=len(qualifiers)
    )


@admin_modifier_qualifiers_router.post("", response_model=ModifierQualifierOut, status_code=201)
def create_modifier_qualifier(
    payload: ModifierQualifierCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierQualifierOut:
    """Create a new modifier qualifier."""
    # Check for duplicate pattern
    existing = db.query(ModifierQualifier).filter(
        ModifierQualifier.pattern == payload.pattern.lower().strip()
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"A qualifier with pattern '{payload.pattern}' already exists"
        )

    qualifier = ModifierQualifier(
        pattern=payload.pattern.lower().strip(),
        normalized_form=payload.normalized_form.lower().strip(),
        category=payload.category,
        is_active=payload.is_active,
    )
    db.add(qualifier)
    db.commit()
    db.refresh(qualifier)

    logger.info(
        "Created modifier qualifier: %s -> %s (%s)",
        qualifier.pattern,
        qualifier.normalized_form,
        qualifier.category
    )
    return ModifierQualifierOut.model_validate(qualifier)


@admin_modifier_qualifiers_router.get("/{qualifier_id}", response_model=ModifierQualifierOut)
def get_modifier_qualifier(
    qualifier_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierQualifierOut:
    """Get a specific modifier qualifier by ID."""
    qualifier = db.query(ModifierQualifier).filter(
        ModifierQualifier.id == qualifier_id
    ).first()

    if not qualifier:
        raise HTTPException(status_code=404, detail="Modifier qualifier not found")

    return ModifierQualifierOut.model_validate(qualifier)


@admin_modifier_qualifiers_router.put("/{qualifier_id}", response_model=ModifierQualifierOut)
def update_modifier_qualifier(
    qualifier_id: int,
    payload: ModifierQualifierUpdate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> ModifierQualifierOut:
    """Update a modifier qualifier."""
    qualifier = db.query(ModifierQualifier).filter(
        ModifierQualifier.id == qualifier_id
    ).first()

    if not qualifier:
        raise HTTPException(status_code=404, detail="Modifier qualifier not found")

    # Update fields if provided
    if payload.pattern is not None:
        new_pattern = payload.pattern.lower().strip()
        # Check for duplicate pattern (excluding self)
        existing = db.query(ModifierQualifier).filter(
            ModifierQualifier.pattern == new_pattern,
            ModifierQualifier.id != qualifier_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"A qualifier with pattern '{payload.pattern}' already exists"
            )
        qualifier.pattern = new_pattern

    if payload.normalized_form is not None:
        qualifier.normalized_form = payload.normalized_form.lower().strip()

    if payload.category is not None:
        qualifier.category = payload.category

    if payload.is_active is not None:
        qualifier.is_active = payload.is_active

    db.commit()
    db.refresh(qualifier)

    logger.info(
        "Updated modifier qualifier %d: %s -> %s (%s)",
        qualifier.id,
        qualifier.pattern,
        qualifier.normalized_form,
        qualifier.category
    )
    return ModifierQualifierOut.model_validate(qualifier)


@admin_modifier_qualifiers_router.delete("/{qualifier_id}", status_code=204)
def delete_modifier_qualifier(
    qualifier_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
) -> None:
    """Delete a modifier qualifier."""
    qualifier = db.query(ModifierQualifier).filter(
        ModifierQualifier.id == qualifier_id
    ).first()

    if not qualifier:
        raise HTTPException(status_code=404, detail="Modifier qualifier not found")

    pattern = qualifier.pattern
    db.delete(qualifier)
    db.commit()

    logger.info("Deleted modifier qualifier: %s", pattern)
