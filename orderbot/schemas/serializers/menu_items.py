"""
Menu Item Serializers.

Provides serialization functions for MenuItem and related models.
"""

from sqlalchemy.orm import Session

from orderbot.db.models import MenuItem
from orderbot.schemas.menu import MenuItemOut, SizePriceOut, MenuItemIngredientOut


def serialize_menu_item(
    item: MenuItem,
    db: Session,
    include_ingredients: bool = True
) -> MenuItemOut:
    """Convert MenuItem model to response schema.

    Args:
        item: The MenuItem to serialize
        db: Database session (unused but kept for API consistency)
        include_ingredients: Whether to include ingredients (set False for list
            endpoints to avoid N+1 queries)

    Returns:
        MenuItemOut schema
    """
    # Get size prices
    size_prices = []
    if item.size_prices:
        for sp in item.size_prices:
            size_prices.append(SizePriceOut(
                size_id=sp.size_id,
                size_name=sp.size.name if sp.size else "Unknown",
                price=float(sp.price),
            ))

    # Get ingredients (skip for list endpoints to avoid N+1 queries)
    ingredients = []
    if include_ingredients and item.ingredient_links:
        for link in item.ingredient_links:
            ingredients.append(MenuItemIngredientOut(
                ingredient_id=link.ingredient_id,
                ingredient_name=link.ingredient.name if link.ingredient else "Unknown",
                ingredient_category=link.ingredient.category if link.ingredient else "Unknown",
                quantity=link.quantity,
            ))

    # Check if item has ingredients (dietary values will be computed)
    has_ingredients = bool(item.ingredient_links) if include_ingredients else False

    return MenuItemOut(
        id=item.id,
        name=item.name,
        description=item.description,
        is_signature=item.is_signature,
        base_price=float(item.base_price),
        available_qty=item.available_qty,
        item_type_id=item.item_type_id,
        aliases=item.aliases,
        abbreviation=item.abbreviation,
        required_match_phrases=item.required_match_phrases,
        size_category_id=item.size_category_id,
        size_prices=size_prices,
        ingredients=ingredients,
        # Dietary attributes (fallback values, computed from ingredients at runtime)
        is_vegan=item.is_vegan,
        is_vegetarian=item.is_vegetarian,
        is_gluten_free=item.is_gluten_free,
        is_dairy_free=item.is_dairy_free,
        is_kosher=item.is_kosher,
        # Allergen attributes
        contains_eggs=item.contains_eggs,
        contains_fish=item.contains_fish,
        contains_sesame=item.contains_sesame,
        contains_nuts=item.contains_nuts,
        # Indicates if dietary values are computed (not editable)
        has_ingredients=has_ingredients,
        # Unit of sale
        unit_type=item.unit_type,
        quantity_per_unit=item.quantity_per_unit,
    )
