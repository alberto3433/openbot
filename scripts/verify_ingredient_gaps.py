#!/usr/bin/env python3
"""
Verify Ingredient Gaps Script

This script analyzes default_config values in menu_items.extra_metadata
and compares them against actual ingredients + aliases in the database.

Run: python scripts/verify_ingredient_gaps.py

Output:
- List of default_config values that have matching ingredients
- List of default_config values that are MISSING from ingredients table
- Summary statistics
"""

import json
import os
import sys
from collections import defaultdict
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from orderbot.models import MenuItem, Ingredient, IngredientAlias


def get_db_session():
    """Create a database session using DATABASE_URL."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()


def extract_default_config_values(db) -> dict[str, list[dict[str, Any]]]:
    """
    Extract all unique values from default_config in menu_items.

    Returns:
        Dict mapping value -> list of menu items that use this value
        Example: {"Nova Scotia Salmon": [{"id": 1, "name": "Classic Lox"}]}
    """
    menu_items = db.query(MenuItem).filter(MenuItem.extra_metadata.isnot(None)).all()

    # Track value -> list of menu items
    value_to_items: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # Fields to skip (not ingredients)
    skip_fields = {"toasted", "side_options", "iced", "size"}

    for item in menu_items:
        try:
            meta = json.loads(item.extra_metadata) if isinstance(item.extra_metadata, str) else item.extra_metadata
            default_config = meta.get("default_config", {})

            if not default_config:
                continue

            item_info = {"id": item.id, "name": item.name, "item_type": item.item_type.slug if item.item_type else None}

            for field, value in default_config.items():
                # Skip non-ingredient fields
                if field in skip_fields:
                    continue

                # Skip boolean values
                if isinstance(value, bool):
                    continue

                # Handle list values (extras, toppings, etc.)
                if isinstance(value, list):
                    for v in value:
                        if isinstance(v, str) and v.strip():
                            value_to_items[v.strip()].append({**item_info, "field": field})
                        elif isinstance(v, dict) and "name" in v:
                            value_to_items[v["name"].strip()].append({**item_info, "field": field})

                # Handle string values
                elif isinstance(value, str) and value.strip():
                    value_to_items[value.strip()].append({**item_info, "field": field})

                # Handle dict values with name key
                elif isinstance(value, dict) and "name" in value:
                    value_to_items[value["name"].strip()].append({**item_info, "field": field})

        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Could not parse extra_metadata for item {item.id} ({item.name}): {e}")

    return dict(value_to_items)


def build_ingredient_lookup(db) -> dict[str, int]:
    """
    Build a case-insensitive lookup of ingredient names and aliases to ingredient IDs.

    Returns:
        Dict mapping lowercase name/alias -> ingredient_id
    """
    lookup: dict[str, int] = {}

    # Add ingredient names
    ingredients = db.query(Ingredient).all()
    for ing in ingredients:
        lookup[ing.name.lower()] = ing.id
        # Also add slug
        if ing.slug:
            lookup[ing.slug.lower()] = ing.id

    # Add aliases
    aliases = db.query(IngredientAlias).all()
    for alias in aliases:
        lookup[alias.alias.lower()] = alias.ingredient_id

    return lookup


def find_ingredient_match(value: str, lookup: dict[str, int]) -> int | None:
    """
    Try to find a matching ingredient for a value.

    Tries exact match first, then normalized versions.
    """
    value_lower = value.lower().strip()

    # Exact match
    if value_lower in lookup:
        return lookup[value_lower]

    # Try without common prefixes/suffixes
    # e.g., "Plain Cream Cheese" might match "Plain"
    # But we want exact matches for safety

    return None


def categorize_missing_ingredients(missing_values: dict[str, list[dict]]) -> dict[str, list[str]]:
    """
    Categorize missing ingredients by likely category based on field name.

    Returns:
        Dict mapping category -> list of missing values
    """
    categories: dict[str, list[str]] = defaultdict(list)

    # Map field names to likely ingredient categories
    field_to_category = {
        "protein": "protein",
        "spread": "spread",
        "cheese": "cheese",
        "bread": "bread",
        "extras": "topping",
        "toppings": "topping",
        "sauce": "sauce",
        "sauces": "sauce",
        "vegetable": "topping",
        "fish": "protein",
        "meat": "protein",
    }

    for value, items in missing_values.items():
        # Get the most common field for this value
        fields = [item.get("field", "unknown") for item in items]
        most_common_field = max(set(fields), key=fields.count)

        category = field_to_category.get(most_common_field, "unknown")
        if value not in categories[category]:
            categories[category].append(value)

    return dict(categories)


def main():
    print("=" * 70)
    print("INGREDIENT GAPS VERIFICATION SCRIPT")
    print("=" * 70)
    print()

    db = get_db_session()

    # Step 1: Extract all default_config values
    print("Step 1: Extracting values from default_config...")
    config_values = extract_default_config_values(db)
    print(f"  Found {len(config_values)} unique values across menu items")
    print()

    # Step 2: Build ingredient lookup
    print("Step 2: Building ingredient lookup from database...")
    ingredient_lookup = build_ingredient_lookup(db)
    print(f"  Found {len(ingredient_lookup)} ingredient names/aliases")
    print()

    # Step 3: Match values to ingredients
    print("Step 3: Matching values to ingredients...")
    matched: dict[str, tuple[int, list[dict]]] = {}  # value -> (ingredient_id, items)
    missing: dict[str, list[dict]] = {}  # value -> items

    for value, items in config_values.items():
        ingredient_id = find_ingredient_match(value, ingredient_lookup)
        if ingredient_id:
            matched[value] = (ingredient_id, items)
        else:
            missing[value] = items

    print(f"  Matched: {len(matched)} values")
    print(f"  Missing: {len(missing)} values")
    print()

    # Step 4: Report matched values
    print("-" * 70)
    print("MATCHED VALUES (have corresponding ingredients)")
    print("-" * 70)
    for value, (ing_id, items) in sorted(matched.items()):
        item_count = len(items)
        print(f"  [OK] '{value}' -> ingredient_id={ing_id} (used by {item_count} items)")
    print()

    # Step 5: Report missing values
    print("-" * 70)
    print("MISSING VALUES (need ingredients to be created)")
    print("-" * 70)
    if missing:
        # Group by category
        categorized = categorize_missing_ingredients(missing)

        for category, values in sorted(categorized.items()):
            print(f"\n  [{category.upper()}]")
            for value in sorted(values):
                items = missing[value]
                item_names = [f"{item['name']}" for item in items[:3]]
                more = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
                print(f"    [MISSING] '{value}' - used by: {', '.join(item_names)}{more}")
    else:
        print("  All values have matching ingredients!")
    print()

    # Step 6: Summary statistics
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Total unique values in default_config: {len(config_values)}")
    print(f"  Values with matching ingredients:      {len(matched)} ({100*len(matched)//len(config_values) if config_values else 0}%)")
    print(f"  Values MISSING ingredients:            {len(missing)} ({100*len(missing)//len(config_values) if config_values else 0}%)")
    print()

    if missing:
        print("Next step: Create migration to add missing ingredients before")
        print("creating the menu_item_ingredients junction table.")
        print()

        # Output SQL-ready format for migration
        print("-" * 70)
        print("INGREDIENTS TO CREATE (for migration)")
        print("-" * 70)
        categorized = categorize_missing_ingredients(missing)
        for category, values in sorted(categorized.items()):
            print(f"\n# {category.upper()}")
            for value in sorted(values):
                slug = value.lower().replace(" ", "_").replace("-", "_").replace("'", "")
                slug = "".join(c for c in slug if c.isalnum() or c == "_")
                print(f'("{slug}", "{value}", "{category}"),')

    db.close()

    # Return exit code based on gaps
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
