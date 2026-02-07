"""Menu index orchestrator - main entry point for building menu indexes."""

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session, joinedload

from orderbot.db.models import (
    Ingredient,
    IngredientStoreAvailability,
    ItemType,
    MenuItem,
    MenuItemStoreAvailability,
)

from .builders import (
    build_company_info,
    build_ingredient_to_items,
    build_item_descriptions,
    build_item_keywords,
    build_item_types_data,
    build_modifier_categories,
    build_neighborhood_zip_codes,
)
from .preloaders import (
    preload_all_ingredients,
    preload_global_attribute_options,
    preload_item_type_config_status,
    preload_menu_item_ingredients,
    preload_size_prices,
)

logger = logging.getLogger(__name__)


def build_menu_index(db: Session, store_id: str | None = None) -> dict[str, Any]:
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
    preloaded_config_status = preload_item_type_config_status(db)
    preloaded_ingredients = preload_all_ingredients(db)
    preloaded_size_prices = preload_size_prices(db)
    preloaded_menu_item_ingredients = preload_menu_item_ingredients(db)

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
    index: dict[str, Any] = {
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
    # Add display name for the special signature_items key (already plural, don't re-pluralize)
    index["item_type_display_names"]["signature_items"] = "signature items"

    for item in items:
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

        # Add included ingredient categories (for pricing - skip upcharge if already included)
        # If a menu item includes cheese, selecting cheese type shouldn't upcharge
        menu_item_ingredients = preloaded_menu_item_ingredients.get(item.id, [])
        included_categories = set()
        for ing_info in menu_item_ingredients:
            if ing_info.get("ingredient_category"):
                included_categories.add(ing_info["ingredient_category"])
        if included_categories:
            item_json["included_ingredient_categories"] = list(included_categories)

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
        # NOTE: Ingredient pricing is managed via GlobalAttributeOption.price_modifier,
        # not via Ingredient.base_price (which has been removed)


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
        if unavail_ids:
            unavail_ings = db.query(Ingredient).filter(Ingredient.id.in_(unavail_ids)).all()
            unavailable_ingredients = [
                {"name": ing.name, "category": ing.category}
                for ing in unavail_ings
            ]
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
        if unavail_item_ids:
            unavail_items = (
                db.query(MenuItem)
                .options(joinedload(MenuItem.item_type))
                .filter(MenuItem.id.in_(unavail_item_ids))
                .all()
            )
            unavailable_menu_items = [
                {"name": item.name, "category": item.item_type.display_name if item.item_type else None}
                for item in unavail_items
            ]
    index["unavailable_menu_items"] = unavailable_menu_items

    # Pre-load attribute and option data for build_item_types_data
    preloaded_global_options = preload_global_attribute_options(db)

    # Add generic item type data for configurable items
    index["item_types"] = build_item_types_data(
        db,
        store_id,
        preloaded_config_status,
        preloaded_global_options,
    )

    # Build modifier categories for answering questions like "what sweeteners do you have?"
    index["modifier_categories"] = build_modifier_categories(db)

    # Build item keyword mappings for modifier inquiry parsing
    # Maps keywords like "latte", "cappuccino" -> "coffee" (item type slug)
    index["item_keywords"] = build_item_keywords(db)

    # Build neighborhood to zip code mappings for delivery zone lookups
    index["neighborhood_zip_codes"] = build_neighborhood_zip_codes(db)

    # Build item descriptions mapping for "what's on" queries
    # Maps normalized item names to descriptions
    index["item_descriptions"] = build_item_descriptions(db)

    # Build ingredient-to-items mapping for ingredient-based search
    # When user says "something with chicken", this index helps find matching items
    index["ingredient_to_items"] = build_ingredient_to_items(
        index, preloaded_ingredients, preloaded_menu_item_ingredients
    )

    # Build company info for customer service inquiries
    index["company_info"] = build_company_info(db)

    return index


def get_menu_version(menu_index: dict[str, Any]) -> str:
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
