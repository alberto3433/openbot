"""Link cheeses to ingredients table

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2025-01-07

This migration:
1. Adds missing cheese ingredients (Havarti, Fresh Mozzarella, Feta)
2. Creates item_type_ingredients links for bagel, egg_sandwich, and omelette
3. Updates cheese attributes to use loads_from_ingredients

Pricing per item type:
- Bagel: $0.75 for all cheeses (add-on to bagel)
- Egg Sandwich: $1.50 for all cheeses (extra cheese upcharge)
- Omelette: $0.00 for all cheeses (included in omelette price)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'q4r5s6t7u8v9'
down_revision = 'p3q4r5s6t7u8'
branch_labels = None
depends_on = None


# New cheese ingredients to add
# Format: (name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_CHEESE_INGREDIENTS = [
    ('Havarti Cheese', False, True, True, False),
    ('Fresh Mozzarella Cheese', False, True, True, False),
    ('Feta Cheese', False, True, True, False),
]

# Cheese configuration per item type
# Format: (ingredient_name, price_modifier, display_order, is_default)
BAGEL_CHEESE_CONFIG = [
    ('American Cheese', 0.75, 1, False),
    ('Swiss Cheese', 0.75, 2, False),
    ('Cheddar Cheese', 0.75, 3, False),
    ('Muenster Cheese', 0.75, 4, False),
    ('Provolone Cheese', 0.75, 5, False),
]

EGG_SANDWICH_CHEESE_CONFIG = [
    ('American Cheese', 1.50, 1, False),
    ('Swiss Cheese', 1.50, 2, False),
    ('Cheddar Cheese', 1.50, 3, False),
    ('Muenster Cheese', 1.50, 4, False),
    ('Provolone Cheese', 1.50, 5, False),
    ('Havarti Cheese', 1.50, 6, False),
    ('Fresh Mozzarella Cheese', 1.50, 7, False),
    ('Pepper Jack Cheese', 1.50, 8, False),
]

OMELETTE_CHEESE_CONFIG = [
    ('American Cheese', 0.00, 1, False),
    ('Swiss Cheese', 0.00, 2, False),
    ('Cheddar Cheese', 0.00, 3, False),
    ('Pepper Jack Cheese', 0.00, 4, False),
    ('Feta Cheese', 0.00, 5, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new cheese ingredients
    for name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_CHEESE_INGREDIENTS:
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
                    VALUES (:name, 'cheese', 'slice', true, 0.0, true,
                            :is_vegan, :is_vegetarian, :is_gluten_free, :is_dairy_free, true)
                """),
                {
                    "name": name,
                    "is_vegan": is_vegan,
                    "is_vegetarian": is_vegetarian,
                    "is_gluten_free": is_gluten_free,
                    "is_dairy_free": is_dairy_free,
                }
            )

    # Step 2: Link cheeses to bagel item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row:
        bagel_id = row[0]
        _create_cheese_links(conn, bagel_id, BAGEL_CHEESE_CONFIG)
        _update_cheese_attribute(conn, bagel_id)

    # Step 3: Link cheeses to egg_sandwich item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        _create_cheese_links(conn, egg_sandwich_id, EGG_SANDWICH_CHEESE_CONFIG)
        _update_cheese_attribute(conn, egg_sandwich_id)

    # Step 4: Link cheeses to omelette item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        _create_cheese_links(conn, omelette_id, OMELETTE_CHEESE_CONFIG)
        _update_cheese_attribute(conn, omelette_id)


def _create_cheese_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for cheeses."""
    for ingredient_name, price_modifier, display_order, is_default in config:
        # Get ingredient id
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'cheese'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'cheese', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_cheese_attribute(conn, item_type_id: int) -> None:
    """Update cheese attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'cheese'
            WHERE item_type_id = :item_type_id AND slug = 'cheese'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert cheese attributes for all item types
    for item_type_slug in ['bagel', 'egg_sandwich', 'omelette']:
        result = conn.execute(
            text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": item_type_slug}
        )
        row = result.fetchone()
        if row:
            item_type_id = row[0]
            # Revert attribute
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = 'cheese'
                """),
                {"item_type_id": item_type_id}
            )
            # Remove cheese links
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = 'cheese'
                """),
                {"item_type_id": item_type_id}
            )

    # Step 2: Remove newly added cheese ingredients
    for name, *_ in NEW_CHEESE_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name AND category = 'cheese'"),
            {"name": name}
        )
