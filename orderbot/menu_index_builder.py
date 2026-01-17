# orderbot/menu_index_builder.py

import hashlib
import json
import logging
from typing import Dict, Any, List, Optional

from collections import defaultdict

from sqlalchemy.orm import Session, joinedload, selectinload

logger = logging.getLogger(__name__)

from .models import (
    MenuItem,
    Ingredient,
    IngredientStoreAvailability,
    MenuItemStoreAvailability,
    ItemType,
    ModifierCategory,
    NeighborhoodZipCode,
    ItemTypeAttribute,
    ItemTypeIngredient,
    Company,
    GlobalAttributeOption,
    ItemTypeGlobalAttribute,
    MenuItemSize,
    MenuItemSizePrice,
)
# Note: We no longer import has_linked_attributes, has_askable_attributes, should_skip_config
# These caused N+1 queries. Instead, we pre-load all ItemTypeGlobalAttribute data.


def _preload_item_type_config_status(db: Session) -> Dict[int, Dict[str, Any]]:
    """
    Pre-load configuration status for all item types in a single query.

    This replaces the N+1 query pattern where we called has_linked_attributes()
    and has_askable_attributes() for each item type.

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

    # Group by item_type_id
    attrs_by_type: Dict[int, List] = defaultdict(list)
    for attr in all_global_attrs:
        attrs_by_type[attr.item_type_id].append(attr)

    # Build config status for each item type
    result: Dict[int, Dict[str, Any]] = {}

    # Get all item type IDs
    all_type_ids = db.query(ItemType.id).all()

    for (type_id,) in all_type_ids:
        attrs = attrs_by_type.get(type_id, [])
        has_linked = len(attrs) > 0
        has_askable = any(attr.ask_in_conversation for attr in attrs) if has_linked else False

        result[type_id] = {
            "has_linked_attrs": has_linked,
            "has_askable_attrs": has_askable,
            "is_configurable": has_linked,
            "skip_config": not has_askable,
            "global_attrs": attrs,
        }

    return result


def _preload_all_ingredients(db: Session) -> Dict[str, List[Ingredient]]:
    """
    Pre-load ALL ingredients in a single query, grouped by category.

    This replaces multiple separate queries for bread, cheese, sauce, etc.

    Returns:
        Dict mapping category -> List[Ingredient]
    """
    all_ingredients = db.query(Ingredient).order_by(Ingredient.name).all()

    by_category: Dict[str, List[Ingredient]] = defaultdict(list)
    for ing in all_ingredients:
        if ing.category:
            by_category[ing.category].append(ing)

    return by_category


def _preload_item_type_attributes(db: Session) -> Dict[int, List]:
    """
    Pre-load all item type attributes in a single query.

    Returns:
        Dict mapping item_type_id -> List[ItemTypeAttribute]
    """
    all_attrs = (
        db.query(ItemTypeAttribute)
        .order_by(ItemTypeAttribute.item_type_id, ItemTypeAttribute.display_order)
        .all()
    )

    by_type: Dict[int, List] = defaultdict(list)
    for attr in all_attrs:
        by_type[attr.item_type_id].append(attr)

    return by_type


def _preload_global_attribute_options(db: Session) -> Dict[int, List]:
    """
    Pre-load all global attribute options in a single query.

    Returns:
        Dict mapping global_attribute_id -> List[GlobalAttributeOption]
    """
    all_options = (
        db.query(GlobalAttributeOption)
        .filter(GlobalAttributeOption.is_available == True)  # noqa: E712
        .order_by(GlobalAttributeOption.global_attribute_id, GlobalAttributeOption.display_order)
        .all()
    )

    by_attr: Dict[int, List] = defaultdict(list)
    for opt in all_options:
        by_attr[opt.global_attribute_id].append(opt)

    return by_attr


def _preload_item_type_ingredients(db: Session) -> Dict[tuple, List]:
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

    by_type_group: Dict[tuple, List] = defaultdict(list)
    for link in all_links:
        # Only include if ingredient is also available
        if link.ingredient and link.ingredient.is_available:
            key = (link.item_type_id, link.ingredient_group)
            by_type_group[key].append(link)

    return by_type_group


def _preload_size_prices(db: Session) -> Dict[int, Dict[str, Any]]:
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
    by_menu_item: Dict[int, Dict[str, Any]] = {}
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


def build_menu_index(db: Session, store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Build a rich, LLM-friendly menu JSON structure. Example shape:

    {
      "items_by_type": {
        "bagel": [ ... ],
        "sized_beverage": [ ... ],
        "side": [ ... ],
        "signature_items": [ ... ],  # All items with is_signature=True
      },
      "item_type_display_names": {"bagel": "Bagels", ...},
      "bread_types": ["White", "Wheat", "Rye"],
      "cheese_types": ["Cheddar", "Swiss", "Provolone"],
    }

    All menu structure is data-driven from the item_types and categories tables.
    Use the categories table with MenuItemCategory join to group items.

    Args:
        db: Database session
        store_id: Optional store ID for store-specific ingredient availability
    """
    # Pre-load all data in batched queries to avoid N+1 query problems
    preloaded_config_status = _preload_item_type_config_status(db)
    preloaded_ingredients = _preload_all_ingredients(db)
    preloaded_size_prices = _preload_size_prices(db)

    # Load menu items with eager loading for related objects
    items = (
        db.query(MenuItem)
        .options(
            joinedload(MenuItem.item_type),
        )
        .order_by(MenuItem.id.asc())
        .all()
    )

    # Load all item types from database
    all_item_types = db.query(ItemType).all()

    # Initialize index with items_by_type as the primary data structure
    index: Dict[str, Any] = {
        "items_by_type": {},  # Items grouped by item_type slug
    }

    # Pre-populate items_by_type with all item types from database
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
        # Get default_config from extra_metadata JSON field
        default_config = None
        if item.extra_metadata:
            try:
                meta = json.loads(item.extra_metadata)
                default_config = meta.get("default_config")
            except (json.JSONDecodeError, TypeError):
                pass

        # Get item type info if available
        item_type_slug = None
        item_type_display_name = None
        item_type_skip_config = False
        if item.item_type:
            item_type_slug = item.item_type.slug
            item_type_display_name = item.item_type.display_name
            # Use pre-loaded config status instead of N+1 query
            config_status = preloaded_config_status.get(item.item_type.id, {})
            item_type_skip_config = config_status.get("skip_config", True)

        item_json = {
            "id": item.id,
            "name": item.name,
            "description": item.description,  # Item description (e.g., "Two Eggs, Bacon, and Cheddar")
            "category": item_type_display_name,  # Derived from item_type.display_name
            "is_signature": bool(item.is_signature),
            "skip_config": item_type_skip_config,  # Skip configuration questions (from item type, e.g., sodas)
            "base_price": float(item.base_price),
            "default_config": default_config,  # Contains bread, protein, cheese, toppings, sauces, toasted
            "item_type": item_type_slug,  # Generic item type (e.g., "sandwich", "drink")
            "required_match_phrases": item.required_match_phrases,  # Comma-separated phrases for match filtering
        }

        # Add size pricing data if available (for items with variant-based pricing)
        size_price_data = preloaded_size_prices.get(item.id)
        if size_price_data:
            item_json["size_category_id"] = size_price_data["size_category_id"]
            item_json["size_category_name"] = size_price_data["size_category_name"]
            item_json["size_category_slug"] = size_price_data["size_category_slug"]
            item_json["size_question_text"] = size_price_data["question_text"]
            item_json["size_prices"] = size_price_data["prices"]

        # Add to items_by_type grouping for type-specific queries
        if item_type_slug and item_type_slug in index["items_by_type"]:
            index["items_by_type"][item_type_slug].append(item_json)

        # Also add signature items to the special signature_items list
        if item.is_signature:
            index["items_by_type"]["signature_items"].append(item_json)


    # Convenience lists for quick questions like "what breads do you have?"
    # Data-driven: loop over all ingredient categories from the database
    for category, ingredients in preloaded_ingredients.items():
        # Create {category}_types list (e.g., bread_types, cheese_types)
        index[f"{category}_types"] = [ing.name for ing in ingredients]

        # Create {category}_prices dict for categories where ingredients have prices
        # (useful for custom item pricing)
        prices = {ing.name.lower(): ing.base_price for ing in ingredients if ing.base_price}
        if prices:
            index[f"{category}_prices"] = prices


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
                category = item.item_type.display_name if item.item_type else None
                unavailable_menu_items.append({"name": item.name, "category": category})
    index["unavailable_menu_items"] = unavailable_menu_items

    # Pre-load attribute and option data for _build_item_types_data
    preloaded_type_attrs = _preload_item_type_attributes(db)
    preloaded_global_options = _preload_global_attribute_options(db)
    preloaded_type_ingredients = _preload_item_type_ingredients(db)

    # Add generic item type data for configurable items
    index["item_types"] = _build_item_types_data(
        db,
        store_id,
        preloaded_config_status,
        preloaded_type_attrs,
        preloaded_global_options,
        preloaded_type_ingredients,
    )

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
    index["ingredient_to_items"] = _build_ingredient_to_items(index, preloaded_ingredients)

    # Build company info for customer service inquiries
    index["company_info"] = _build_company_info(db)

    return index


def _build_ingredient_to_items(
    menu_index: Dict[str, Any],
    preloaded_ingredients: Dict[str, List[Any]],
) -> Dict[str, list[Dict[str, Any]]]:
    """
    Build a mapping of ingredients to menu items that contain them by default.

    Scans menu items for ingredients in:
    - Item names (e.g., "Chicken Salad Sandwich")
    - Item descriptions (e.g., "Grilled Chicken, Bacon, Tomato...")
    - default_config values (e.g., {"protein": "Chicken Salad"})

    Args:
        menu_index: The menu index being built
        preloaded_ingredients: Dict mapping category -> List[Ingredient] from _preload_all_ingredients()

    Returns:
        Dict mapping lowercase ingredient names to lists of matching menu items.
        Example: {"chicken": [{"id": 123, "name": "Chicken Salad Sandwich", ...}]}
    """
    import re

    # Get searchable ingredients from all categories (data-driven from database)
    searchable_ingredients: set[str] = set()

    for category, ingredients in preloaded_ingredients.items():
        for ing in ingredients:
            ing_name = ing.name.lower()
            # Add full name
            searchable_ingredients.add(ing_name)
            # Also add individual words (e.g., "chicken salad" -> "chicken", "salad")
            for word in ing_name.split():
                if len(word) > 2:  # Skip short words like "of", "a"
                    searchable_ingredients.add(word)

    ingredient_to_items: Dict[str, list[Dict[str, Any]]] = {
        ing: [] for ing in searchable_ingredients
    }

    # Collect all menu items from items_by_type (data-driven from database)
    all_items: list[Dict[str, Any]] = []
    if "items_by_type" in menu_index:
        for type_slug, items in menu_index["items_by_type"].items():
            if isinstance(items, list):
                all_items.extend(items)

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

        for ingredient in searchable_ingredients:
            # Use word boundary to avoid partial matches (e.g., "ham" in "shamrock")
            if re.search(rf'\b{re.escape(ingredient)}\b', combined_text):
                # Avoid duplicates
                if item not in ingredient_to_items[ingredient]:
                    ingredient_to_items[ingredient].append(item)

    # Remove empty entries
    ingredient_to_items = {k: v for k, v in ingredient_to_items.items() if v}

    # Merge results for ingredient aliases (data-driven from preloaded data)
    # If "lox" is an alias for "nova scotia salmon", share results between them
    # Build alias -> canonical mapping from preloaded ingredients
    alias_to_canonical: Dict[str, str] = {}
    for category_ingredients in preloaded_ingredients.values():
        for ing in category_ingredients:
            canonical_name = ing.name.lower()
            # Add aliases from the ingredient's alias records
            for alias in ing.aliases:
                alias_to_canonical[alias.lower()] = canonical_name

    # Share results between aliases and canonical names
    for alias, canonical in alias_to_canonical.items():
        # If we have results for the canonical name, share with alias
        if canonical in ingredient_to_items and alias not in ingredient_to_items:
            ingredient_to_items[alias] = ingredient_to_items[canonical]
        # If we have results for the alias, share with canonical
        elif alias in ingredient_to_items and canonical not in ingredient_to_items:
            ingredient_to_items[canonical] = ingredient_to_items[alias]

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


def _build_item_types_data(
    db: Session,
    store_id: Optional[str] = None,
    preloaded_config_status: Optional[Dict[int, Dict[str, Any]]] = None,
    preloaded_type_attrs: Optional[Dict[int, List]] = None,
    preloaded_global_options: Optional[Dict[int, List]] = None,
    preloaded_type_ingredients: Optional[Dict[tuple, List]] = None,
) -> Dict[str, Any]:
    """
    Build generic item type data including all attributes and options.

    This provides the LLM with structured information about configurable items
    that goes beyond the hardcoded sandwich attributes.

    Uses the item_type_attributes table (consolidated schema) and global
    attributes for configuring item type options.

    Args:
        db: Database session
        store_id: Optional store ID for availability filtering
        preloaded_config_status: Pre-loaded config status from _preload_item_type_config_status()
        preloaded_type_attrs: Pre-loaded item type attributes from _preload_item_type_attributes()
        preloaded_global_options: Pre-loaded global options from _preload_global_attribute_options()
        preloaded_type_ingredients: Pre-loaded type ingredients from _preload_item_type_ingredients()

    Returns:
        Dict mapping item type slugs to their attribute configurations
    """
    result = {}

    # Use pre-loaded data if available, otherwise load (for backward compatibility)
    if preloaded_config_status is None:
        preloaded_config_status = _preload_item_type_config_status(db)
    if preloaded_type_attrs is None:
        preloaded_type_attrs = _preload_item_type_attributes(db)
    if preloaded_global_options is None:
        preloaded_global_options = _preload_global_attribute_options(db)
    if preloaded_type_ingredients is None:
        preloaded_type_ingredients = _preload_item_type_ingredients(db)

    item_types = db.query(ItemType).all()
    for it in item_types:
        # Use pre-loaded config status instead of N+1 queries
        config_status = preloaded_config_status.get(it.id, {})
        it_is_configurable = config_status.get("has_linked_attrs", False)
        it_skip_config = config_status.get("skip_config", True)

        if not it_is_configurable:
            # Non-configurable items don't need attribute data
            result[it.slug] = {
                "display_name": it.display_name,
                "is_configurable": False,
                "skip_config": it_skip_config,  # Skip configuration questions (e.g., sodas don't need hot/iced)
                "attributes": [],
            }
            continue

        # Get item type attributes from pre-loaded data
        item_type_attrs = preloaded_type_attrs.get(it.id, [])

        attributes = []

        if item_type_attrs:
            # Use new consolidated table
            for ita in item_type_attrs:
                # Check if this attribute loads from ingredients table
                if ita.loads_from_ingredients and ita.ingredient_group:
                    # Get ingredient links from pre-loaded data
                    key = (it.id, ita.ingredient_group)
                    ingredient_links = preloaded_type_ingredients.get(key, [])

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
                    # For ItemTypeAttribute entries that don't load from ingredients
                    # (e.g., boolean types like "toasted"), options are not applicable.
                    # Select-type attributes should use GlobalAttribute via ItemTypeGlobalAttribute.
                    attr_data = {
                        "slug": ita.slug,
                        "display_name": ita.display_name,
                        "input_type": ita.input_type,
                        "is_required": ita.is_required,
                        "allow_none": ita.allow_none,
                        "ask_in_conversation": ita.ask_in_conversation,
                        "question_text": ita.question_text,
                        "options": [],  # No local options; use global attributes for select types
                    }

                if ita.input_type == "multi_select":
                    attr_data["min_selections"] = ita.min_selections
                    attr_data["max_selections"] = ita.max_selections

                attributes.append(attr_data)

        # Get global attributes from pre-loaded config status (already loaded with joinedload)
        # Global attributes are shared across item types with normalized options
        global_attr_links = config_status.get("global_attrs", [])

        # Sort by display_order (they may not be sorted in the pre-loaded data)
        global_attr_links = sorted(global_attr_links, key=lambda x: x.display_order or 0)

        for link in global_attr_links:
            global_attr = link.global_attribute
            if not global_attr:
                continue

            # Get options from pre-loaded global options
            options = preloaded_global_options.get(global_attr.id, [])

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
