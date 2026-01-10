"""
Modifier Qualifier Schemas for Sandwich Bot
============================================

This module defines Pydantic models for modifier qualifiers. Qualifiers are
patterns like "extra", "light", "on the side" that modify how a customer
wants their food prepared.

Endpoint Coverage:
------------------
- GET /admin/modifier-qualifiers: List all qualifiers
- POST /admin/modifier-qualifiers: Create a new qualifier
- PUT /admin/modifier-qualifiers/{id}: Update a qualifier
- DELETE /admin/modifier-qualifiers/{id}: Delete a qualifier

Categories:
-----------
Qualifiers are organized into categories for conflict detection:
- **amount**: Quantity modifiers (extra, light, double) - these can conflict
- **position**: Location modifiers (on the side) - no conflict with amount
- **preparation**: How to prepare (crispy, well done) - no conflict with amount

Pattern Matching:
-----------------
Patterns are matched as whole words, case-insensitive. For example:
- "extra" matches "extra mayo" but not "extraordinary"
- "a little bit of" matches "a little bit of mayo"

Example Usage:
--------------
    # User says: "extra crispy bacon on the side"
    # Detected qualifiers: "extra" (amount), "crispy" (preparation), "on the side" (position)
    # Result: "Bacon (extra, crispy, on the side)"

Conflict Handling:
------------------
When qualifiers from the same category conflict (e.g., "light extra mayo"),
the system asks the user for clarification rather than guessing.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# Valid category values
QualifierCategory = Literal["amount", "position", "preparation"]


class ModifierQualifierBase(BaseModel):
    """Base fields for modifier qualifiers."""

    pattern: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="The pattern to match (e.g., 'extra', 'a little bit of')"
    )
    normalized_form: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The display form (e.g., 'extra', 'light')"
    )
    category: QualifierCategory = Field(
        default="amount",
        description="Category for conflict detection: amount, position, preparation"
    )
    is_active: bool = Field(
        default=True,
        description="Whether this qualifier is active"
    )


class ModifierQualifierCreate(ModifierQualifierBase):
    """Request model for creating a new modifier qualifier."""
    pass


class ModifierQualifierUpdate(BaseModel):
    """
    Request model for updating a modifier qualifier.

    All fields are optional - only provided fields will be updated.
    """
    pattern: Optional[str] = Field(
        None,
        min_length=1,
        max_length=100,
        description="The pattern to match"
    )
    normalized_form: Optional[str] = Field(
        None,
        min_length=1,
        max_length=50,
        description="The display form"
    )
    category: Optional[QualifierCategory] = Field(
        None,
        description="Category for conflict detection"
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether this qualifier is active"
    )


class ModifierQualifierOut(ModifierQualifierBase):
    """Response model for a modifier qualifier."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ModifierQualifierList(BaseModel):
    """Response model for listing modifier qualifiers."""

    qualifiers: list[ModifierQualifierOut]
    total: int
