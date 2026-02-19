"""
Unrecognized Suggestions Schemas for Orderbot
==============================================

Pydantic models for managing unrecognized suggestions:
- Menu items: items users request that aren't on the menu
- Options: attribute options users mention that don't exist (e.g., "venti")
- Ingredients: ingredient requests not on the menu (e.g., "honey")
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# =============================================================================
# Unrecognized Menu Item Suggestion Schemas
# =============================================================================

class UnrecognizedMenuItemSuggestionOut(BaseModel):
    """Response model for an unrecognized menu item suggestion."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    match_type: str
    suggested_item_type_id: int | None = None
    suggested_item_type_slug: str | None = None
    suggested_menu_item_names: list[str] | None = None
    hit_count: int
    is_active: bool
    created_at: datetime | None = None

    @classmethod
    def from_db(cls, db_obj) -> "UnrecognizedMenuItemSuggestionOut":
        """Create from database object with relationships."""
        item_type_slug = None
        if db_obj.suggested_item_type:
            item_type_slug = db_obj.suggested_item_type.slug

        menu_item_names = None
        if db_obj.suggested_menu_items:
            menu_item_names = [item.name for item in db_obj.suggested_menu_items]

        return cls(
            id=db_obj.id,
            input_pattern=db_obj.input_pattern,
            match_type=db_obj.match_type,
            suggested_item_type_id=db_obj.suggested_item_type_id,
            suggested_item_type_slug=item_type_slug,
            suggested_menu_item_names=menu_item_names,
            hit_count=db_obj.hit_count,
            is_active=db_obj.is_active,
            created_at=db_obj.created_at,
        )


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


class UnrecognizedMenuItemLogEntry(BaseModel):
    """Response model for an unrecognized menu item log entry."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_input: str
    normalized_input: str
    session_id: str | None = None
    order_item_count: int
    fallback_level: str  # "curated", "fuzzy", "llm", "generic"
    inferred_category: str | None = None
    created_at: datetime | None = None


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

class UnrecognizedOptionSuggestionOut(BaseModel):
    """Response model for an unrecognized attribute option suggestion."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    attribute_slug: str
    suggested_display_name: str
    is_active: bool
    created_at: datetime | None = None


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

class UnrecognizedIngredientSuggestionOut(BaseModel):
    """Response model for an unrecognized ingredient suggestion."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    match_type: str
    suggested_display_name: str
    modifier_category: str | None = None
    alternative_ingredient_names: list[str] | None = None
    hit_count: int
    is_active: bool
    created_at: datetime | None = None

    @classmethod
    def from_db(cls, db_obj) -> "UnrecognizedIngredientSuggestionOut":
        """Create from database object with relationships."""
        alt_names = None
        if db_obj.alternative_ingredients:
            alt_names = [ing.name for ing in db_obj.alternative_ingredients]

        return cls(
            id=db_obj.id,
            input_pattern=db_obj.input_pattern,
            match_type=db_obj.match_type,
            suggested_display_name=db_obj.suggested_display_name,
            modifier_category=db_obj.modifier_category,
            alternative_ingredient_names=alt_names,
            hit_count=db_obj.hit_count,
            is_active=db_obj.is_active,
            created_at=db_obj.created_at,
        )


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
