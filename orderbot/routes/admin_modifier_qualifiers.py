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

from ..db.models import ModifierQualifier
from ..schemas.modifier_qualifiers import (
    ModifierQualifierCreate,
    ModifierQualifierUpdate,
    ModifierQualifierOut,
    ModifierQualifierList,
)
from .crud_factory import CRUDRouterFactory
from .crud_helpers import make_list_builder


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
    normalize_fields={"pattern": "lower_strip", "normalized_form": "lower_strip"},
    list_response_schema=ModifierQualifierList,
    list_response_builder=make_list_builder(ModifierQualifierList, "qualifiers"),
)

# Export the router
admin_modifier_qualifiers_router = _crud.router
