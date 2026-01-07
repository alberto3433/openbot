"""
Item Type Field Schemas for Sandwich Bot
=========================================

This module defines Pydantic models for the item type field configuration system.
Item type fields define the configurable aspects of each item type (e.g., bagel_type,
toasted, spread for bagels; size, iced, milk for beverages).

These schemas are used by:
- Admin API endpoints for managing field configurations
- State machine for determining which questions to ask
- Menu cache for loading field definitions

Endpoints:
----------
- GET /admin/item-type-fields: List all fields (optionally filtered by item_type)
- GET /admin/item-type-fields/{id}: Get a specific field
- POST /admin/item-type-fields: Create a new field
- PUT /admin/item-type-fields/{id}: Update a field
- DELETE /admin/item-type-fields/{id}: Delete a field

Field Properties:
-----------------
- field_name: Identifier for the field (e.g., "bagel_type", "toasted")
- display_order: Order in which questions are asked
- required: Whether the field must have a value for item to be complete
- ask: Whether to prompt user for this field (vs. using defaults)
- question_text: The question to ask when prompting for this field
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ItemTypeFieldOut(BaseModel):
    """
    Response model for an item type field.

    Attributes:
        id: Database primary key
        item_type_id: Foreign key to item_types table
        item_type_slug: The slug of the parent item type
        field_name: Field identifier (e.g., "toasted", "size")
        display_order: Sort order for questions
        required: Whether field must have a value
        ask: Whether to prompt user for this field
        question_text: Question to ask for this field
        created_at: When the field was created
        updated_at: When the field was last updated
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_type_id: int
    item_type_slug: Optional[str] = None
    field_name: str
    display_order: int
    required: bool
    ask: bool
    question_text: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ItemTypeFieldCreate(BaseModel):
    """
    Request model for creating an item type field.

    Attributes:
        item_type_id: ID of the parent item type (required)
        field_name: Field identifier (required)
        display_order: Sort order (default: 0)
        required: Whether field must have a value (default: False)
        ask: Whether to prompt user (default: True)
        question_text: Question to ask

    Example:
        {
            "item_type_id": 1,
            "field_name": "bagel_type",
            "display_order": 1,
            "required": true,
            "ask": true,
            "question_text": "What kind of bagel would you like?"
        }
    """
    item_type_id: int
    field_name: str
    display_order: int = 0
    required: bool = False
    ask: bool = True
    question_text: Optional[str] = None


class ItemTypeFieldUpdate(BaseModel):
    """
    Request model for updating an item type field.

    All fields optional - only provided fields are updated.

    Attributes:
        field_name: New field identifier
        display_order: New sort order
        required: Update required status
        ask: Update ask status
        question_text: New question text
    """
    field_name: Optional[str] = None
    display_order: Optional[int] = None
    required: Optional[bool] = None
    ask: Optional[bool] = None
    question_text: Optional[str] = None
