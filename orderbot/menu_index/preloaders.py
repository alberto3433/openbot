"""Database preloaders for menu index building.

These functions batch-load data to avoid N+1 query problems.
"""

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session, joinedload

from orderbot.db.models import (
    GlobalAttributeOption,
    ItemType,
    ItemTypeGlobalAttribute,
    ItemTypeIngredient,
    MenuItemIngredient,
    MenuItemSize,
    MenuItemSizePrice,
)


def preload_item_type_config_status(db: Session) -> dict[int, dict[str, Any]]:
    """
    Pre-load configuration status for all item types in a single query.

    This replaces the N+1 query pattern where we called has_linked_attributes()
    and has_askable_attributes() for each item type.

    Uses ItemTypeGlobalAttribute (links to GlobalAttribute) to determine
    which item types have configurable attributes.

    Returns:
        Dict mapping item_type_id -> {
            "has_linked_attrs": bool,
            "has_askable_attrs": bool,
            "is_configurable": bool,
            "skip_config": bool,
            "global_attrs": List[ItemTypeGlobalAttribute]
        }
    """
    # Load ALL global attribute links in one query
    all_global_attrs = (
        db.query(ItemTypeGlobalAttribute)
        .options(joinedload(ItemTypeGlobalAttribute.global_attribute))
        .all()
    )

    # Group global attrs by item_type_id
    global_attrs_by_type: dict[int, list] = defaultdict(list)
    for attr in all_global_attrs:
        global_attrs_by_type[attr.item_type_id].append(attr)

    # Build config status for each item type
    result: dict[int, dict[str, Any]] = {}

    # Get all item type IDs
    all_type_ids = db.query(ItemType.id).all()

    for (type_id,) in all_type_ids:
        global_attrs = global_attrs_by_type.get(type_id, [])

        # Has linked attrs if global attributes exist
        has_linked = len(global_attrs) > 0

        # Has askable attrs if ANY attr has ask_in_conversation=True
        has_askable = any(attr.ask_in_conversation for attr in global_attrs)

        result[type_id] = {
            "has_linked_attrs": has_linked,
            "has_askable_attrs": has_askable,
            "is_configurable": has_linked,
            "skip_config": not has_askable,
            "global_attrs": global_attrs,
        }

    return result


def preload_all_ingredients(db: Session) -> dict[str, list]:
    """
    Pre-load ALL ingredients in a single query, grouped by category.

    This replaces multiple separate queries for bread, cheese, sauce, etc.

    Returns:
        Dict mapping category -> List[Ingredient]
    """
    from orderbot.db.models import Ingredient

    all_ingredients = db.query(Ingredient).order_by(Ingredient.name).all()

    by_category: dict[str, list] = defaultdict(list)
    for ing in all_ingredients:
        if ing.category:
            by_category[ing.category].append(ing)

    return by_category


def preload_global_attribute_options(db: Session) -> dict[int, list]:
    """
    Pre-load all global attribute options in a single query.

    Returns:
        Dict mapping global_attribute_id -> List[GlobalAttributeOption]
    """
    # Load ALL options including unavailable ones (for recognition)
    # Unavailable options allow us to detect when user selects them
    # and provide helpful feedback (e.g., "We don't have medium - we have small or large")
    # Eager-load ingredient relationship for ingredient-linked options
    all_options = (
        db.query(GlobalAttributeOption)
        .options(joinedload(GlobalAttributeOption.ingredient))
        .order_by(GlobalAttributeOption.global_attribute_id, GlobalAttributeOption.display_order)
        .all()
    )

    by_attr: dict[int, list] = defaultdict(list)
    for opt in all_options:
        by_attr[opt.global_attribute_id].append(opt)

    return by_attr


def preload_item_type_ingredients(db: Session) -> dict[tuple, list]:
    """
    Pre-load all item type ingredient links in a single query.

    Returns:
        Dict mapping (item_type_id, ingredient_group) -> List[ItemTypeIngredient]
    """
    all_links = (
        db.query(ItemTypeIngredient)
        .options(joinedload(ItemTypeIngredient.ingredient))
        .filter(ItemTypeIngredient.is_available == True)  # noqa: E712
        .order_by(ItemTypeIngredient.item_type_id, ItemTypeIngredient.display_order)
        .all()
    )

    by_type_group: dict[tuple, list] = defaultdict(list)
    for link in all_links:
        # Only include if ingredient is also available
        if link.ingredient and link.ingredient.is_available:
            key = (link.item_type_id, link.ingredient_group)
            by_type_group[key].append(link)

    return by_type_group


def preload_size_prices(db: Session) -> dict[int, dict[str, Any]]:
    """
    Pre-load all menu item size prices in a single query.

    Returns:
        Dict mapping menu_item_id -> {
            "size_category_id": int,
            "size_category_name": str,
            "size_category_slug": str,
            "question_text": str,
            "prices": [
                {"size_id": int, "size_name": str, "price": float, "display_order": int},
                ...
            ]
        }
    """
    # Load all size prices with their related size and category data
    all_prices = (
        db.query(MenuItemSizePrice)
        .options(
            joinedload(MenuItemSizePrice.size)
            .joinedload(MenuItemSize.category)
        )
        .order_by(MenuItemSizePrice.menu_item_id)
        .all()
    )

    # Group by menu_item_id
    by_menu_item: dict[int, dict[str, Any]] = {}
    for price in all_prices:
        item_id = price.menu_item_id
        size = price.size
        category = size.category if size else None

        if item_id not in by_menu_item:
            by_menu_item[item_id] = {
                "size_category_id": category.id if category else None,
                "size_category_name": category.name if category else None,
                "size_category_slug": category.slug if category else None,
                "question_text": category.question_text if category else None,
                "prices": []
            }

        by_menu_item[item_id]["prices"].append({
            "size_id": size.id if size else None,
            "size_name": size.name if size else None,
            "price": price.price,
            "display_order": size.display_order if size else 0,
        })

    # Sort prices by display_order for each menu item
    for item_id, data in by_menu_item.items():
        data["prices"].sort(key=lambda p: p["display_order"])

    return by_menu_item


def preload_menu_item_ingredients(db: Session) -> dict[int, list[dict[str, Any]]]:
    """
    Pre-load all menu item ingredient links in a single query.

    Returns:
        Dict mapping menu_item_id -> [
            {"ingredient_id": int, "ingredient_name": str, "quantity": int},
            ...
        ]
    """
    all_links = (
        db.query(MenuItemIngredient)
        .options(joinedload(MenuItemIngredient.ingredient))
        .all()
    )

    by_menu_item: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for link in all_links:
        if link.ingredient:
            by_menu_item[link.menu_item_id].append({
                "ingredient_id": link.ingredient_id,
                "ingredient_name": link.ingredient.name,
                "ingredient_slug": link.ingredient.slug,
                "ingredient_category": link.ingredient.category,
                "quantity": link.quantity,
            })

    return dict(by_menu_item)
