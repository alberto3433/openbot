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
        suggested_category_slug: Category to suggest (e.g., "pastry", "side")
        suggested_menu_items: List of specific menu items to suggest
        hit_count: How many times this suggestion has been used
        is_active: Whether this suggestion is enabled
        created_at: When the suggestion was created
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    input_pattern: str
    match_type: str
    suggested_category_slug: Optional[str] = None
    suggested_menu_items: Optional[List[str]] = None
    hit_count: int
    is_active: bool
    created_at: Optional[datetime] = None


class UnrecognizedSuggestionCreate(BaseModel):
    """
    Request model for creating an unrecognized item suggestion.

    Attributes:
        input_pattern: The pattern to match (required)
        match_type: How to match (default: "exact")
        suggested_category_slug: Category to suggest
        suggested_menu_items: List of specific menu items to suggest
        is_active: Whether this suggestion is enabled (default: True)

    Example:
        {
            "input_pattern": "croissant",
            "match_type": "exact",
            "suggested_menu_items": ["Rugelach", "Babka"]
        }
    """
    input_pattern: str
    match_type: str = "exact"
    suggested_category_slug: Optional[str] = None
    suggested_menu_items: Optional[List[str]] = None
    is_active: bool = True


class UnrecognizedSuggestionUpdate(BaseModel):
    """
    Request model for updating an unrecognized item suggestion.

    All fields optional - only provided fields are updated.
    """
    input_pattern: Optional[str] = None
    match_type: Optional[str] = None
    suggested_category_slug: Optional[str] = None
    suggested_menu_items: Optional[List[str]] = None
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
