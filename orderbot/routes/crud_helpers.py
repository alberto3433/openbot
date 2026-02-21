"""
CRUD Route Helpers for Orderbot Admin API
==========================================

This module provides helper functions to reduce boilerplate in admin CRUD routes
that use the CRUDRouterFactory.

Helpers:
--------
- get_or_404: Fetch a record by ID or raise ResourceNotFoundError
- check_slug_unique: Check slug uniqueness with optional scoping
- make_list_builder: Creates list response wrapper functions
- apply_payload_updates: Applies non-None payload fields to model with normalization
- build_create_kwargs: Build model kwargs from a create payload with normalization
"""

from typing import Any, Callable, TypeVar

from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..cache.base import normalize_text
from ..exceptions import ResourceNotFoundError, ValidationError


def get_or_404(
    db: Session,
    model: type,
    id_value: int | str,
    *,
    id_column: str = "id",
    detail: str | None = None,
):
    """
    Fetch a record by ID or raise ResourceNotFoundError (mapped to HTTP 404).

    Replaces the common pattern:
        item = db.query(Model).filter(Model.id == item_id).first()
        if not item:
            raise ResourceNotFoundError("... not found")

    Args:
        db: Database session
        model: SQLAlchemy model class
        id_value: The ID value to look up
        id_column: Column name to filter on (default: "id")
        detail: Custom error message. If None, auto-generates from model name.

    Returns:
        The found record

    Raises:
        ResourceNotFoundError: If record not found
    """
    column = getattr(model, id_column)
    item = db.query(model).filter(column == id_value).first()
    if not item:
        name = model.__name__.replace("_", " ")
        raise ResourceNotFoundError(detail or f"{name} not found")
    return item


def check_slug_unique(
    db: Session,
    model: type,
    slug: str,
    *,
    exclude_id: int | None = None,
    scope_filters: dict[str, Any] | None = None,
    detail: str | None = None,
) -> None:
    """
    Check slug uniqueness, raising ValidationError if duplicate found.

    Replaces the common pattern:
        existing = db.query(Model).filter(Model.slug == slug).first()
        if existing:
            raise ValidationError("Slug already exists")

    Args:
        db: Database session
        model: SQLAlchemy model class
        slug: The slug value to check
        exclude_id: ID to exclude from check (for updates)
        scope_filters: Additional column=value filters for scoped uniqueness
            e.g. {"global_attribute_id": 5} for attribute-scoped slugs
        detail: Custom error message. If None, auto-generates from model name.

    Raises:
        ValidationError: If a duplicate slug is found
    """
    query = db.query(model).filter(model.slug == slug)
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    if scope_filters:
        for col_name, value in scope_filters.items():
            query = query.filter(getattr(model, col_name) == value)
    if query.first():
        name = model.__name__.replace("_", " ")
        raise ValidationError(detail or f"{name} with slug '{slug}' already exists")


ListSchemaType = TypeVar("ListSchemaType", bound=BaseModel)


def make_list_builder(
    list_schema: type[ListSchemaType],
    items_field: str,
) -> Callable[[list, int], ListSchemaType]:
    """
    Create a list response builder function for CRUDRouterFactory.

    This eliminates the need to write boilerplate functions like:
        def _build_list_response(items, total):
            return CategoryList(categories=items, total=total)

    Usage:
        _crud = CRUDRouterFactory(
            ...
            list_response_builder=make_list_builder(CategoryList, "categories"),
        )

    Args:
        list_schema: The Pydantic schema for the list response (e.g., CategoryList)
        items_field: The field name in the schema for the items list (e.g., "categories")

    Returns:
        A function that takes (items, total) and returns the list response schema
    """
    def builder(items: list, total: int) -> ListSchemaType:
        return list_schema(**{items_field: items, "total": total})
    return builder


def apply_payload_updates(
    item: Any,
    payload: BaseModel,
    db: Session,
    *,
    normalize_fields: dict[str, str] | None = None,
    skip_fields: set[str] | None = None,
) -> None:
    """
    Apply non-None fields from payload to model item.

    This eliminates repetitive update handler code like:
        if payload.slug is not None:
            item.slug = payload.slug.lower().strip()
        if payload.name is not None:
            item.name = payload.name.strip()

    Usage:
        def _handle_before_update(item, payload, db):
            apply_payload_updates(
                item, payload, db,
                normalize_fields={"slug": "lower_strip", "name": "strip"},
            )

    Args:
        item: The SQLAlchemy model instance to update
        payload: The Pydantic update schema with new values
        db: Database session (passed for consistency, may be needed by extensions)
        normalize_fields: Dict mapping field names to normalization type:
            - "strip": Call .strip() on string values
            - "lower": Call .lower() on string values
            - "lower_strip": Call .lower().strip() on string values
        skip_fields: Set of field names to skip (handled manually)
    """
    normalize_fields = normalize_fields or {}
    skip_fields = skip_fields or set()

    # Get fields that were explicitly set in the payload
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name in skip_fields:
            continue

        if value is None:
            # Explicit None - may mean "clear this field"
            if hasattr(item, field_name):
                setattr(item, field_name, value)
            continue

        # Apply normalization if specified
        if field_name in normalize_fields and isinstance(value, str):
            norm_type = normalize_fields[field_name]
            if norm_type == "strip":
                value = value.strip()
            elif norm_type == "lower":
                value = value.lower()
            elif norm_type == "lower_strip":
                value = normalize_text(value)

        if hasattr(item, field_name):
            setattr(item, field_name, value)


def build_create_kwargs(
    payload: BaseModel,
    *,
    normalize_fields: dict[str, str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build model kwargs from a create payload with field normalization.

    This eliminates repetitive create handler code like:
        return {
            "slug": payload.slug.lower().strip(),
            "name": payload.name.strip(),
            "description": payload.description,
        }

    Usage:
        def _build_create_kwargs(payload, db):
            return build_create_kwargs(
                payload,
                normalize_fields={"slug": "lower_strip", "name": "strip"},
            )

    Args:
        payload: The Pydantic create schema
        normalize_fields: Dict mapping field names to normalization type
        extra_fields: Additional fields to add to the result

    Returns:
        Dict of field names to values, suitable for Model(**kwargs)
    """
    normalize_fields = normalize_fields or {}
    result = {}

    for field_name, value in payload.model_dump().items():
        if value is not None and field_name in normalize_fields and isinstance(value, str):
            norm_type = normalize_fields[field_name]
            if norm_type == "strip":
                value = value.strip()
            elif norm_type == "lower":
                value = value.lower()
            elif norm_type == "lower_strip":
                value = normalize_text(value)
        result[field_name] = value

    if extra_fields:
        result.update(extra_fields)

    return result
