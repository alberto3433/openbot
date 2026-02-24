"""
Public Menu Response Schemas
============================

Pydantic models for the customer-facing menu endpoint.
These provide a read-only, hierarchical view of the menu
organized by overall category and display group.
"""

from __future__ import annotations

from pydantic import Field

from .base import OrmModel


class PublicSizePriceOut(OrmModel):
    """A single size+price entry for a menu item."""

    size_name: str
    price: float
    display_order: int = 0


class PublicMenuItemOut(OrmModel):
    """A menu item as shown on the public menu page."""

    id: int
    name: str
    description: str | None = None
    is_signature: bool = False
    size_prices: list[PublicSizePriceOut] = Field(default_factory=list)
    is_available: bool = True

    # Dietary flags
    is_vegan: bool | None = None
    is_vegetarian: bool | None = None
    is_gluten_free: bool | None = None
    is_dairy_free: bool | None = None
    is_kosher: bool | None = None

    # Allergen flags
    contains_eggs: bool | None = None
    contains_fish: bool | None = None
    contains_sesame: bool | None = None
    contains_nuts: bool | None = None


class PublicDisplayGroupOut(OrmModel):
    """A display group (e.g. 'Sandwiches', 'Drinks') with its items."""

    slug: str
    display_name: str
    display_order: int = 0
    items: list[PublicMenuItemOut] = Field(default_factory=list)


class PublicOverallCategoryOut(OrmModel):
    """A top-level category (e.g. 'Food', 'Beverage') with its display groups."""

    slug: str
    display_name: str
    display_groups: list[PublicDisplayGroupOut] = Field(default_factory=list)


class PublicMenuResponse(OrmModel):
    """Full public menu response."""

    categories: list[PublicOverallCategoryOut] = Field(default_factory=list)
    store_id: str | None = None
    store_name: str | None = None
