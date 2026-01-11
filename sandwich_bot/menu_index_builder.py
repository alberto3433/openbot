# sandwich_bot/menu_index_builder.py

import hashlib
import json
import logging
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from .models import (
    MenuItem,
    Ingredient,
    Recipe,
    IngredientStoreAvailability,
    MenuItemStoreAvailability,
    ItemType,
    AttributeOption,
    ModifierCategory,
    NeighborhoodZipCode,
    ItemTypeAttribute,
    ItemTypeIngredient,
    MenuItemAttributeValue,
    MenuItemAttributeSelection,
    Company,
    # Global attribute normalization tables
    GlobalAttribute,
    GlobalAttributeOption,
    ItemTypeGlobalAttribute,
)
from .services.item_type_helpers import (
    has_linked_attributes,
    has_askable_attributes,
    should_skip_config,
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


def _preload_menu_item_configs(db: Session) -> Dict[int, Dict[str, Any]]:
    """
    Pre-load all menu item attribute configurations in batched queries.

    This replaces the N+1 query pattern where we queried per menu item.
    Instead, we load everything in 2 queries and group by menu_item_id.

    Returns:
        Dict mapping menu_item_id -> default_config dict
    """
    from collections import defaultdict
    from sqlalchemy.orm import joinedload

    # Load ALL attribute values in one query with eager loading
    all_attr_values = (
        db.query(MenuItemAttributeValue)
        .options(
            joinedload(MenuItemAttributeValue.attribute),
            joinedload(MenuItemAttributeValue.option),
        )
        .all()
    )

    # Load ALL multi-select selections in one query with eager loading
    all_selections = (
        db.query(MenuItemAttributeSelection)
        .options(joinedload(MenuItemAttributeSelection.option))
        .all()
    )

    # Group selections by (menu_item_id, attribute_id) for fast lookup
    selections_by_item_attr: Dict[tuple, List] = defaultdict(list)
    for sel in all_selections:
        key = (sel.menu_item_id, sel.attribute_id)
        selections_by_item_attr[key].append(sel)

    # Group attribute values by menu_item_id
    values_by_item: Dict[int, List] = defaultdict(list)
    for av in all_attr_values:
        values_by_item[av.menu_item_id].append(av)

    # Build config dicts for each menu item
    configs: Dict[int, Dict[str, Any]] = {}

    for menu_item_id, attr_values in values_by_item.items():
        config: Dict[str, Any] = {}

        for av in attr_values:
            attr = av.attribute
            if not attr:
                continue

            slug = attr.slug

            if attr.input_type == "boolean":
                if av.value_boolean is not None:
                    config[slug] = av.value_boolean
            elif attr.input_type == "multi_select":
                # Look up selections from pre-loaded data
                key = (menu_item_id, attr.id)
                selections = selections_by_item_attr.get(key, [])
                if selections:
                    config[slug] = [sel.option.display_name for sel in selections if sel.option]
            else:  # single_select or text
                if av.option:
                    config[slug] = av.option.display_name
                elif av.value_text:
                    config[slug] = av.value_text

        if config:
            configs[menu_item_id] = config

    return configs


def _build_default_config_from_relational(
    menu_item_id: int,
    preloaded_configs: Dict[int, Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """
    Get default_config for a menu item from pre-loaded data.

    Args:
        menu_item_id: The menu item ID
        preloaded_configs: Dict from _preload_menu_item_configs()

    Returns:
        Dict with attribute values, or None if no values exist.
    """
    return preloaded_configs.get(menu_item_id)


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

    # Pre-load all menu item configs in batched queries (fixes N+1 query problem)
    preloaded_configs = _preload_menu_item_configs(db)

    # Determine the primary configurable item type for dynamic category naming
    # A configurable item type has linked global attributes
    all_item_types = db.query(ItemType).all()
    primary_item_type = None
    for it in all_item_types:
        if has_linked_attributes(it.id, db):
            primary_item_type = it
            break
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
    # (all_item_types was already queried above for primary type detection)
    for it in all_item_types:
        index["items_by_type"][it.slug] = []

    # Add a special key for signature items (items with is_signature=true across all types)
    index["items_by_type"]["signature_items"] = []

    # Build display name mapping for item types (for custom plural forms)
    # Only include types that have a custom display_name_plural set
    index["item_type_display_names"] = {
        it.slug: it.display_name_plural
        for it in all_item_types
        if it.display_name_plural
    }

    for item in items:
        recipe_json = _recipe_to_dict(item.recipe) if item.recipe else None

        # Get default_config from relational data (menu_item_attribute_values/selections)
        # Falls back to extra_metadata for legacy items not yet migrated
        default_config = _build_default_config_from_relational(item.id, preloaded_configs)
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
            # Derive skip_config from linked global attributes
            item_type_skip_config = should_skip_config(item.item_type, db)

        item_json = {
            "id": item.id,
            "name": item.name,
            "description": item.description,  # Item description (e.g., "Two Eggs, Bacon, and Cheddar")
            "category": item.category,
            "is_signature": bool(item.is_signature),
            "skip_config": item_type_skip_config,  # Skip configuration questions (from item type, e.g., sodas)
            "base_price": float(item.base_price),
            "recipe": recipe_json,
            "default_config": default_config,  # Contains bread, protein, cheese, toppings, sauces, toasted
            "item_type": item_type_slug,  # Generic item type (e.g., "sandwich", "drink")
            "required_match_phrases": item.required_match_phrases,  # Comma-separated phrases for match filtering
        }

        # Add to items_by_type grouping for type-specific queries
        if item_type_slug and item_type_slug in index["items_by_type"]:
            index["items_by_type"][item_type_slug].append(item_json)

        # Also add signature items to the special signature_items list
        if item.is_signature:
            index["items_by_type"]["signature_items"].append(item_json)

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

    # Cream cheese flavors - extracted from ingredients with 'Cream Cheese' in name
    # These are used for listing cream cheese options to customers
    cream_cheese_flavors = []
    for ing in cheese_ingredients:
        if "cream cheese" in ing.name.lower():
            # Extract flavor (e.g., "Plain Cream Cheese" -> "plain")
            flavor = ing.name.lower().replace(" cream cheese", "").strip()
            if flavor and flavor not in cream_cheese_flavors:
                cream_cheese_flavors.append(flavor)
    index["cream_cheese_flavors"] = cream_cheese_flavors

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

    # Add list of menu items that contain bagels (for bagel configuration questions)
    index["bagel_menu_items"] = _build_bagel_menu_items(db)

    # Build by-pound prices from menu_items with category "by_the_lb" or "cream_cheese"
    # These are items like "Nova Scotia Salmon (1 lb)" -> $44.00
    index["by_pound_prices"] = _build_by_pound_prices(db)

    # Build modifier categories for answering questions like "what sweeteners do you have?"
    index["modifier_categories"] = _build_modifier_categories(db)

    # Build item keyword mappings for modifier inquiry parsing
    # Maps keywords like "latte", "cappuccino" -> "coffee" (item type slug)
    index["item_keywords"] = _build_item_keywords(db)

    # Build neighborhood to zip code mappings for delivery zone lookups
    index["neighborhood_zip_codes"] = _build_neighborhood_zip_codes(db)

    # Build item descriptions mapping for "what's on" queries
    # Maps normalized item names to descriptions
    index["item_descriptions"] = _build_item_descriptions(db)

    # Build ingredient-to-items mapping for ingredient-based search
    # When user says "something with chicken", this index helps find matching items
    index["ingredient_to_items"] = _build_ingredient_to_items(index)

    # Build company info for customer service inquiries
    index["company_info"] = _build_company_info(db)

    return index


def _build_ingredient_to_items(menu_index: Dict[str, Any]) -> Dict[str, list[Dict[str, Any]]]:
    """
    Build a mapping of ingredients to menu items that contain them by default.

    Scans menu items for ingredients in:
    - Item names (e.g., "Chicken Salad Sandwich")
    - Item descriptions (e.g., "Grilled Chicken, Bacon, Tomato...")
    - default_config values (e.g., {"protein": "Chicken Salad"})

    Returns:
        Dict mapping lowercase ingredient names to lists of matching menu items.
        Example: {"chicken": [{"id": 123, "name": "Chicken Salad Sandwich", ...}]}
    """
    import re

    # Common ingredients to index
    # Focus on proteins and key ingredients customers might search for
    SEARCHABLE_INGREDIENTS = {
        # Proteins
        "chicken", "turkey", "bacon", "ham", "pastrami", "corned beef",
        "roast beef", "tuna", "salmon", "lox", "nova", "whitefish",
        "sable", "sturgeon", "egg", "eggs",
        # Other key ingredients
        "avocado", "hummus",
    }

    ingredient_to_items: Dict[str, list[Dict[str, Any]]] = {
        ing: [] for ing in SEARCHABLE_INGREDIENTS
    }

    # Collect all menu items from various categories
    all_items: list[Dict[str, Any]] = []
    for category in ["signature_sandwiches", "custom_sandwiches", "sides", "drinks", "desserts", "other"]:
        if category in menu_index:
            all_items.extend(menu_index[category])

    # Also check items_by_type for comprehensive coverage
    if "items_by_type" in menu_index:
        for type_slug, items in menu_index["items_by_type"].items():
            if isinstance(items, list):
                for item in items:
                    if item not in all_items:
                        all_items.append(item)

    for item in all_items:
        item_name = (item.get("name") or "").lower()
        item_desc = (item.get("description") or "").lower()
        default_config = item.get("default_config") or {}

        # Build searchable text from default_config values
        config_text = " ".join(
            str(v).lower() for v in default_config.values()
            if isinstance(v, str)
        )
        # Also check list values in config (e.g., {"extras": ["Bacon", "Tomato"]})
        for v in default_config.values():
            if isinstance(v, list):
                config_text += " " + " ".join(str(x).lower() for x in v)

        combined_text = f"{item_name} {item_desc} {config_text}"

        for ingredient in SEARCHABLE_INGREDIENTS:
            # Use word boundary to avoid partial matches (e.g., "ham" in "shamrock")
            if re.search(rf'\b{re.escape(ingredient)}\b', combined_text):
                # Avoid duplicates
                if item not in ingredient_to_items[ingredient]:
                    ingredient_to_items[ingredient].append(item)

    # Remove empty entries
    ingredient_to_items = {k: v for k, v in ingredient_to_items.items() if v}

    # Add common aliases
    if "lox" in ingredient_to_items or "salmon" in ingredient_to_items:
        # Merge lox and salmon results
        combined = []
        for item in ingredient_to_items.get("lox", []) + ingredient_to_items.get("salmon", []):
            if item not in combined:
                combined.append(item)
        if combined:
            ingredient_to_items["lox"] = combined
            ingredient_to_items["salmon"] = combined
            ingredient_to_items["nova"] = combined

    return ingredient_to_items


def _build_item_keywords(db: Session) -> Dict[str, str]:
    """
    Build a keyword-to-item-type-slug mapping from ItemType aliases.

    This maps user input keywords like "latte", "cappuccino", "bagels"
    to their canonical item type slugs like "coffee", "bagel".

    Returns:
        Dict mapping lowercase keywords to item type slugs.
        Example: {"latte": "coffee", "lattes": "coffee", "cappuccino": "coffee"}
    """
    keyword_to_slug: Dict[str, str] = {}

    item_types = db.query(ItemType).all()
    for it in item_types:
        # Add the slug and display_name as keywords
        keyword_to_slug[it.slug.lower()] = it.slug
        if it.display_name:
            keyword_to_slug[it.display_name.lower()] = it.slug

        # Add aliases from the child table (now a list)
        for alias in it.aliases:
            alias = alias.strip().lower()
            if alias:
                keyword_to_slug[alias] = it.slug

    return keyword_to_slug


def _build_item_types_data(db: Session, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build generic item type data including all attributes and options.

    This provides the LLM with structured information about configurable items
    that goes beyond the hardcoded sandwich attributes.

    Uses the item_type_attributes table (consolidated schema) and global
    attributes for configuring item type options.

    Args:
        db: Database session
        store_id: Optional store ID for availability filtering

    Returns:
        Dict mapping item type slugs to their attribute configurations
    """
    result = {}

    item_types = db.query(ItemType).all()
    for it in item_types:
        # Derive configurability from linked global attributes
        it_is_configurable = has_linked_attributes(it.id, db)
        it_skip_config = not has_askable_attributes(it.id, db) if it_is_configurable else True

        if not it_is_configurable:
            # Non-configurable items don't need attribute data
            result[it.slug] = {
                "display_name": it.display_name,
                "is_configurable": False,
                "skip_config": it_skip_config,  # Skip configuration questions (e.g., sodas don't need hot/iced)
                "attributes": [],
            }
            continue

        # Try new item_type_attributes table first (consolidated schema)
        item_type_attrs = (
            db.query(ItemTypeAttribute)
            .filter(ItemTypeAttribute.item_type_id == it.id)
            .order_by(ItemTypeAttribute.display_order)
            .all()
        )

        attributes = []

        if item_type_attrs:
            # Use new consolidated table
            for ita in item_type_attrs:
                # Check if this attribute loads from ingredients table
                if ita.loads_from_ingredients and ita.ingredient_group:
                    # Load options from item_type_ingredients table
                    ingredient_links = (
                        db.query(ItemTypeIngredient)
                        .join(Ingredient)
                        .filter(
                            ItemTypeIngredient.item_type_id == it.id,
                            ItemTypeIngredient.ingredient_group == ita.ingredient_group,
                            ItemTypeIngredient.is_available == True,
                            Ingredient.is_available == True  # Also check ingredient availability
                        )
                        .order_by(ItemTypeIngredient.display_order)
                        .all()
                    )

                    attr_data = {
                        "slug": ita.slug,
                        "display_name": ita.display_name,
                        "input_type": ita.input_type,
                        "is_required": ita.is_required,
                        "allow_none": ita.allow_none,
                        "ask_in_conversation": ita.ask_in_conversation,
                        "question_text": ita.question_text,
                        "loads_from_ingredients": True,
                        "ingredient_group": ita.ingredient_group,
                        "options": [
                            {
                                "slug": link.ingredient.slug,  # Use ingredient slug column
                                "display_name": link.display_name_override or link.ingredient.name,
                                "ingredient_id": link.ingredient_id,
                                "ingredient_name": link.ingredient.name,
                                "price_modifier": float(link.price_modifier),
                                "iced_price_modifier": 0.0,  # No iced modifier for ingredients (handled elsewhere)
                                "is_default": link.is_default,
                            }
                            for link in ingredient_links
                        ],
                    }
                else:
                    # Get options linked to this attribute via item_type_attribute_id (new FK)
                    options = (
                        db.query(AttributeOption)
                        .filter(
                            AttributeOption.item_type_attribute_id == ita.id,
                            AttributeOption.is_available == True
                        )
                        .order_by(AttributeOption.display_order)
                        .all()
                    )

                    attr_data = {
                        "slug": ita.slug,
                        "display_name": ita.display_name,
                        "input_type": ita.input_type,
                        "is_required": ita.is_required,
                        "allow_none": ita.allow_none,
                        "ask_in_conversation": ita.ask_in_conversation,
                        "question_text": ita.question_text,
                        "options": [
                            {
                                "slug": opt.slug,
                                "display_name": opt.display_name,
                                "price_modifier": opt.price_modifier,
                                "iced_price_modifier": getattr(opt, 'iced_price_modifier', 0.0) or 0.0,
                                "is_default": opt.is_default,
                            }
                            for opt in options
                        ],
                    }

                if ita.input_type == "multi_select":
                    attr_data["min_selections"] = ita.min_selections
                    attr_data["max_selections"] = ita.max_selections

                attributes.append(attr_data)

        # Also load global attributes linked to this item type
        # Global attributes are shared across item types with normalized options
        global_attr_links = (
            db.query(ItemTypeGlobalAttribute)
            .filter(ItemTypeGlobalAttribute.item_type_id == it.id)
            .order_by(ItemTypeGlobalAttribute.display_order)
            .all()
        )

        for link in global_attr_links:
            global_attr = link.global_attribute
            if not global_attr:
                continue

            # Get options from global_attribute_options table
            options = (
                db.query(GlobalAttributeOption)
                .filter(
                    GlobalAttributeOption.global_attribute_id == global_attr.id,
                    GlobalAttributeOption.is_available == True
                )
                .order_by(GlobalAttributeOption.display_order)
                .all()
            )

            attr_data = {
                "slug": global_attr.slug,
                "display_name": global_attr.display_name,
                "input_type": global_attr.input_type,
                "is_required": link.is_required,
                "allow_none": link.allow_none,
                "ask_in_conversation": link.ask_in_conversation,
                "question_text": link.question_text,
                "is_global": True,  # Flag to indicate this is from global attributes
                "options": [
                    {
                        "slug": opt.slug,
                        "display_name": opt.display_name,
                        "price_modifier": opt.price_modifier,
                        "iced_price_modifier": opt.iced_price_modifier or 0.0,
                        "is_default": opt.is_default,
                    }
                    for opt in options
                ],
            }

            if global_attr.input_type == "multi_select":
                attr_data["min_selections"] = link.min_selections
                attr_data["max_selections"] = link.max_selections

            attributes.append(attr_data)

        result[it.slug] = {
            "display_name": it.display_name,
            "is_configurable": True,
            "skip_config": it_skip_config,  # Skip config if no attributes have ask_in_conversation=True
            "attributes": attributes,
        }

    return result


def _build_bagel_menu_items(db: Session) -> List[Dict[str, Any]]:
    """
    Find all menu items that contain a bagel as an ingredient.

    These items need bagel configuration questions (bagel type, toasted).

    Checks for:
    1. Base ingredients with category='bread' and name containing 'bagel'
    2. Choice groups named 'Bagel' or similar
    3. Choice group options that are bagel ingredients

    Returns:
        List of dicts with: id, name, default_bagel_type (from recipe default or None)
    """
    bagel_menu_items: List[Dict[str, Any]] = []
    seen_item_ids: set = set()

    # Get all menu items with recipes
    items_with_recipes = (
        db.query(MenuItem)
        .filter(MenuItem.recipe_id.isnot(None))
        .all()
    )

    for item in items_with_recipes:
        if item.id in seen_item_ids:
            continue

        recipe = item.recipe
        if not recipe:
            continue

        has_bagel = False
        default_bagel_type = None

        # Check 1: Base ingredients with category='bread' and name contains 'bagel'
        for ri in recipe.ingredients:
            ing = ri.ingredient
            if ing.category and ing.category.lower() == "bread":
                if "bagel" in ing.name.lower():
                    has_bagel = True
                    # Use this as default bagel type
                    default_bagel_type = ing.name
                    break

        # Check 2 & 3: Choice groups named 'Bagel' or with bagel options
        if not has_bagel:
            for cg in recipe.choice_groups:
                # Check if group name suggests bagel (e.g., "Bagel", "Bagel Type", "Bread")
                group_name_lower = cg.name.lower() if cg.name else ""
                is_bagel_group = "bagel" in group_name_lower

                for ci in cg.choices:
                    ing = ci.ingredient
                    # Check if ingredient is a bagel
                    is_bagel_ingredient = (
                        ing.category and ing.category.lower() == "bread" and
                        "bagel" in ing.name.lower()
                    )
                    # Also check group name for "bread" groups with bagel options
                    if is_bagel_ingredient or (is_bagel_group and ing.category and ing.category.lower() == "bread"):
                        has_bagel = True
                        # Use default choice as default bagel type
                        if ci.is_default:
                            default_bagel_type = ing.name
                        break
                if has_bagel:
                    break

        if has_bagel:
            seen_item_ids.add(item.id)
            bagel_menu_items.append({
                "id": item.id,
                "name": item.name,
                "default_bagel_type": default_bagel_type,
            })

    return bagel_menu_items


def _build_by_pound_prices(db: Session) -> Dict[str, float]:
    """
    Build a dictionary of by-pound prices from menu items.

    Queries menu items with category "by_the_lb" or "cream_cheese" and extracts
    per-pound prices. Creates aliases for common variations.

    Returns:
        Dict mapping normalized item names (lowercase) to per-pound prices.
        Example: {"nova scotia salmon": 44.0, "nova": 44.0, "lox": 44.0}
    """
    import re

    prices: Dict[str, float] = {}

    # Query all by-pound items from database
    by_pound_items = (
        db.query(MenuItem)
        .filter(MenuItem.category.in_(["by_the_lb", "cream_cheese"]))
        .all()
    )

    # Parse item names and calculate per-pound prices
    # Items are stored as "Name (1 lb)" or "Name (1/4 lb)"
    for item in by_pound_items:
        name = item.name
        price = float(item.base_price or 0)

        # Extract weight from name: "(1 lb)", "(1/4 lb)", "(Whole)"
        weight_match = re.search(r'\(([\d/]+)\s*lb\)', name, re.IGNORECASE)
        whole_match = re.search(r'\(Whole\)', name, re.IGNORECASE)

        if weight_match:
            weight_str = weight_match.group(1)
            # Calculate weight as float
            if '/' in weight_str:
                num, denom = weight_str.split('/')
                weight = float(num) / float(denom)
            else:
                weight = float(weight_str)

            # Calculate per-pound price
            per_pound = price / weight if weight > 0 else price

            # Extract base name (without weight)
            base_name = re.sub(r'\s*\([\d/]+\s*lb\)', '', name, flags=re.IGNORECASE).strip()
            base_name_lower = base_name.lower()

            # Only store if this is better precision (1 lb over 1/4 lb)
            # or if we don't have this item yet
            if base_name_lower not in prices or weight >= 1:
                prices[base_name_lower] = round(per_pound, 2)

        elif whole_match:
            # Items like "Whitefish (Whole)" - store as-is without calculating per-pound
            base_name = re.sub(r'\s*\(Whole\)', '', name, flags=re.IGNORECASE).strip()
            base_name_lower = base_name.lower()
            # For whole items, we store the whole price (used differently)
            # Only add if not already present from a per-pound entry
            if base_name_lower not in prices:
                prices[base_name_lower] = round(price, 2)

    # Add common aliases for fish items
    aliases = {
        "nova scotia salmon": ["nova", "lox", "nova scotia salmon (lox)"],
        "whitefish salad": ["whitefish"],  # Common shorthand
        "lake sturgeon": ["sturgeon", "smoked sturgeon"],
        "smoked trout": ["trout"],
        "plain cream cheese": ["cream cheese"],
    }

    for base_name, alias_list in aliases.items():
        if base_name in prices:
            for alias in alias_list:
                if alias not in prices:
                    prices[alias] = prices[base_name]

    return prices


def _build_modifier_categories(db: Session) -> Dict[str, Any]:
    """
    Build modifier category data for answering questions like "what sweeteners do you have?"

    Returns a dictionary that maps user input keywords to category information.
    For database-backed categories, loads the actual options from the Ingredient table.

    Returns:
        Dict with structure:
        {
            "keyword_to_category": {
                "sweetener": "sweeteners",
                "sugar": "sweeteners",
                ...
            },
            "categories": {
                "sweeteners": {
                    "display_name": "Sweeteners",
                    "description": "For sweeteners, we have sugar, raw sugar...",
                    "prompt_suffix": "Would you like any of these in your drink?",
                    "options": ["sugar", "raw sugar", "honey", ...]  # Only for db-backed
                },
                ...
            }
        }
    """
    categories = db.query(ModifierCategory).all()

    keyword_to_category: Dict[str, str] = {}
    category_data: Dict[str, Dict[str, Any]] = {}

    for cat in categories:
        # Build keyword mappings from aliases (now a list from child table)
        for alias in cat.aliases:
            alias = alias.strip().lower()
            if alias:
                keyword_to_category[alias] = cat.slug

        # Build category data
        cat_info: Dict[str, Any] = {
            "display_name": cat.display_name,
            "description": cat.description,
            "prompt_suffix": cat.prompt_suffix,
        }

        # For database-backed categories, load options from Ingredient table
        if cat.loads_from_ingredients and cat.ingredient_category:
            ingredients = (
                db.query(Ingredient)
                .filter(
                    Ingredient.category == cat.ingredient_category,
                    Ingredient.is_available == True
                )
                .order_by(Ingredient.name)
                .all()
            )
            cat_info["options"] = [ing.name for ing in ingredients]

            # Build description dynamically if not set
            if not cat.description and cat_info["options"]:
                options_list = ", ".join(cat_info["options"])
                cat_info["description"] = f"For {cat.display_name.lower()}, we have {options_list}."

        category_data[cat.slug] = cat_info

    return {
        "keyword_to_category": keyword_to_category,
        "categories": category_data,
    }


def _build_neighborhood_zip_codes(db: Session) -> Dict[str, List[str]]:
    """
    Build a neighborhood-to-zip-codes mapping from the database.

    Used for delivery zone lookups when customers specify a neighborhood
    instead of a zip code.

    Returns:
        Dict mapping lowercase neighborhood names to lists of zip codes.
        Example: {"tribeca": ["10007", "10013", "10282"], "uws": ["10023", "10024", "10025"]}
    """
    neighborhoods = db.query(NeighborhoodZipCode).all()

    result: Dict[str, List[str]] = {}
    for n in neighborhoods:
        result[n.neighborhood.lower()] = n.zip_codes or []

    return result


def _build_item_descriptions(db: Session) -> Dict[str, str]:
    """
    Build an item-name-to-description mapping from menu items.

    Used for answering "what's on the X" questions without hardcoded descriptions.

    Returns:
        Dict mapping lowercase item names to descriptions.
        Example: {"the classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar"}
    """
    # Get all menu items with descriptions
    items = db.query(MenuItem).filter(MenuItem.description.isnot(None)).all()

    result: Dict[str, str] = {}
    for item in items:
        name_lower = item.name.lower()
        result[name_lower] = item.description

        # Also add without "the " prefix for easier matching
        if name_lower.startswith("the "):
            result[name_lower[4:]] = item.description

    return result


def _build_company_info(db: Session) -> Dict[str, Any]:
    """
    Build company info for customer service inquiries.

    Used to provide contact information when users want to speak to a manager,
    report issues, or request refunds.

    Returns:
        Dict with company contact information.
        Example: {
            "corporate_email": "zuckersbagelsnyc@gmail.com",
            "corporate_phone": "212-555-0000",
            "instagram_handle": "@zuckersbagels",
            "feedback_form_url": "https://survey.example.com/feedback"
        }
    """
    company = db.query(Company).first()

    if not company:
        return {}

    return {
        "corporate_email": company.corporate_email,
        "corporate_phone": company.corporate_phone,
        "instagram_handle": company.instagram_handle,
        "feedback_form_url": company.feedback_form_url,
    }


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
