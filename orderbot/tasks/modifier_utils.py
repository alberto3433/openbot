"""
Modifier Utilities.

This module provides utilities for working with modifier data structures,
including the ModifierEntry dataclass for type-safe access and the standard
modifier format specification.

Standard Modifier Format:
    {
        "slug": str,           # Canonical identifier (required)
        "category": str,       # Category/attribute slug (required)
        "quantity": int,       # How many (default: 1)
        "price": float,        # Unit price (optional, default: 0.0)
        "display_name": str,   # Human-readable name (optional)
        "ingredient_category": str,  # Ingredient's category for unit lookup (optional)
    }
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ModifierEntry:
    """Type-safe wrapper for modifier dictionary entries.

    This dataclass provides structured access to modifier data that's stored
    as dictionaries in MenuItemTask.selections. Use from_dict() to create
    instances from raw dictionaries.

    Examples:
        >>> modifier = ModifierEntry.from_dict({"slug": "bacon", "category": "protein", "quantity": 2})
        >>> modifier.slug
        'bacon'
        >>> modifier.total_price
        0.0

        >>> modifier = ModifierEntry.from_dict({"slug": "vanilla", "quantity": 2, "price": 0.75})
        >>> modifier.total_price
        1.5
    """

    slug: str
    category: str
    quantity: int = 1
    price: float = 0.0
    display_name: str | None = None
    ingredient_category: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModifierEntry":
        """Create a ModifierEntry from a dictionary.

        Handles missing keys and None values gracefully, providing sensible
        defaults for optional fields.

        Args:
            data: Dictionary with modifier data

        Returns:
            ModifierEntry instance

        Examples:
            >>> ModifierEntry.from_dict({"slug": "bacon", "category": "protein"})
            ModifierEntry(slug='bacon', category='protein', quantity=1, price=0.0, ...)
        """
        return cls(
            slug=data.get("slug") or "",
            category=data.get("category") or "",
            quantity=data.get("quantity", 1) or 1,
            price=data.get("price", 0.0) or 0.0,
            display_name=data.get("display_name"),
            ingredient_category=data.get("ingredient_category"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert back to dictionary format for storage.

        Returns:
            Dictionary with modifier data, omitting None values for optional fields.
        """
        result: dict[str, Any] = {
            "slug": self.slug,
            "category": self.category,
            "quantity": self.quantity,
            "price": self.price,
        }
        if self.display_name is not None:
            result["display_name"] = self.display_name
        if self.ingredient_category is not None:
            result["ingredient_category"] = self.ingredient_category
        return result

    @property
    def total_price(self) -> float:
        """Calculate total price (unit_price * quantity)."""
        return self.price * self.quantity

    @property
    def is_valid(self) -> bool:
        """Check if this modifier has required fields (slug and category)."""
        return bool(self.slug and self.category)

    @property
    def is_declined(self) -> bool:
        """Check if this represents a declined selection (user said 'no')."""
        return self.slug == "_declined"


def extract_modifier_slug_and_quantity(modifier: dict[str, Any]) -> tuple[str, int]:
    """Extract slug and quantity from a modifier dict with defensive defaults.

    A common pattern throughout the codebase - extract the key fields from
    a modifier dictionary with sensible defaults for missing/None values.

    Args:
        modifier: Modifier dictionary

    Returns:
        Tuple of (slug, quantity) with defaults ("", 1) for missing values

    Examples:
        >>> extract_modifier_slug_and_quantity({"slug": "bacon", "quantity": 2})
        ('bacon', 2)
        >>> extract_modifier_slug_and_quantity({"slug": "egg"})
        ('egg', 1)
        >>> extract_modifier_slug_and_quantity({})
        ('', 1)
    """
    slug = modifier.get("slug") or ""
    quantity = modifier.get("quantity", 1) or 1
    return slug, quantity


def extract_modifier_price(modifier: dict[str, Any]) -> float | None:
    """Extract stored price from a modifier dict.

    Returns the stored price if it exists and is positive, None otherwise.
    This is useful for checking if a modifier already has a cached price
    or needs to be looked up from the database.

    Args:
        modifier: Modifier dictionary

    Returns:
        Price if stored and > 0, None otherwise

    Examples:
        >>> extract_modifier_price({"slug": "bacon", "price": 1.50})
        1.5
        >>> extract_modifier_price({"slug": "egg", "price": 0})
        None
        >>> extract_modifier_price({"slug": "salt"})
        None
    """
    price = modifier.get("price")
    if price and price > 0:
        return price
    return None
