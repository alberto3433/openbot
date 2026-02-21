"""
Admin Overall Categories Routes for Orderbot
=============================================

CRUD endpoints for overall categories (e.g., "Food", "Beverage").
These group menu display groups by modifier extraction rules.

Endpoints:
----------
- GET /admin/overall-categories: List all overall categories
- POST /admin/overall-categories: Create a new overall category
- GET /admin/overall-categories/{id}: Get a specific overall category
- PUT /admin/overall-categories/{id}: Update an overall category
- DELETE /admin/overall-categories/{id}: Delete an overall category
"""

from sqlalchemy.orm import Session

from ..cache.base import normalize_text
from ..db.models import OverallCategory, MenuDisplayGroup
from ..schemas.modifiers import (
    OverallCategoryAdminOut,
    OverallCategoryAdminCreate,
    OverallCategoryAdminUpdate,
    OverallCategoryAdminList,
)
from .crud_factory import CRUDRouterFactory
from .crud_helpers import make_list_builder


def _to_response(item: OverallCategory, db: Session) -> OverallCategoryAdminOut:
    """Map OverallCategory model to admin response (display_name -> name, add count)."""
    count = db.query(MenuDisplayGroup).filter(
        MenuDisplayGroup.overall_category_id == item.id
    ).count()
    return OverallCategoryAdminOut(
        id=item.id,
        name=item.display_name,
        slug=item.slug,
        description=None,
        menu_item_count=count,
    )


def _build_create_kwargs(payload: OverallCategoryAdminCreate, db: Session) -> dict:
    """Map frontend 'name' field to model 'display_name'."""
    return {
        "display_name": payload.name,
        "slug": normalize_text(payload.slug),
    }


def _handle_before_update(item: OverallCategory, payload: OverallCategoryAdminUpdate, db: Session) -> None:
    """Map frontend 'name' field to model 'display_name' on update."""
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        item.display_name = data["name"]
    if "slug" in data and data["slug"] is not None:
        item.slug = normalize_text(data["slug"])


_crud = CRUDRouterFactory(
    model=OverallCategory,
    create_schema=OverallCategoryAdminCreate,
    update_schema=OverallCategoryAdminUpdate,
    response_schema=OverallCategoryAdminOut,
    prefix="/admin/overall-categories",
    tags=["Admin - Overall Categories"],
    not_found_message="Overall category not found",
    unique_fields=["slug"],
    order_by=["display_name"],
    to_response=_to_response,
    on_before_create=_build_create_kwargs,
    on_before_update=_handle_before_update,
    list_response_schema=OverallCategoryAdminList,
    list_response_builder=make_list_builder(OverallCategoryAdminList, "categories"),
)

admin_overall_categories_router = _crud.router
