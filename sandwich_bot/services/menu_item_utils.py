"""
Menu Item Utilities.

This module provides utility functions for working with menu items,
including looking up default ingredients/attributes for signature items.
"""

import logging
from functools import lru_cache
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal

logger = logging.getLogger(__name__)


def get_menu_item_default_ingredients(menu_item_id: int, db: Optional[Session] = None) -> list[dict]:
    """
    Get the default ingredients/attributes for a menu item.

    This looks up the pre-configured attributes in menu_item_attribute_selections
    and returns them as a list of dicts with ingredient info.

    Args:
        menu_item_id: The ID of the menu item
        db: Optional database session. If not provided, creates a new one.

    Returns:
        List of dicts with keys:
        - name: Display name of the ingredient (e.g., "Applewood Smoked Bacon")
        - attribute_slug: The attribute slug (e.g., "extra_protein", "cheese")
        - attribute_name: The attribute display name (e.g., "Extra Protein")
        - price: The price modifier for this ingredient
        - is_default: Always True for these (they're menu item defaults)
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        result = db.execute(text('''
            SELECT
                ao.display_name as name,
                ita.slug as attribute_slug,
                ita.display_name as attribute_name,
                ao.price_modifier as price
            FROM menu_item_attribute_selections mias
            JOIN attribute_options ao ON mias.option_id = ao.id
            JOIN item_type_attributes ita ON mias.attribute_id = ita.id
            WHERE mias.menu_item_id = :menu_item_id
            ORDER BY ita.display_order, ao.display_order
        '''), {'menu_item_id': menu_item_id})

        ingredients = []
        for row in result:
            ingredients.append({
                'name': row.name,
                'attribute_slug': row.attribute_slug,
                'attribute_name': row.attribute_name,
                'price': float(row.price) if row.price else 0.0,
                'is_default': True,
            })

        logger.debug(
            "Found %d default ingredients for menu_item_id=%d: %s",
            len(ingredients),
            menu_item_id,
            [i['name'] for i in ingredients]
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
    """Get common aliases for an ingredient name."""
    name_lower = ingredient_name.lower()
    aliases = []

    # Bacon aliases
    if 'bacon' in name_lower:
        aliases.extend(['bacon'])
    if 'applewood' in name_lower:
        aliases.extend(['applewood', 'applewood bacon'])

    # Cheese aliases
    if 'cheddar' in name_lower:
        aliases.extend(['cheddar', 'cheese'])
    if 'american' in name_lower:
        aliases.extend(['american', 'american cheese', 'cheese'])
    if 'swiss' in name_lower:
        aliases.extend(['swiss', 'swiss cheese', 'cheese'])
    if 'muenster' in name_lower:
        aliases.extend(['muenster', 'cheese'])

    # Protein aliases
    if 'ham' in name_lower:
        aliases.extend(['ham'])
    if 'turkey' in name_lower:
        aliases.extend(['turkey'])
    if 'sausage' in name_lower:
        aliases.extend(['sausage'])
    if 'egg' in name_lower and 'salad' not in name_lower:
        aliases.extend(['egg', 'eggs'])

    # Salmon/fish aliases
    if 'salmon' in name_lower or 'nova' in name_lower or 'lox' in name_lower:
        aliases.extend(['salmon', 'nova', 'lox', 'nova scotia salmon'])

    return aliases


# Cache menu item default ingredients for performance
_default_ingredients_cache: dict[int, list[dict]] = {}


def get_cached_default_ingredients(menu_item_id: int, db: Optional[Session] = None) -> list[dict]:
    """
    Get default ingredients with caching.

    Cache is cleared on server restart or when menu data is refreshed.
    """
    if menu_item_id not in _default_ingredients_cache:
        _default_ingredients_cache[menu_item_id] = get_menu_item_default_ingredients(menu_item_id, db)
    return _default_ingredients_cache[menu_item_id]


def clear_default_ingredients_cache():
    """Clear the default ingredients cache."""
    _default_ingredients_cache.clear()
    logger.info("Cleared default ingredients cache")
