"""
Unrecognized Suggestions Schemas for Orderbot
==============================================

Pydantic models for managing unrecognized suggestions:
- Menu items: items users request that aren't on the menu
- Options: attribute options users mention that don't exist (e.g., "venti")
- Ingredients: ingredient requests not on the menu (e.g., "honey")
"""

from typing import Any

from pydantic import BaseModel

from .base import TimestampedModel


# =============================================================================
# Unrecognized Menu Item Suggestion Schemas
# =============================================================================

class UnrecognizedMenuItemSuggestionOut(TimestampedModel):
    """Response model for an unrecognized menu item suggestion."""
    input_pattern: str
    match_type: str
    suggested_item_type_id: int | None = None
    suggested_item_type_slug: str | None = None
    suggested_menu_item_names: list[str] | None = None
    hit_count: int
    is_active: bool



class UnrecognizedMenuItemSuggestionCreate(BaseModel):
    """Request model for creating an unrecognized menu item suggestion."""
    input_pattern: str
    match_type: str = "exact"
    suggested_item_type_slug: str | None = None
    suggested_menu_item_names: list[str] | None = None
    is_active: bool = True


class UnrecognizedMenuItemSuggestionUpdate(BaseModel):
    """Request model for updating an unrecognized menu item suggestion."""
    input_pattern: str | None = None
    match_type: str | None = None
    suggested_item_type_slug: str | None = None
    suggested_menu_item_names: list[str] | None = None
    is_active: bool | None = None


class UnrecognizedMenuItemSuggestionStats(BaseModel):
    """Statistics for unrecognized menu item suggestions."""
    total_suggestions: int
    active_suggestions: int
    total_hits: int
    by_match_type: dict[str, int]
    by_category: dict[str, int]
    top_hits: list[dict[str, Any]]


class UnrecognizedMenuItemLogEntry(TimestampedModel):
    """Response model for an unrecognized menu item log entry."""
    user_input: str
    normalized_input: str
    session_id: str | None = None
    order_item_count: int
    fallback_level: str  # "curated", "fuzzy", "llm", "generic"
    inferred_category: str | None = None


class UnrecognizedMenuItemLogStats(BaseModel):
    """Aggregated statistics for unrecognized menu item logs."""
    total_requests: int
    by_fallback_level: dict[str, int]
    by_inferred_category: dict[str, int]
    top_unrecognized: list[dict[str, Any]]
    recent_entries: list[UnrecognizedMenuItemLogEntry]


# =============================================================================
# Unrecognized Option Suggestion Schemas
# =============================================================================

class UnrecognizedOptionSuggestionOut(TimestampedModel):
    """Response model for an unrecognized attribute option suggestion."""
    input_pattern: str
    attribute_slug: str
    suggested_display_name: str
    is_active: bool


class UnrecognizedOptionSuggestionCreate(BaseModel):
    """Request model for creating an unrecognized option suggestion."""
    input_pattern: str
    attribute_slug: str
    suggested_display_name: str
    is_active: bool = True


class UnrecognizedOptionSuggestionUpdate(BaseModel):
    """Request model for updating an unrecognized option suggestion."""
    input_pattern: str | None = None
    attribute_slug: str | None = None
    suggested_display_name: str | None = None
    is_active: bool | None = None


class UnrecognizedOptionSuggestionStats(BaseModel):
    """Statistics for unrecognized option suggestions."""
    total_suggestions: int
    active_suggestions: int
    by_attribute: dict[str, int]


# =============================================================================
# Unrecognized Ingredient Suggestion Schemas
# =============================================================================

class UnrecognizedIngredientSuggestionOut(TimestampedModel):
    """Response model for an unrecognized ingredient suggestion."""
    input_pattern: str
    match_type: str
    suggested_display_name: str
    modifier_category: str | None = None
    alternative_ingredient_names: list[str] | None = None
    hit_count: int
    is_active: bool



class UnrecognizedIngredientSuggestionCreate(BaseModel):
    """Request model for creating an unrecognized ingredient suggestion."""
    input_pattern: str
    match_type: str = "exact"
    suggested_display_name: str
    modifier_category: str | None = None
    alternative_ingredient_names: list[str] | None = None
    is_active: bool = True


class UnrecognizedIngredientSuggestionUpdate(BaseModel):
    """Request model for updating an unrecognized ingredient suggestion."""
    input_pattern: str | None = None
    match_type: str | None = None
    suggested_display_name: str | None = None
    modifier_category: str | None = None
    alternative_ingredient_names: list[str] | None = None
    is_active: bool | None = None
