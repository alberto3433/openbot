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
    RecipeChoiceItem,
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
    # We derive them from the choice groups + ingredient categories.

    # Bread types that appear in any choice group
    bread_ingredients = (
        db.query(Ingredient)
        .join(RecipeChoiceItem, RecipeChoiceItem.ingredient_id == Ingredient.id)
        .join(RecipeChoiceGroup, RecipeChoiceGroup.id == RecipeChoiceItem.choice_group_id)
        .filter(Ingredient.category == "bread")
        .distinct()
        .all()
    )
    index["bread_types"] = [ing.name for ing in bread_ingredients]

    # Cheese types that appear in any choice group
    cheese_ingredients = (
        db.query(Ingredient)
        .join(RecipeChoiceItem, RecipeChoiceItem.ingredient_id == Ingredient.id)
        .join(RecipeChoiceGroup, RecipeChoiceGroup.id == RecipeChoiceItem.choice_group_id)
        .filter(Ingredient.category == "cheese")
        .distinct()
        .all()
    )
    index["cheese_types"] = [ing.name for ing in cheese_ingredients]

    # (Optional) Sauce types
    sauce_ingredients = (
        db.query(Ingredient)
        .join(RecipeChoiceItem, RecipeChoiceItem.ingredient_id == Ingredient.id)
        .join(RecipeChoiceGroup, RecipeChoiceGroup.id == RecipeChoiceItem.choice_group_id)
        .filter(Ingredient.category == "sauce")
        .distinct()
        .all()
    )
    index["sauce_types"] = [ing.name for ing in sauce_ingredients]

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
