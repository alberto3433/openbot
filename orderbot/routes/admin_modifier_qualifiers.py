"""
Admin Modifier Qualifiers Routes for Orderbot
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
"""

from typing import Any

from sqlalchemy.orm import Session

from ..models import ModifierQualifier
from ..schemas.modifier_qualifiers import (
    ModifierQualifierCreate,
    ModifierQualifierUpdate,
    ModifierQualifierOut,
    ModifierQualifierList,
)
from .crud_factory import CRUDRouterFactory


def _build_create_kwargs(payload: ModifierQualifierCreate, db: Session) -> dict[str, Any]:
    """Build model kwargs from create payload with normalization."""
    return {
        "pattern": payload.pattern.lower().strip(),
        "normalized_form": payload.normalized_form.lower().strip(),
        "category": payload.category,
        "is_active": payload.is_active,
    }


def _handle_before_update(
    item: ModifierQualifier,
    payload: ModifierQualifierUpdate,
    db: Session,
) -> None:
    """Apply update payload to item with normalization."""
    if payload.pattern is not None:
        item.pattern = payload.pattern.lower().strip()
    if payload.normalized_form is not None:
        item.normalized_form = payload.normalized_form.lower().strip()
    if payload.category is not None:
        item.category = payload.category
    if payload.is_active is not None:
        item.is_active = payload.is_active


def _build_list_response(
    items: list[ModifierQualifierOut],
    total: int,
) -> ModifierQualifierList:
    """Build list response wrapper."""
    return ModifierQualifierList(qualifiers=items, total=total)


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=ModifierQualifier,
    create_schema=ModifierQualifierCreate,
    update_schema=ModifierQualifierUpdate,
    response_schema=ModifierQualifierOut,
    prefix="/admin/modifier-qualifiers",
    tags=["Admin - Modifier Qualifiers"],
    id_param="qualifier_id",
    not_found_message="Modifier qualifier not found",
    unique_fields=["pattern"],
    order_by=["category", "normalized_form", "pattern"],
    on_before_create=_build_create_kwargs,
    on_before_update=_handle_before_update,
    list_response_schema=ModifierQualifierList,
    list_response_builder=_build_list_response,
)

# Export the router
admin_modifier_qualifiers_router = _crud.router
