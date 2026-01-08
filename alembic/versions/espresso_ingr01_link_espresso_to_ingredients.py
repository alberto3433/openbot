"""Link espresso shots attribute to ingredients table

Revision ID: espresso_ingr01
Revises: sized_bev_ingr01
Create Date: 2026-01-07

This migration:
1. Adds espresso shot count ingredients (Single, Double, Triple, Quad)
2. Creates item_type_ingredients links for shots
3. Updates espresso shots attribute to use loads_from_ingredients

Note: milk, sweetener, syrup attributes were already migrated.
Note: extra_shot and decaf are boolean fields without options, not ingredient-based.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'espresso_ingr01'
down_revision = 'sized_bev_ingr01'
branch_labels = None
depends_on = None


# New espresso shot ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_SHOTS_INGREDIENTS = [
    ('Single Shot', 'espresso_shots', True, True, True, True),
    ('Double Shot Espresso', 'espresso_shots', True, True, True, True),  # Different from "Double Shot" extra
    ('Triple Shot Espresso', 'espresso_shots', True, True, True, True),  # Different from "Triple Shot" extra
    ('Quad Shot', 'espresso_shots', True, True, True, True),
]


# Shots configuration for espresso
# Format: (ingredient_name, price_modifier, display_order, is_default)
ESPRESSO_SHOTS_CONFIG = [
    ('Single Shot', 0.00, 1, True),
    ('Double Shot Espresso', 0.75, 2, False),
    ('Triple Shot Espresso', 1.50, 3, False),
    ('Quad Shot', 2.25, 4, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new shot ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_SHOTS_INGREDIENTS:
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, base_price, is_available,
                                           is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                    VALUES (:name, :category, 'portion', false, 0.0, true,
                            :is_vegan, :is_vegetarian, :is_gluten_free, :is_dairy_free, true)
                """),
                {
                    "name": name,
                    "category": category,
                    "is_vegan": is_vegan,
                    "is_vegetarian": is_vegetarian,
                    "is_gluten_free": is_gluten_free,
                    "is_dairy_free": is_dairy_free,
                }
            )
            print(f"Added espresso_shots ingredient: {name}")

    # Step 2: Get espresso item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'espresso'"))
    row = result.fetchone()
    if not row:
        print("Warning: espresso item type not found, skipping")
        return

    espresso_id = row[0]
    print(f"Found espresso item_type_id: {espresso_id}")

    # Step 3: Create links for shots attribute
    _create_ingredient_links(conn, espresso_id, 'shots', ESPRESSO_SHOTS_CONFIG)

    # Step 4: Update shots attribute to use loads_from_ingredients
    _update_attribute(conn, espresso_id, 'shots', 'shots')


def _create_ingredient_links(conn, item_type_id: int, ingredient_group: str, config: list) -> None:
    """Create item_type_ingredients links for a group."""
    created = 0
    for ingredient_name, price_modifier, display_order, is_default in config:
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": ingredient_name}
        )
        row = result.fetchone()
        if row is None:
            print(f"Warning: Ingredient '{ingredient_name}' not found, skipping")
            continue
        ingredient_id = row[0]

        result = conn.execute(
            text("""
                SELECT id FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = :group
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id, "group": ingredient_group}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, :group, :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "group": ingredient_group,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )
            created += 1

    print(f"Created {created} {ingredient_group} links for espresso")


def _update_attribute(conn, item_type_id: int, attr_slug: str, ingredient_group: str) -> None:
    """Update attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = :group
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": attr_slug, "group": ingredient_group}
    )
    print(f"Updated {attr_slug} attribute to use ingredient_group={ingredient_group}")


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert attribute and remove links for espresso
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'espresso'"))
    row = result.fetchone()
    if row:
        espresso_id = row[0]

        # Revert attribute
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'shots'
            """),
            {"item_type_id": espresso_id}
        )

        # Remove links
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'shots'
            """),
            {"item_type_id": espresso_id}
        )

    # Step 2: Remove newly added shot ingredients
    for name, *_ in NEW_SHOTS_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
