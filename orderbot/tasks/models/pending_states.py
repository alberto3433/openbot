"""
Typed models for pending state fields on OrderTask.

Replaces untyped dict | None fields with Pydantic models for type safety.
"""

from typing import Any

from pydantic import BaseModel


class PendingSwitchItem(BaseModel):
    """State for item switch confirmation (e.g., 'can you make it iced?' -> similar item found)."""
    id: int
    name: str
    base_price: float
    item_type: str


class PendingAttrDisambiguation(BaseModel):
    """State for attribute option disambiguation (e.g., 'walnut' matches multiple options)."""
    options: list[dict]
    attr_slug: str
    modifiers: dict[str, Any]
    item_id: str


class PendingChangeClarification(BaseModel):
    """State for modifier change clarification (e.g., 'change to blueberry' -> bagel or spread?)."""
    new_value: str
    possible_attributes: list[str]
    item_id: str | None
    target: str | None


class PendingUnmatchedPagination(BaseModel):
    """State for unmatched token pagination (e.g., 'honey' for coffee -> show options)."""
    unmatched_text: str
    attr_slug: str
    available_options: list[dict]
    page: int
    item_id: str


class PendingIngredientSuggestion(BaseModel):
    """State for ingredient suggestion (e.g., 'I want caramel syrup' -> suggest items)."""
    ingredient: str
    suggested_items: list[str]


class PendingDuplicateSelection(BaseModel):
    """State for duplicate item selection (e.g., 'another one' with multiple items)."""
    count: int
    items: list[dict]


class PendingSameThingClarification(BaseModel):
    """State for 'same thing' disambiguation (previous order vs cart items)."""
    has_previous_order: bool
    cart_items: list[dict]


class PendingIngredientSearch(BaseModel):
    """State for ingredient search pagination (e.g., 'chicken' -> show matching items)."""
    ingredient: str
    matches: list[dict]
    offset: int


class PendingDietaryFollowup(BaseModel):
    """State for dietary follow-up (e.g., 'is X vegan?' -> offer vegan options)."""
    dietary_type: str
    category: str | None


class PendingOrderHistory(BaseModel):
    """State for order history selection (e.g., 'what did I order before?')."""
    orders: list[dict]
