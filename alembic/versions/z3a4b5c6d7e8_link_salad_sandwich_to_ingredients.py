"""Link salad_sandwich attributes to ingredients table

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2026-01-07

This migration:
1. Adds missing salad ingredients (Baked Salmon Salad, Chicken Salad, etc.)
2. Creates item_type_ingredients links for salad and extras attributes
3. Updates salad_sandwich attributes to use loads_from_ingredients

Note: bread attribute was already migrated in a previous migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'z3a4b5c6d7e8'
down_revision = 'y2z3a4b5c6d7'
branch_labels = None
depends_on = None


# New salad ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_SALAD_INGREDIENTS = [
    ('Baked Salmon Salad', 'protein', False, False, True, True),
    ('Chicken Salad', 'protein', False, False, True, True),
    ('Cranberry Pecan Chicken Salad', 'protein', False, False, True, True),
    ('Lemon Chicken Salad', 'protein', False, False, True, True),
]


# Salad configuration for salad_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
SALAD_SANDWICH_SALAD_CONFIG = [
    ('Egg Salad', 0.00, 1, False),
    ('Tuna Salad', 0.00, 2, False),
    ('Chicken Salad', 0.00, 3, False),
    ('Whitefish Salad', 0.00, 4, False),
    ('Baked Salmon Salad', 0.00, 5, False),
    ('Lemon Chicken Salad', 0.00, 6, False),
    ('Cranberry Pecan Chicken Salad', 0.00, 7, False),
]


# Extras configuration for salad_sandwich (these are toppings)
# Format: (ingredient_name, price_modifier, display_order, is_default)
SALAD_SANDWICH_EXTRAS_CONFIG = [
    ('Lettuce', 0.50, 1, False),
    ('Tomato', 0.75, 2, False),
    ('Onion', 0.50, 3, False),
    ('Red Onion', 0.50, 4, False),
    ('Cucumber', 0.75, 5, False),
    ('Capers', 1.00, 6, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new salad ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_SALAD_INGREDIENTS:
        # Check if ingredient already exists
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, base_price, is_available,
                                           is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                    VALUES (:name, :category, 'portion', true, 0.0, true,
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
            print(f"Added ingredient: {name}")

    # Step 2: Get salad_sandwich item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'salad_sandwich'"))
    row = result.fetchone()
    if not row:
        print("Warning: salad_sandwich item type not found, skipping")
        return

    salad_sandwich_id = row[0]
    print(f"Found salad_sandwich item_type_id: {salad_sandwich_id}")

    # Step 3: Create links for salad and extras attributes
    _create_ingredient_links(conn, salad_sandwich_id, 'salad', SALAD_SANDWICH_SALAD_CONFIG)
    _create_ingredient_links(conn, salad_sandwich_id, 'extras', SALAD_SANDWICH_EXTRAS_CONFIG)

    # Step 4: Update attributes to use loads_from_ingredients
    _update_attribute(conn, salad_sandwich_id, 'salad', 'salad')
    _update_attribute(conn, salad_sandwich_id, 'extras', 'extras')


def _create_ingredient_links(conn, item_type_id: int, ingredient_group: str, config: list) -> None:
    """Create item_type_ingredients links for a group."""
    created = 0
    for ingredient_name, price_modifier, display_order, is_default in config:
        # Get ingredient id (search across all categories)
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

    print(f"Created {created} {ingredient_group} links for salad_sandwich")


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

    # Step 1: Revert attributes and remove links for salad_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'salad_sandwich'"))
    row = result.fetchone()
    if row:
        salad_sandwich_id = row[0]

        # Revert attributes
        for attr_slug in ['salad', 'extras']:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": salad_sandwich_id, "slug": attr_slug}
            )

        # Remove links
        for ingredient_group in ['salad', 'extras']:
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = :group
                """),
                {"item_type_id": salad_sandwich_id, "group": ingredient_group}
            )

    # Step 2: Remove newly added salad ingredients
    for name, *_ in NEW_SALAD_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
