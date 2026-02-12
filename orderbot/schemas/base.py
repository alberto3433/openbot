"""
Base Schema Classes for Orderbot
====================================

This module provides reusable base classes for Pydantic schemas to reduce
duplication across the codebase. All response schemas should inherit from
these bases where applicable.

Base Classes:
-------------
- OrmModel: Base for any schema that reads from SQLAlchemy models
- TimestampedModel: OrmModel with id and created_at fields
- FullTimestampedModel: Adds updated_at to TimestampedModel
- ListResponse: Generic paginated list response

Usage:
------
    from orderbot.schemas.base import OrmModel, TimestampedModel, ListResponse

    class CategoryOut(TimestampedModel):
        name: str
        slug: str
        # id and created_at inherited

    class CategoryList(ListResponse[CategoryOut]):
        pass  # Automatically has items: list[CategoryOut] and total: int
"""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


# Type variable for generic list responses
T = TypeVar("T")


class OrmModel(BaseModel):
    """
    Base class for schemas that read from SQLAlchemy ORM models.

    Configures Pydantic to accept SQLAlchemy model instances directly
    via model_validate(), enabling patterns like:

        item = db.query(MenuItem).first()
        return MenuItemOut.model_validate(item)

    All *Out response schemas should inherit from this or its subclasses.
    """

    model_config = ConfigDict(from_attributes=True)


class TimestampedModel(OrmModel):
    """
    Base class for response schemas with id and created_at.

    Most database entities have these fields. Inherit from this to
    avoid repeating them in every schema.

    Fields:
        id: Database primary key
        created_at: When the record was created
    """

    id: int
    created_at: datetime | None = None


class FullTimestampedModel(TimestampedModel):
    """
    Base class for response schemas with id, created_at, and updated_at.

    Use for entities that track modification time.

    Fields:
        id: Database primary key
        created_at: When the record was created
        updated_at: When the record was last modified
    """

    updated_at: datetime | None = None


class ListResponse(BaseModel, Generic[T]):
    """
    Generic paginated list response.

    Use as a base for list endpoints to ensure consistent response format
    across the API.

    Type Parameters:
        T: The item type in the list (e.g., CategoryOut)

    Fields:
        items: List of items
        total: Total count of items (may differ from len(items) if paginated)

    Usage:
        class CategoryList(ListResponse[CategoryOut]):
            pass

        # Or inline for simple cases:
        def get_categories() -> ListResponse[CategoryOut]:
            return ListResponse(items=categories, total=len(categories))
    """

    items: list[T] = Field(default_factory=list)
    total: int = 0


class PaginatedListResponse(BaseModel, Generic[T]):
    """
    Generic paginated list response with page navigation metadata.

    Extends the basic list pattern with page, page_size, and has_next
    for endpoints that support cursor-based pagination.

    Type Parameters:
        T: The item type in the list (e.g., OrderSummaryOut)

    Fields:
        items: List of items for the current page
        page: Current page number (1-indexed)
        page_size: Number of items per page
        total: Total count of matching items
        has_next: Whether there are more pages after this one
    """

    items: list[T] = Field(default_factory=list)
    page: int
    page_size: int
    total: int
    has_next: bool


class AvailabilityUpdate(BaseModel):
    """
    Base class for availability toggle requests.

    Used by the "86" system for quickly marking items as unavailable.
    Supports both global and store-specific availability.

    Fields:
        is_available: New availability state (True = available, False = 86'd)
        store_id: If provided, updates store-specific availability only
    """

    is_available: bool
    store_id: str | None = None
