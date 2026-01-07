"""
Response Pattern Schemas for Sandwich Bot
==========================================

This module defines Pydantic models for the response pattern system.
Response patterns define how to recognize user intent from their input
(affirmative responses like "yes", negative responses like "no", etc.).

These schemas are used by:
- Admin API endpoints for managing response patterns
- Menu cache for loading patterns
- State machine for recognizing user responses

Endpoints:
----------
- GET /admin/response-patterns: List all patterns (optionally filtered by type)
- GET /admin/response-patterns/{id}: Get a specific pattern
- POST /admin/response-patterns: Create a new pattern
- PUT /admin/response-patterns/{id}: Update a pattern
- DELETE /admin/response-patterns/{id}: Delete a pattern

Pattern Types:
--------------
- affirmative: Yes responses (yes, yeah, sure, ok, etc.)
- negative: No responses (no, nope, no thanks, etc.)
- cancel: Cancel responses (cancel, never mind, forget it, etc.)
- done: Done responses (that's all, nothing else, etc.)
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ResponsePatternOut(BaseModel):
    """
    Response model for a response pattern.

    Attributes:
        id: Database primary key
        pattern_type: Type of response (affirmative, negative, cancel, done)
        pattern: The pattern to match
        created_at: When the pattern was created
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    pattern_type: str
    pattern: str
    created_at: Optional[datetime] = None


class ResponsePatternCreate(BaseModel):
    """
    Request model for creating a response pattern.

    Attributes:
        pattern_type: Type of response (required)
        pattern: The pattern to match (required)

    Example:
        {
            "pattern_type": "affirmative",
            "pattern": "you bet"
        }
    """
    pattern_type: str
    pattern: str


class ResponsePatternUpdate(BaseModel):
    """
    Request model for updating a response pattern.

    All fields optional - only provided fields are updated.

    Attributes:
        pattern_type: New pattern type
        pattern: New pattern text
    """
    pattern_type: Optional[str] = None
    pattern: Optional[str] = None


class ResponsePatternTypeStats(BaseModel):
    """
    Statistics for a pattern type.

    Attributes:
        pattern_type: The type of response
        count: Number of patterns for this type
        patterns: List of patterns
    """
    pattern_type: str
    count: int
    patterns: list[str]
