# sandwich_bot/menu_index_builder.py

import hashlib
import json
from typing import Dict, Any, List

from sqlalchemy.orm import Session

from .models import (
    MenuItem,
    Ingredient,
    Recipe,
    RecipeIngredient,
    RecipeChoiceGroup,
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


def build_menu_index(db: Session) -> Dict[str, Any]:
    """
    Build a rich, LLM-friendly menu JSON structure. Example shape:

    {
      "signature_sandwiches": [ ... ],
      "sides": [ ... ],
      "drinks": [ ... ],
      "desserts": [ ... ],
      "other": [ ... ],
      "bread_types": ["White", "Wheat", "Rye"],
      "cheese_types": ["Cheddar", "Swiss", "Provolone"],
    }
    """
    items = db.query(MenuItem).order_by(MenuItem.id.asc()).all()

    index: Dict[str, Any] = {
        "signature_sandwiches": [],
        "sides": [],
        "drinks": [],
        "desserts": [],
        "other": [],
    }

    for item in items:
        recipe_json = _recipe_to_dict(item.recipe) if item.recipe else None

        item_json = {
            "id": item.id,
            "name": item.name,
            "category": item.category,
            "is_signature": bool(item.is_signature),
            "base_price": float(item.base_price),
            "available_qty": int(item.available_qty),
            "recipe": recipe_json,
        }

        cat = (item.category or "").lower()
        if cat == "sandwich" and item.is_signature:
            index["signature_sandwiches"].append(item_json)
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

    # Sauce types - all ingredients with category 'sauce'
    sauce_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "sauce")
        .order_by(Ingredient.name)
        .all()
    )
    index["sauce_types"] = [ing.name for ing in sauce_ingredients]

    # Protein types - all ingredients with category 'protein'
    protein_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "protein")
        .order_by(Ingredient.name)
        .all()
    )
    index["protein_types"] = [ing.name for ing in protein_ingredients]

    # Topping types - all ingredients with category 'topping'
    topping_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.category == "topping")
        .order_by(Ingredient.name)
        .all()
    )
    index["topping_types"] = [ing.name for ing in topping_ingredients]

    return index


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
