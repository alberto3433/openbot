"""Builder functions for menu index components."""

import re
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from orderbot.cache.base import normalize_text
from orderbot.db.models import (
    Ingredient,
    ItemType,
    MenuItem,
    ModifierCategory,
    NeighborhoodZipCode,
)
from orderbot.services.store_service import get_company

from .preloaders import (
    preload_global_attribute_options,
    preload_item_type_config_status,
)


def build_ingredient_to_items(
    menu_index: dict[str, Any],
    preloaded_ingredients: dict[str, list[Any]],
    preloaded_menu_item_ingredients: dict[int, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Build a mapping of ingredients to menu items that contain them by default.

    Uses two data sources for comprehensive coverage:
    1. Junction table (menu_item_ingredients) - explicit ingredient links
    2. Text matching on names/descriptions - implicit ingredient references

    Args:
        menu_index: The menu index being built
        preloaded_ingredients: Dict mapping category -> List[Ingredient]
        preloaded_menu_item_ingredients: Dict mapping menu_item_id -> List[ingredient info]

    Returns:
        Dict mapping lowercase ingredient names to lists of matching menu items.
        Example: {"chicken": [{"id": 123, "name": "Chicken Salad Sandwich", ...}]}
    """
    ingredient_to_items: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Build menu_item_id -> item_json lookup from the menu index
    item_by_id: dict[int, dict[str, Any]] = {}
    if "items_by_type" in menu_index:
        for type_slug, items in menu_index["items_by_type"].items():
            if isinstance(items, list):
                for item in items:
                    item_id = item.get("id")
                    if item_id:
                        item_by_id[item_id] = item

    # Build alias -> canonical name mapping for ingredients
    alias_to_canonical: dict[str, str] = {}
    for category_ingredients in preloaded_ingredients.values():
        for ing in category_ingredients:
            canonical_name = ing.name.lower()
            for alias in ing.aliases:
                alias_to_canonical[alias.lower()] = canonical_name

    # ========================================
    # SOURCE 1: Junction table (explicit links)
    # ========================================
    for menu_item_id, ingredients in preloaded_menu_item_ingredients.items():
        item_json = item_by_id.get(menu_item_id)
        if not item_json:
            continue

        for ing_info in ingredients:
            ing_name = ing_info["ingredient_name"].lower()

            # Add to results for canonical name
            if item_json not in ingredient_to_items[ing_name]:
                ingredient_to_items[ing_name].append(item_json)

            # Also add individual words from multi-word ingredients
            for word in ing_name.split():
                if len(word) > 2:
                    if item_json not in ingredient_to_items[word]:
                        ingredient_to_items[word].append(item_json)

    # ========================================
    # SOURCE 2: Text matching (implicit references)
    # ========================================
    # Get searchable ingredients from all categories
    searchable_ingredients: set[str] = set()
    for category_ingredients in preloaded_ingredients.values():
        for ing in category_ingredients:
            ing_name = ing.name.lower()
            searchable_ingredients.add(ing_name)
            for word in ing_name.split():
                if len(word) > 2:
                    searchable_ingredients.add(word)

    # Scan menu items for ingredient mentions in name/description
    for item in item_by_id.values():
        item_name = (item.get("name") or "").lower()
        item_desc = (item.get("description") or "").lower()
        combined_text = f"{item_name} {item_desc}"

        for ingredient in searchable_ingredients:
            # Use word boundary to avoid partial matches
            if re.search(rf'\b{re.escape(ingredient)}\b', combined_text):
                if item not in ingredient_to_items[ingredient]:
                    ingredient_to_items[ingredient].append(item)

    # ========================================
    # Share results between aliases and canonical names
    # ========================================
    for alias, canonical in alias_to_canonical.items():
        if canonical in ingredient_to_items and alias not in ingredient_to_items:
            ingredient_to_items[alias] = ingredient_to_items[canonical]
        elif alias in ingredient_to_items and canonical not in ingredient_to_items:
            ingredient_to_items[canonical] = ingredient_to_items[alias]

    # Remove empty entries and convert to regular dict
    return {k: v for k, v in ingredient_to_items.items() if v}


def build_item_keywords(db: Session) -> dict[str, str]:
    """
    Build a keyword-to-item-type-slug mapping from ItemType aliases.

    This maps user input keywords like "latte", "cappuccino", "bagels"
    to their canonical item type slugs like "coffee", "bagel".

    Returns:
        Dict mapping lowercase keywords to item type slugs.
        Example: {"latte": "coffee", "lattes": "coffee", "cappuccino": "coffee"}
    """
    keyword_to_slug: dict[str, str] = {}

    item_types = db.query(ItemType).all()
    for it in item_types:
        # Add the slug and display_name as keywords
        keyword_to_slug[it.slug.lower()] = it.slug
        if it.display_name:
            keyword_to_slug[it.display_name.lower()] = it.slug

        # Add aliases from the child table (now a list)
        for alias in it.aliases:
            alias = normalize_text(alias)
            if alias:
                keyword_to_slug[alias] = it.slug

    return keyword_to_slug


def build_item_types_data(
    db: Session,
    store_id: str | None = None,
    preloaded_config_status: dict[int, dict[str, Any]] | None = None,
    preloaded_global_options: dict[int, list] | None = None,
) -> dict[str, Any]:
    """
    Build generic item type data including all attributes and options.

    This provides the LLM with structured information about configurable items
    that goes beyond the hardcoded sandwich attributes.

    Uses ItemTypeGlobalAttribute (links to GlobalAttribute) for configuring
    item type options.

    Args:
        db: Database session
        store_id: Optional store ID for availability filtering
        preloaded_config_status: Pre-loaded config status from preload_item_type_config_status()
        preloaded_global_options: Pre-loaded global options from preload_global_attribute_options()

    Returns:
        Dict mapping item type slugs to their attribute configurations
    """
    result = {}

    # Use pre-loaded data if available, otherwise load (for backward compatibility)
    if preloaded_config_status is None:
        preloaded_config_status = preload_item_type_config_status(db)
    if preloaded_global_options is None:
        preloaded_global_options = preload_global_attribute_options(db)

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

        attributes = []

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

            # Build options with proper slug/display_name derivation from linked ingredient
            option_dicts = []
            for opt in options:
                # Derive slug and display_name from ingredient when linked
                opt_slug = opt.ingredient.slug if opt.ingredient else opt.slug
                opt_display_name = opt.ingredient.name if opt.ingredient else opt.display_name
                opt_ingredient_category = opt.ingredient.category if opt.ingredient else None

                # Skip options with NULL slug (shouldn't happen with proper data)
                if not opt_slug:
                    continue

                option_dicts.append({
                    "slug": opt_slug,
                    "display_name": opt_display_name or opt_slug,
                    "price_modifier": opt.price_modifier,
                    "is_default": opt.is_default,
                    "is_available": opt.is_available,
                    "ingredient_category": opt_ingredient_category,
                })

            attr_data = {
                "slug": global_attr.slug,
                "display_name": global_attr.display_name,
                "input_type": global_attr.input_type,
                "is_required": link.is_required,
                "allow_none": link.allow_none,
                "ask_in_conversation": link.ask_in_conversation,
                "question_text": global_attr.question_text,
                "offer_question_text": global_attr.offer_question_text,
                "is_global": True,  # Flag to indicate this is from global attributes
                "options": option_dicts,
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


def build_modifier_categories(db: Session) -> dict[str, Any]:
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
    # Pre-load all available ingredients once to avoid N+1 queries in the loop
    all_available_ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.is_available == True)  # noqa: E712
        .order_by(Ingredient.category, Ingredient.name)
        .all()
    )
    ingredients_by_category: dict[str, list[str]] = {}
    for ing in all_available_ingredients:
        if ing.category:
            ingredients_by_category.setdefault(ing.category, []).append(ing.name)

    categories = db.query(ModifierCategory).all()

    keyword_to_category: dict[str, str] = {}
    category_data: dict[str, dict[str, Any]] = {}

    for cat in categories:
        # Build keyword mappings from aliases (now a list from child table)
        for alias in cat.aliases:
            alias = normalize_text(alias)
            if alias:
                keyword_to_category[alias] = cat.slug

        # Also add the slug itself as a keyword (e.g., "syrups" -> "syrups")
        keyword_to_category[cat.slug] = cat.slug

        # Build category data
        cat_info: dict[str, Any] = {
            "display_name": cat.display_name,
            "description": cat.description,
            "prompt_suffix": cat.prompt_suffix,
        }

        # For database-backed categories, use pre-loaded ingredients by category
        if cat.loads_from_ingredients and cat.ingredient_category:
            cat_info["options"] = ingredients_by_category.get(cat.ingredient_category, [])

            # Build description dynamically if not set
            if not cat.description and cat_info["options"]:
                options_list = ", ".join(cat_info["options"])
                cat_info["description"] = f"For {cat.display_name.lower()}, we have {options_list}."

        category_data[cat.slug] = cat_info

    return {
        "keyword_to_category": keyword_to_category,
        "categories": category_data,
    }


def build_neighborhood_zip_codes(db: Session) -> dict[str, list[str]]:
    """
    Build a neighborhood-to-zip-codes mapping from the database.

    Used for delivery zone lookups when customers specify a neighborhood
    instead of a zip code.

    Returns:
        Dict mapping lowercase neighborhood names to lists of zip codes.
        Example: {"tribeca": ["10007", "10013", "10282"], "uws": ["10023", "10024", "10025"]}
    """
    neighborhoods = db.query(NeighborhoodZipCode).all()

    result: dict[str, list[str]] = {}
    for n in neighborhoods:
        result[n.neighborhood.lower()] = n.zip_codes or []

    return result


def build_item_descriptions(db: Session) -> dict[str, str]:
    """
    Build an item-name-to-description mapping from menu items.

    Used for answering "what's on the X" questions without hardcoded descriptions.

    Returns:
        Dict mapping lowercase item names to descriptions.
        Example: {"the classic bec": "Two Eggs, Applewood Smoked Bacon, and Cheddar"}
    """
    # Get all menu items with descriptions
    items = db.query(MenuItem).filter(MenuItem.description.isnot(None)).all()

    result: dict[str, str] = {}
    for item in items:
        name_lower = item.name.lower()
        result[name_lower] = item.description

        # Also add without "the " prefix for easier matching
        if name_lower.startswith("the "):
            result[name_lower[4:]] = item.description

    return result


def build_company_info(db: Session) -> dict[str, Any]:
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
    company = get_company(db)

    if not company:
        return {}

    return {
        "corporate_email": company.corporate_email,
        "corporate_phone": company.corporate_phone,
        "instagram_handle": company.instagram_handle,
        "feedback_form_url": company.feedback_form_url,
    }
