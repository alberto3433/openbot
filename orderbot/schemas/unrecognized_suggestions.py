"""
Unrecognized Item Suggestions Schemas for Orderbot
===================================================

This module defines Pydantic models for managing unrecognized item suggestions.
These are curated responses for items users commonly request that aren't on the menu.

Tables:
-------
- unrecognized_item_suggestions: Curated responses for known unrecognized items
- unrecognized_item_log: Analytics for tracking unrecognized item requests

Match Types:
------------
- exact: Input must exactly match the pattern
- prefix: Input must start with the pattern
- contains: Input must contain the pattern

Example Suggestions:
--------------------
- "croissant" -> suggest pastry category
- "home fries" -> suggest side category
- "expresso" (misspelling) -> suggest espresso category
"""

from datetime import datetime
from typing import Optional, List, Any

from pydantic import BaseModel, ConfigDict


class UnrecognizedSuggestionOut(BaseModel):
    """
    Response model for an unrecognized item suggestion.

    Attributes:
        id: Database primary key
        input_pattern: The pattern to match against user input
        match_type: How to match (exact, prefix, contains)
        suggested_item_type_id: FK to item_types table
        suggested_item_type_slug: Item type slug (derived from relationship)
        suggested_menu_item_names: List of menu item names (derived from relationship)
        hit_count: How many times this suggestion has been used
        is_active: Whether this suggestion is enabled
        created_at: When the suggestion was created
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    match_type: str
    suggested_item_type_id: Optional[int] = None
    suggested_item_type_slug: Optional[str] = None
    suggested_menu_item_names: Optional[List[str]] = None
    hit_count: int
    is_active: bool
    created_at: Optional[datetime] = None

    @classmethod
    def from_db(cls, db_obj) -> "UnrecognizedSuggestionOut":
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


class UnrecognizedSuggestionCreate(BaseModel):
    """
    Request model for creating an unrecognized item suggestion.

    Attributes:
        input_pattern: The pattern to match (required)
        match_type: How to match (default: "exact")
        suggested_item_type_slug: Item type slug to suggest (looked up to get FK)
        suggested_menu_item_names: List of menu item names to suggest (looked up to get FKs)
        is_active: Whether this suggestion is enabled (default: True)

    Example:
        {
            "input_pattern": "croissant",
            "match_type": "exact",
            "suggested_menu_item_names": ["Rugelach", "Babka"]
        }
    """
    input_pattern: str
    match_type: str = "exact"
    suggested_item_type_slug: Optional[str] = None
    suggested_menu_item_names: Optional[List[str]] = None
    is_active: bool = True


class UnrecognizedSuggestionUpdate(BaseModel):
    """
    Request model for updating an unrecognized item suggestion.

    All fields optional - only provided fields are updated.
    """
    input_pattern: Optional[str] = None
    match_type: Optional[str] = None
    suggested_item_type_slug: Optional[str] = None
    suggested_menu_item_names: Optional[List[str]] = None
    is_active: Optional[bool] = None


class UnrecognizedSuggestionStats(BaseModel):
    """
    Statistics for unrecognized item suggestions.
    """
    total_suggestions: int
    active_suggestions: int
    total_hits: int
    by_match_type: dict[str, int]
    by_category: dict[str, int]
    top_hits: List[dict[str, Any]]


class UnrecognizedLogEntry(BaseModel):
    """
    Response model for an unrecognized item log entry.

    These are analytics records showing what items users requested
    that weren't found on the menu.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_input: str
    normalized_input: str
    session_id: Optional[str] = None
    order_item_count: int
    fallback_level: str  # "curated", "fuzzy", "llm", "generic"
    inferred_category: Optional[str] = None
    created_at: Optional[datetime] = None


class UnrecognizedLogStats(BaseModel):
    """
    Aggregated statistics for unrecognized item logs.
    """
    total_requests: int
    by_fallback_level: dict[str, int]
    by_inferred_category: dict[str, int]
    top_unrecognized: List[dict[str, Any]]
    recent_entries: List[UnrecognizedLogEntry]


# =============================================================================
# Unrecognized Option Suggestion Schemas
# =============================================================================

class UnrecognizedOptionSuggestionOut(BaseModel):
    """
    Response model for an unrecognized attribute option suggestion.

    Attributes:
        id: Database primary key
        input_pattern: The pattern to match against user input (e.g., "venti")
        attribute_slug: The attribute this suggestion is for (e.g., "size")
        suggested_display_name: Human-readable name (e.g., "Venti")
        is_active: Whether this suggestion is enabled
        created_at: When the suggestion was created
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    attribute_slug: str
    suggested_display_name: str
    is_active: bool
    created_at: Optional[datetime] = None


class UnrecognizedOptionSuggestionCreate(BaseModel):
    """
    Request model for creating an unrecognized option suggestion.

    Example:
        {
            "input_pattern": "venti",
            "attribute_slug": "size",
            "suggested_display_name": "Venti"
        }
    """
    input_pattern: str
    attribute_slug: str
    suggested_display_name: str
    is_active: bool = True


class UnrecognizedOptionSuggestionUpdate(BaseModel):
    """
    Request model for updating an unrecognized option suggestion.

    All fields optional - only provided fields are updated.
    """
    input_pattern: Optional[str] = None
    attribute_slug: Optional[str] = None
    suggested_display_name: Optional[str] = None
    is_active: Optional[bool] = None


class UnrecognizedOptionSuggestionStats(BaseModel):
    """
    Statistics for unrecognized option suggestions.
    """
    total_suggestions: int
    active_suggestions: int
    by_attribute: dict[str, int]
