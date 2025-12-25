# sandwich_bot/menu_index_builder.py

import hashlib
import json
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from .models import (
    MenuItem,
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeChoiceGroup,
    IngredientStoreAvailability,
    MenuItemStoreAvailability,
    ItemType,
    AttributeDefinition,
    AttributeOption,
)


def _recipe_to_dict(recipe: Recipe) -> Dict[str, Any]:
    if not recipe:
        return None

    # Base (always included) ingredients
    base_ingredients: List[Dict[str, Any]] = []
    for ri in recipe.ingredients:
        ingr = ri.ingredient
        base_ingredients.append({
            "ingredient_id": ingr.id,
            "name": ingr.name,
            "category": ingr.category,
            "quantity": ri.quantity,
            "unit": ri.unit_override or ingr.unit,
            "is_required": ri.is_required,
        })

    # Choice groups (Bread, Cheese, Sauce, etc.)
    choice_groups: List[Dict[str, Any]] = []
    for cg in recipe.choice_groups:
        group = {
            "id": cg.id,
            "name": cg.name,
            "min_choices": cg.min_choices,
            "max_choices": cg.max_choices,
            "is_required": cg.is_required,
            "options": [],
        }
        for ci in cg.choices:
            ingr = ci.ingredient
            group["options"].append({
                "ingredient_id": ingr.id,
                "name": ingr.name,
                "category": ingr.category,
                "is_default": ci.is_default,
                "extra_price": ci.extra_price,
            })
        choice_groups.append(group)

    return {
        "id": recipe.id,
        "name": recipe.name,
        "description": recipe.description,
        "base_ingredients": base_ingredients,
        "choice_groups": choice_groups,
    }


def build_menu_index(db: Session, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a rich, LLM-friendly menu JSON structure. Example shape:

    {
      "signature_sandwiches": [ ... ],  # or "signature_pizzas" for pizza shops
      "sides": [ ... ],
      "drinks": [ ... ],
      "desserts": [ ... ],
      "other": [ ... ],
      "bread_types": ["White", "Wheat", "Rye"],
      "cheese_types": ["Cheddar", "Swiss", "Provolone"],
    }

    Args:
        db: Database session
        store_id: Optional store ID for store-specific ingredient availability
    """
    items = db.query(MenuItem).order_by(MenuItem.id.asc()).all()

    # Determine the primary configurable item type for dynamic category naming
    primary_item_type = db.query(ItemType).filter(ItemType.is_configurable == True).first()
    primary_type_slug = primary_item_type.slug if primary_item_type else "sandwich"

    # Build dynamic category names (handle pluralization correctly)
    def pluralize(word: str) -> str:
        if word.endswith("ch") or word.endswith("s") or word.endswith("x"):
            return word + "es"
        return word + "s"

    signature_key = f"signature_{pluralize(primary_type_slug)}"
    custom_key = f"custom_{pluralize(primary_type_slug)}"

    index: Dict[str, Any] = {
        signature_key: [],
        custom_key: [],  # Build-your-own items
        "sides": [],
        "drinks": [],
        "desserts": [],
        "other": [],
        "items_by_type": {},  # Items grouped by item_type slug for type-specific queries
    }

    # Pre-populate items_by_type with all item types from database
    all_item_types = db.query(ItemType).all()
    for it in all_item_types:
        index["items_by_type"][it.slug] = []

    for item in items:
        recipe_json = _recipe_to_dict(item.recipe) if item.recipe else None

        # Get default_config from the new column, fall back to extra_metadata for migration
        default_config = item.default_config
        if default_config is None and item.extra_metadata:
            try:
                meta = json.loads(item.extra_metadata)
                default_config = meta.get("default_config")
            except (json.JSONDecodeError, TypeError):
                pass

        # Get item type info if available
        item_type_slug = None
        item_type_skip_config = False
        if item.item_type:
            item_type_slug = item.item_type.slug
            item_type_skip_config = bool(item.item_type.skip_config)

        item_json = {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "is_signature": bool(item.is_signature),
            "skip_config": item_type_skip_config,  # Skip configuration questions (from item type, e.g., sodas)
            "base_price": float(item.base_price),
            "available_qty": int(item.available_qty),
            "recipe": recipe_json,
            "default_config": default_config,  # Contains bread, protein, cheese, toppings, sauces, toasted
            "item_type": item_type_slug,  # Generic item type (e.g., "sandwich", "drink")
        }

        # Add to items_by_type grouping for type-specific queries
        if item_type_slug and item_type_slug in index["items_by_type"]:
            index["items_by_type"][item_type_slug].append(item_json)

        cat = (item.category or "").lower()
        # Handle both "sandwich"/"pizza" and "signature" categories for main items
        # Use substring matching to handle categories like "Signature Sandwich"
        is_main_item_type = (
            cat == primary_type_slug
            or "sandwich" in cat
            or "signature" in cat
            or cat == "bagel"
        )
        if is_main_item_type and item.is_signature:
            index[signature_key].append(item_json)
        elif is_main_item_type and not item.is_signature:
            index[custom_key].append(item_json)
        elif cat == "side":
            index["sides"].append(item_json)
        elif cat == "drink":
            index["drinks"].append(item_json)
        elif cat == "dessert":
            index["desserts"].append(item_json)
        else:
            index["other"].append(item_json)

    # Convenience lists for quick questions like "what breads do you have?"
    # These are pulled directly from the Ingredient table by category,
    # allowing admins to manage options independently of recipes.

    # Bread types - all ingredients with category 'bread'
    bread_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "bread")
        .order_by(Ingredient.name)
        .all()
    )
    index["bread_types"] = [ing.name for ing in bread_ingredients]

    # Cheese types - all ingredients with category 'cheese'
    cheese_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "cheese")
        .order_by(Ingredient.name)
        .all()
    )
    index["cheese_types"] = [ing.name for ing in cheese_ingredients]
    index["cheese_prices"] = {ing.name.lower(): ing.base_price for ing in cheese_ingredients}

    # Sauce types - all ingredients with category 'sauce'
    sauce_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "sauce")
        .order_by(Ingredient.name)
        .all()
    )
    index["sauce_types"] = [ing.name for ing in sauce_ingredients]

    # Protein types - all ingredients with category 'protein' (include prices for custom sandwiches)
    protein_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "protein")
        .order_by(Ingredient.name)
        .all()
    )
    index["protein_types"] = [ing.name for ing in protein_ingredients]
    index["protein_prices"] = {ing.name.lower(): ing.base_price for ing in protein_ingredients}

    # Bread prices for custom sandwiches
    index["bread_prices"] = {ing.name.lower(): ing.base_price for ing in bread_ingredients}

    # Topping types - all ingredients with category 'topping'
    topping_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "topping")
        .order_by(Ingredient.name)
        .all()
    )
    index["topping_types"] = [ing.name for ing in topping_ingredients]

    # Unavailable ingredients (86'd items) - so LLM knows what's out of stock
    # Check store-specific availability if store_id provided
    unavailable_ingredients = []
    if store_id:
        # Get ingredients that are 86'd for this specific store
        store_unavail = (
            db.query(IngredientStoreAvailability)
            .filter(
                IngredientStoreAvailability.store_id == store_id,
                IngredientStoreAvailability.is_available == False
            )
            .all()
        )
        unavail_ids = {sa.ingredient_id for sa in store_unavail}
        for ing_id in unavail_ids:
            ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
            if ing:
                unavailable_ingredients.append({"name": ing.name, "category": ing.category})
    else:
        # Fall back to global unavailable
        unavailable = (
            db.query(Ingredient)
            .filter(Ingredient.is_available == False)
            .order_by(Ingredient.category, Ingredient.name)
            .all()
        )
        unavailable_ingredients = [
            {"name": ing.name, "category": ing.category}
            for ing in unavailable
        ]
    index["unavailable_ingredients"] = unavailable_ingredients

    # Unavailable menu items (86'd items) - so LLM knows what menu items are out of stock
    # Menu items are only tracked per-store (no global fallback)
    unavailable_menu_items = []
    if store_id:
        # Get menu items that are 86'd for this specific store
        store_unavail_items = (
            db.query(MenuItemStoreAvailability)
            .filter(
                MenuItemStoreAvailability.store_id == store_id,
                MenuItemStoreAvailability.is_available == False
            )
            .all()
        )
        unavail_item_ids = {sa.menu_item_id for sa in store_unavail_items}
        for item_id in unavail_item_ids:
            item = db.query(MenuItem).filter(MenuItem.id == item_id).first()
            if item:
                unavailable_menu_items.append({"name": item.name, "category": item.category})
    index["unavailable_menu_items"] = unavailable_menu_items

    # Add generic item type data for configurable items
    index["item_types"] = _build_item_types_data(db, store_id)

    return index


def _build_item_types_data(db: Session, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build generic item type data including all attributes and options.

    This provides the LLM with structured information about configurable items
    that goes beyond the hardcoded sandwich attributes.

    Args:
        db: Database session
        store_id: Optional store ID for availability filtering

    Returns:
        Dict mapping item type slugs to their attribute configurations
    """
    result = {}

    item_types = db.query(ItemType).all()
    for it in item_types:
        if not it.is_configurable:
            # Non-configurable items don't need attribute data
            result[it.slug] = {
                "display_name": it.display_name,
                "is_configurable": False,
                "skip_config": bool(it.skip_config),  # Skip configuration questions (e.g., sodas don't need hot/iced)
                "attributes": [],
            }
            continue

        # Get all attribute definitions for this item type
        attr_defs = (
            db.query(AttributeDefinition)
            .filter(AttributeDefinition.item_type_id == it.id)
            .order_by(AttributeDefinition.display_order)
            .all()
        )

        attributes = []
        for ad in attr_defs:
            # Get options for this attribute
            options_query = (
                db.query(AttributeOption)
                .filter(AttributeOption.attribute_definition_id == ad.id)
                .order_by(AttributeOption.display_order)
            )

            # Filter by availability
            options = options_query.filter(AttributeOption.is_available == True).all()

            attr_data = {
                "slug": ad.slug,
                "display_name": ad.display_name,
                "input_type": ad.input_type,
                "is_required": ad.is_required,
                "allow_none": ad.allow_none,
                "options": [
                    {
                        "slug": opt.slug,
                        "display_name": opt.display_name,
                        "price_modifier": opt.price_modifier,
                        "is_default": opt.is_default,
                    }
                    for opt in options
                ],
            }

            if ad.input_type == "multi_select":
                attr_data["min_selections"] = ad.min_selections
                attr_data["max_selections"] = ad.max_selections

            attributes.append(attr_data)

        result[it.slug] = {
            "display_name": it.display_name,
            "is_configurable": True,
            "skip_config": bool(it.skip_config),  # Skip configuration questions (e.g., sodas don't need hot/iced)
            "attributes": attributes,
        }

    return result


def get_menu_version(menu_index: Dict[str, Any]) -> str:
    """
    Generate a deterministic hash of the menu for version tracking.

    Used to detect if the menu has changed since it was last sent to the LLM,
    allowing us to skip sending the menu again if it hasn't changed.

    Args:
        menu_index: The menu dictionary from build_menu_index()

    Returns:
        A 12-character hex string hash of the menu
    """
    # Sort keys for deterministic serialization
    menu_str = json.dumps(menu_index, sort_keys=True)
    return hashlib.md5(menu_str.encode()).hexdigest()[:12]
