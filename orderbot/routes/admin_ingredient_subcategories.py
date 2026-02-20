"""
Admin Ingredient Subcategories Routes for Orderbot
======================================================

CRUD endpoints for managing ingredient subcategories. Subcategories group
ingredients within a category (e.g., 'bagel' under 'bread', 'cream_cheese'
under 'spread').

Endpoints:
----------
- GET /admin/ingredient-subcategories: List all (optional ?category_slug= filter)
- POST /admin/ingredient-subcategories: Create
- GET /admin/ingredient-subcategories/{id}: Get
- PUT /admin/ingredient-subcategories/{id}: Update
- DELETE /admin/ingredient-subcategories/{id}: Delete
"""

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..db.models import Ingredient, IngredientCategory, IngredientSubcategory
from ..auth import verify_admin_credentials
from ..exceptions import ValidationError, ReferentialIntegrityError
from ..schemas.ingredient_subcategories import (
    IngredientSubcategoryCreate,
    IngredientSubcategoryList,
    IngredientSubcategoryOut,
    IngredientSubcategoryUpdate,
)
from .crud_factory import CRUDRouterFactory
from .crud_helpers import apply_payload_updates, check_slug_unique, make_list_builder


def _handle_before_create(payload: IngredientSubcategoryCreate, db: Session) -> dict:
    """Validate parent category and build model kwargs."""
    slug = payload.slug.lower().strip()
    category_slug = payload.category_slug.lower().strip()

    # Validate parent category exists
    cat = db.query(IngredientCategory).filter(
        IngredientCategory.slug == category_slug
    ).first()
    if not cat:
        raise ValidationError(f"Category '{category_slug}' not found")

    return {
        "slug": slug,
        "display_name": payload.display_name.strip(),
        "category_slug": category_slug,
        "display_order": payload.display_order,
    }


def _handle_before_update(item, payload: IngredientSubcategoryUpdate, db: Session) -> None:
    """Apply updates with slug normalization and uniqueness check."""
    if payload.slug is not None:
        new_slug = payload.slug.lower().strip()
        if new_slug != item.slug:
            check_slug_unique(
                db, IngredientSubcategory, new_slug,
                exclude_id=item.id,
                detail=f"Subcategory slug '{new_slug}' already exists",
            )
            item.slug = new_slug

    # Apply remaining fields
    apply_payload_updates(
        item, payload, db,
        normalize_fields={"display_name": "strip"},
        skip_fields={"slug"},
    )


def _handle_before_delete(item, db: Session) -> None:
    """Check referential integrity before deletion."""
    ref_count = db.query(Ingredient).filter(
        Ingredient.subcategory_id == item.id
    ).count()
    if ref_count:
        raise ReferentialIntegrityError(
            f"Cannot delete subcategory '{item.slug}' — "
            f"{ref_count} ingredient(s) still reference it. "
            f"Reassign them first."
        )


# Create the CRUD router using the factory
_crud = CRUDRouterFactory(
    model=IngredientSubcategory,
    create_schema=IngredientSubcategoryCreate,
    update_schema=IngredientSubcategoryUpdate,
    response_schema=IngredientSubcategoryOut,
    prefix="/admin/ingredient-subcategories",
    tags=["Admin - Ingredient Subcategories"],
    id_param="subcategory_id",
    not_found_message="Ingredient subcategory not found",
    unique_fields=["slug"],
    order_by=["category_slug", "display_order", "slug"],
    on_before_create=_handle_before_create,
    on_before_update=_handle_before_update,
    on_before_delete=_handle_before_delete,
    list_response_schema=IngredientSubcategoryList,
    list_response_builder=make_list_builder(IngredientSubcategoryList, "subcategories"),
)

admin_ingredient_subcategories_router = _crud.router

# Replace factory's default list endpoint with custom filtered list
admin_ingredient_subcategories_router.routes.pop(0)


@admin_ingredient_subcategories_router.get("", response_model=IngredientSubcategoryList)
def list_subcategories(
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_credentials),
    category_slug: str | None = Query(None, description="Filter by parent category slug"),
) -> IngredientSubcategoryList:
    """List all ingredient subcategories, optionally filtered by category."""
    query = db.query(IngredientSubcategory)
    if category_slug:
        query = query.filter(IngredientSubcategory.category_slug == category_slug)
    query = query.order_by(
        IngredientSubcategory.category_slug,
        IngredientSubcategory.display_order,
        IngredientSubcategory.slug,
    )
    items = query.all()
    return IngredientSubcategoryList(
        subcategories=[IngredientSubcategoryOut.model_validate(i) for i in items],
        total=len(items),
    )
