"""
Modifier Utilities.

This module provides utilities for working with modifier data structures.

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

from typing import Any


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


