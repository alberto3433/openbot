"""
Attribute Loader for Item Type Configuration.

This module provides shared functionality for loading item type attributes
from the database. It consolidates the common DB query patterns used by
CoffeeConfigHandler, MenuItemConfigHandler, and other handlers.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level cache for item type attributes
_attributes_cache: dict[str, dict] = {}


def clear_cache() -> None:
    """Clear the attribute cache. Useful for testing or after DB changes."""
    global _attributes_cache
    _attributes_cache = {}


def load_item_type_attributes(
    item_type_slug: str,
    include_global_attributes: bool = False,
    include_ingredient_metadata: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    Load item type attributes from database.

    This is the core function for loading attributes for any item type.
    Results are cached to avoid repeated DB queries.

    Args:
        item_type_slug: The slug of the item type (e.g., "sized_beverage", "deli_sandwich")
        include_global_attributes: Whether to also load linked global attributes
        include_ingredient_metadata: Whether to include aliases/must_match from ingredients

    Returns:
        Dict with structure:
        {
            "attribute_slug": {
                "slug": "attribute_slug",
                "display_name": "Attribute Name",
                "question_text": "What would you like?",
                "ask_in_conversation": True,
                "input_type": "single_select",
                "display_order": 1,
                "allow_none": False,
                "options": [
                    {"slug": "option1", "display_name": "Option 1", "price": 0.0, ...},
                    ...
                ]
            },
            ...
        }
    """
    cache_key = f"{item_type_slug}:{include_global_attributes}:{include_ingredient_metadata}"
    if cache_key in _attributes_cache:
        return _attributes_cache[cache_key]

    from ..db import SessionLocal
    from ..models import (
        ItemType, ItemTypeAttribute, AttributeOption,
        ItemTypeIngredient, Ingredient,
        ItemTypeGlobalAttribute, GlobalAttribute,
    )

    db = SessionLocal()
    try:
        item_type = db.query(ItemType).filter(ItemType.slug == item_type_slug).first()
        if not item_type:
            logger.warning("Item type '%s' not found in database", item_type_slug)
            _attributes_cache[cache_key] = {}
            return {}

        attrs = db.query(ItemTypeAttribute).filter(
            ItemTypeAttribute.item_type_id == item_type.id
        ).order_by(ItemTypeAttribute.display_order).all()

        result: dict[str, dict[str, Any]] = {}

        for attr in attrs:
            opts_data = _load_attribute_options(
                db, attr, item_type.id, include_ingredient_metadata
            )

            result[attr.slug] = {
                "slug": attr.slug,
                "display_name": attr.display_name,
                "question_text": attr.question_text,
                "ask_in_conversation": attr.ask_in_conversation,
                "input_type": attr.input_type,
                "display_order": attr.display_order,
                "allow_none": getattr(attr, 'allow_none', False),
                "options": opts_data,
            }

        # Optionally load global attributes linked to this item type
        if include_global_attributes:
            _load_global_attributes(db, item_type.id, result)

        _attributes_cache[cache_key] = result
        logger.debug("Loaded %s attributes for item type '%s'", len(result), item_type_slug)
        return result

    finally:
        db.close()


def _load_attribute_options(
    db,
    attr,
    item_type_id: int,
    include_ingredient_metadata: bool = True,
) -> list[dict[str, Any]]:
    """
    Load options for an attribute, either from ingredients or attribute_options.

    Args:
        db: Database session
        attr: ItemTypeAttribute instance
        item_type_id: ID of the item type
        include_ingredient_metadata: Whether to include aliases/must_match

    Returns:
        List of option dictionaries
    """
    from ..models import ItemTypeIngredient, Ingredient, AttributeOption

    opts_data = []

    if attr.loads_from_ingredients and attr.ingredient_group:
        # Load options from item_type_ingredients + ingredients
        ingredient_links = (
            db.query(ItemTypeIngredient)
            .join(Ingredient, ItemTypeIngredient.ingredient_id == Ingredient.id)
            .filter(
                ItemTypeIngredient.item_type_id == item_type_id,
                ItemTypeIngredient.ingredient_group == attr.ingredient_group,
                ItemTypeIngredient.is_available == True,
            )
            .order_by(ItemTypeIngredient.display_order)
            .all()
        )

        for link in ingredient_links:
            ingredient = link.ingredient
            opt_data: dict[str, Any] = {
                "slug": ingredient.slug or ingredient.name.lower().replace(" ", "_"),
                "display_name": link.display_name_override or ingredient.name,
                "price": float(link.price_modifier or 0),
                "is_default": getattr(link, 'is_default', False),
                "category": ingredient.category,
            }
            if include_ingredient_metadata:
                if ingredient.aliases:
                    opt_data["aliases"] = ingredient.aliases
                if ingredient.must_match:
                    opt_data["must_match"] = ingredient.must_match
            opts_data.append(opt_data)
    else:
        # Load options from attribute_options table
        options = db.query(AttributeOption).filter(
            AttributeOption.item_type_attribute_id == attr.id,
            AttributeOption.is_available == True,
        ).order_by(AttributeOption.display_order).all()

        for opt in options:
            opt_data = {
                "slug": opt.slug,
                "display_name": opt.display_name or opt.slug.replace("_", " ").title(),
                "price": float(opt.price_modifier or 0),
                "is_default": getattr(opt, 'is_default', False),
            }
            opts_data.append(opt_data)

    return opts_data


def _load_global_attributes(db, item_type_id: int, result: dict) -> None:
    """
    Load global attributes linked to an item type.

    Args:
        db: Database session
        item_type_id: ID of the item type
        result: Dict to add global attributes to (modified in place)
    """
    from ..models import ItemTypeGlobalAttribute, GlobalAttribute
    from ..menu_data_cache import menu_cache

    global_attr_links = (
        db.query(ItemTypeGlobalAttribute)
        .filter(ItemTypeGlobalAttribute.item_type_id == item_type_id)
        .order_by(ItemTypeGlobalAttribute.display_order)
        .all()
    )

    for link in global_attr_links:
        global_attr = db.query(GlobalAttribute).filter(
            GlobalAttribute.id == link.global_attribute_id
        ).first()
        if not global_attr:
            continue

        # Load options from cache for consistent field mappings
        cached_opts = menu_cache.get_global_attribute_options(global_attr.slug)

        result[global_attr.slug] = {
            "slug": global_attr.slug,
            "display_name": global_attr.display_name,
            "question_text": global_attr.question_text,
            "ask_in_conversation": link.ask_in_conversation,
            "input_type": global_attr.input_type,
            "display_order": link.display_order,
            "allow_none": getattr(global_attr, 'allow_none', True),
            "options": cached_opts,
            "is_global": True,
        }
