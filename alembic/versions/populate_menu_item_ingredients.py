"""Populate menu_item_ingredients from default_config

Revision ID: populate_menu_item_ingredients
Revises: create_menu_item_ingredients
Create Date: 2026-01-22

This migration reads the default_config from menu_items.extra_metadata
and populates the menu_item_ingredients junction table.

The default_config contains ingredient references like:
{
    "bread": "everything bagel",
    "protein": "nova scotia salmon",
    "extras": ["tomato", "red onion"]
}

Each value is looked up in the ingredients table (by name or alias)
and a link is created in menu_item_ingredients.
"""
import json
from alembic import op
from sqlalchemy import text


revision = 'populate_menu_item_ingredients'
down_revision = 'create_menu_item_ingredients'
branch_labels = None
depends_on = None


# Fields in default_config that are NOT ingredients
SKIP_FIELDS = {'toasted', 'side_options', 'iced', 'size', 'scooped'}


def upgrade() -> None:
    conn = op.get_bind()

    # Build ingredient lookup from names and aliases (case-insensitive)
    ingredient_lookup = {}

    # Add ingredient names
    result = conn.execute(text("SELECT id, LOWER(name) as name FROM ingredients"))
    for row in result:
        ingredient_lookup[row.name] = row.id

    # Add ingredient aliases
    result = conn.execute(text("""
        SELECT ingredient_id, LOWER(alias) as alias
        FROM ingredient_aliases
    """))
    for row in result:
        ingredient_lookup[row.alias] = row.ingredient_id

    print(f"Loaded {len(ingredient_lookup)} ingredient names/aliases")

    # Get all menu items with extra_metadata
    result = conn.execute(text("""
        SELECT id, name, extra_metadata
        FROM menu_items
        WHERE extra_metadata IS NOT NULL
    """))

    items_processed = 0
    links_created = 0
    unmatched_values = []

    for row in result:
        item_id = row.id
        item_name = row.name
        extra_metadata = row.extra_metadata

        # Parse JSON
        try:
            meta = json.loads(extra_metadata) if isinstance(extra_metadata, str) else extra_metadata
            default_config = meta.get("default_config", {})
        except (json.JSONDecodeError, TypeError):
            continue

        if not default_config:
            continue

        items_processed += 1

        # Extract ingredient values
        for field, value in default_config.items():
            if field in SKIP_FIELDS:
                continue

            # Skip boolean values
            if isinstance(value, bool):
                continue

            # Collect values to process
            values_to_link = []

            if isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and v.strip():
                        values_to_link.append(v.strip())
                    elif isinstance(v, dict) and "name" in v:
                        values_to_link.append(v["name"].strip())
            elif isinstance(value, str) and value.strip():
                values_to_link.append(value.strip())
            elif isinstance(value, dict) and "name" in value:
                values_to_link.append(value["name"].strip())

            # Look up and link each value
            for val in values_to_link:
                val_lower = val.lower()
                ingredient_id = ingredient_lookup.get(val_lower)

                if ingredient_id:
                    # Check if link already exists
                    existing = conn.execute(text("""
                        SELECT id FROM menu_item_ingredients
                        WHERE menu_item_id = :menu_item_id AND ingredient_id = :ingredient_id
                    """), {"menu_item_id": item_id, "ingredient_id": ingredient_id}).fetchone()

                    if not existing:
                        conn.execute(text("""
                            INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity)
                            VALUES (:menu_item_id, :ingredient_id, 1)
                        """), {"menu_item_id": item_id, "ingredient_id": ingredient_id})
                        links_created += 1
                else:
                    unmatched_values.append({
                        "item": item_name,
                        "field": field,
                        "value": val
                    })

    print(f"Processed {items_processed} menu items")
    print(f"Created {links_created} ingredient links")

    if unmatched_values:
        print(f"WARNING: {len(unmatched_values)} unmatched values:")
        for uv in unmatched_values:
            print(f"  - {uv['item']}: {uv['field']}='{uv['value']}'")


def downgrade() -> None:
    # Clear the junction table (it will be recreated on next upgrade)
    conn = op.get_bind()
    conn.execute(text("DELETE FROM menu_item_ingredients"))
    print("Cleared menu_item_ingredients table")
