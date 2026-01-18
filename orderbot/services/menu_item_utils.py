"""
Menu Item Utilities.

This module provides utility functions for working with menu items,
including looking up default ingredients/attributes for signature items.
"""

import json
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal

logger = logging.getLogger(__name__)


def get_menu_item_default_ingredients(menu_item_id: int, db: Optional[Session] = None) -> list[dict]:
    """
    Get the default ingredients/attributes for a menu item.

    This looks up the default_config in the menu item's extra_metadata JSON field
    and returns the ingredient names as a list of dicts.

    Args:
        menu_item_id: The ID of the menu item
        db: Optional database session. If not provided, creates a new one.

    Returns:
        List of dicts with keys:
        - name: Display name of the ingredient (e.g., "Applewood Smoked Bacon")
        - attribute_slug: The attribute slug (e.g., "protein", "cheese", "toppings")
        - attribute_name: The attribute display name
        - price: Always 0.0 (defaults are included in base price)
        - is_default: Always True for these (they're menu item defaults)
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        result = db.execute(
            text("SELECT extra_metadata FROM menu_items WHERE id = :menu_item_id"),
            {"menu_item_id": menu_item_id}
        )
        row = result.fetchone()

        if not row or not row.extra_metadata:
            return []

        try:
            meta = json.loads(row.extra_metadata)
        except (json.JSONDecodeError, TypeError):
            return []

        default_config = meta.get("default_config", {})
        if not default_config:
            return []

        ingredients = []
        # Attribute slug mapping to display names
        attr_display_names = {
            "bread": "Bread",
            "protein": "Protein",
            "cheese": "Cheese",
            "toppings": "Toppings",
            "spread": "Spread",
            "extras": "Extras",
            "sauce": "Sauce",
            "sauces": "Sauces",
        }

        for attr_slug, value in default_config.items():
            # Skip non-ingredient attributes
            if attr_slug in ("toasted", "scooped"):
                continue

            attr_name = attr_display_names.get(attr_slug, attr_slug.replace("_", " ").title())

            if isinstance(value, list):
                # Multi-value attributes like toppings
                for item in value:
                    ingredients.append({
                        "name": str(item),
                        "attribute_slug": attr_slug,
                        "attribute_name": attr_name,
                        "price": 0.0,
                        "is_default": True,
                    })
            elif isinstance(value, str) and value:
                # Single-value attributes like bread, protein
                ingredients.append({
                    "name": value,
                    "attribute_slug": attr_slug,
                    "attribute_name": attr_name,
                    "price": 0.0,
                    "is_default": True,
                })

        logger.debug(
            "Found %d default ingredients for menu_item_id=%d: %s",
            len(ingredients),
            menu_item_id,
            [i["name"] for i in ingredients]
        )

        return ingredients

    finally:
        if close_db:
            db.close()


def find_default_ingredient_match(
    menu_item_id: int,
    user_input: str,
    db: Optional[Session] = None,
) -> Optional[dict]:
    """
    Find if user input matches any default ingredient of a menu item.

    Args:
        menu_item_id: The ID of the menu item
        user_input: What the user said (e.g., "bacon", "the bacon", "cheese")
        db: Optional database session

    Returns:
        Matching ingredient dict if found, None otherwise
    """
    # Normalize input
    normalized = user_input.lower().strip()
    if normalized.startswith("the "):
        normalized = normalized[4:]

    ingredients = get_menu_item_default_ingredients(menu_item_id, db)

    for ingredient in ingredients:
        name_lower = ingredient['name'].lower()

        # Direct match
        if normalized == name_lower:
            return ingredient

        # Partial match (e.g., "bacon" matches "Applewood Smoked Bacon")
        if normalized in name_lower or name_lower in normalized:
            return ingredient

        # Check for common aliases
        aliases = _get_ingredient_aliases(ingredient['name'])
        for alias in aliases:
            if normalized == alias or alias in normalized:
                return ingredient

    return None


def _get_ingredient_aliases(ingredient_name: str) -> list[str]:
    """Get aliases for an ingredient name from the database.

    Looks up the ingredient in the menu cache and returns all aliases
    that map to this ingredient's canonical name.

    Args:
        ingredient_name: The canonical ingredient name (e.g., "American Cheese")

    Returns:
        List of lowercase aliases (e.g., ["american", "american cheese"])
    """
    from orderbot.menu_data_cache import menu_cache

    try:
        # Get all aliases (alias -> canonical_name mapping)
        all_aliases = menu_cache.get_ingredient_aliases()

        # Find all aliases that map to this ingredient name
        name_lower = ingredient_name.lower()
        aliases = []
        for alias, canonical in all_aliases.items():
            if canonical.lower() == name_lower:
                aliases.append(alias)

        return aliases
    except Exception:
        # If cache not loaded, return empty list (fail gracefully for this utility)
        return []


