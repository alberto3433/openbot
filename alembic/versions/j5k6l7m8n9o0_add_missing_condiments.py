"""Add Salt, Black Pepper, Ketchup to condiments for all sandwich types

Revision ID: j5k6l7m8n9o0
Revises: 1648e574384f
Create Date: 2026-01-09

This migration adds Salt, Black Pepper, and Ketchup as condiment options for:
- deli_sandwich
- egg_sandwich
- spread_sandwich
- fish_sandwich

These ingredients already exist in the ingredients table but were not linked
to the condiment attribute for sandwich types.
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'j5k6l7m8n9o0'
down_revision = '1648e574384f'
branch_labels = None
depends_on = None


# Condiments to add for all sandwich types
# Format: (ingredient_name, price_modifier, display_order_offset, is_default)
# display_order_offset will be added to existing max order
NEW_CONDIMENTS = [
    ('Salt', 0.00, 1, False),
    ('Black Pepper', 0.00, 2, False),
    ('Ketchup', 0.00, 3, False),
]

# Sandwich item types that should have these condiments
SANDWICH_ITEM_TYPES = [
    'deli_sandwich',
    'egg_sandwich',
    'spread_sandwich',
    'fish_sandwich',
]


def upgrade() -> None:
    conn = op.get_bind()

    for item_type_slug in SANDWICH_ITEM_TYPES:
        # Get item type ID
        result = conn.execute(
            text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": item_type_slug}
        )
        row = result.fetchone()
        if not row:
            print(f"Warning: item_type '{item_type_slug}' not found, skipping")
            continue

        item_type_id = row[0]

        # Get max display_order for existing condiments
        result = conn.execute(
            text("""
                SELECT COALESCE(MAX(display_order), 0) FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'condiment'
            """),
            {"item_type_id": item_type_id}
        )
        max_order = result.fetchone()[0]

        created = 0
        for ingredient_name, price_modifier, order_offset, is_default in NEW_CONDIMENTS:
            # Get ingredient ID
            result = conn.execute(
                text("SELECT id FROM ingredients WHERE name = :name"),
                {"name": ingredient_name}
            )
            row = result.fetchone()
            if row is None:
                print(f"Warning: Ingredient '{ingredient_name}' not found, skipping")
                continue
            ingredient_id = row[0]

            # Check if link already exists
            result = conn.execute(
                text("""
                    SELECT id FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id
                    AND ingredient_id = :ingredient_id
                    AND ingredient_group = 'condiment'
                """),
                {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
            )
            if result.fetchone() is None:
                conn.execute(
                    text("""
                        INSERT INTO item_type_ingredients
                        (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                        VALUES (:item_type_id, :ingredient_id, 'condiment', :price, :order, :is_default, true)
                    """),
                    {
                        "item_type_id": item_type_id,
                        "ingredient_id": ingredient_id,
                        "price": price_modifier,
                        "order": max_order + order_offset,
                        "is_default": is_default,
                    }
                )
                created += 1

        print(f"Created {created} condiment links for {item_type_slug}")


def downgrade() -> None:
    conn = op.get_bind()

    for item_type_slug in SANDWICH_ITEM_TYPES:
        # Get item type ID
        result = conn.execute(
            text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": item_type_slug}
        )
        row = result.fetchone()
        if not row:
            continue

        item_type_id = row[0]

        # Remove the added condiment links
        for ingredient_name, *_ in NEW_CONDIMENTS:
            result = conn.execute(
                text("SELECT id FROM ingredients WHERE name = :name"),
                {"name": ingredient_name}
            )
            row = result.fetchone()
            if row is None:
                continue
            ingredient_id = row[0]

            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id
                    AND ingredient_id = :ingredient_id
                    AND ingredient_group = 'condiment'
                """),
                {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
            )

        print(f"Removed condiment links for {item_type_slug}")
