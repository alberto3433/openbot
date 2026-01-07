"""Link breads to ingredients table

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2025-01-07

This migration:
1. Adds missing bread ingredients (Rainbow Bagel, French Toast Bagel, Sun Dried
   Tomato Bagel, Jalapeno Cheddar Bagel, Flagel, GF Sesame Bagel, GF Cinnamon
   Raisin Bagel, Croissant, Wrap, GF Wrap, Artisan Bread)
2. Creates item_type_ingredients links for egg_sandwich, salad_sandwich, and
   spread_sandwich
3. Updates bread attributes to use loads_from_ingredients

Pricing per item type based on current attribute_options values.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 's6t7u8v9w0x1'
down_revision = 'r5s6t7u8v9w0'
branch_labels = None
depends_on = None


# New bread ingredients to add
# Format: (name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_BREAD_INGREDIENTS = [
    ('Rainbow Bagel', True, True, False, True),
    ('French Toast Bagel', False, True, False, False),  # Contains egg/dairy
    ('Sun Dried Tomato Bagel', True, True, False, True),
    ('Jalapeno Cheddar Bagel', False, True, False, False),  # Contains cheese
    ('Flagel', True, True, False, True),
    ('Gluten Free Sesame Bagel', True, True, True, True),
    ('Gluten Free Cinnamon Raisin Bagel', True, True, True, True),
    ('Croissant', False, True, False, False),  # Contains butter
    ('Wrap', True, True, False, True),
    ('Gluten Free Wrap', True, True, True, True),
    ('Artisan Bread', True, True, False, True),
]

# Bread configuration for egg_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
EGG_SANDWICH_BREAD_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),
    ('Everything Bagel', 0.00, 2, False),
    ('Sesame Bagel', 0.00, 3, False),
    ('Poppy Bagel', 0.00, 4, False),
    ('Onion Bagel', 0.00, 5, False),
    ('Salt Bagel', 0.00, 6, False),
    ('Garlic Bagel', 0.00, 7, False),
    ('Pumpernickel Bagel', 0.00, 8, False),
    ('Whole Wheat Bagel', 0.00, 9, False),
    ('Egg Bagel', 0.00, 10, False),
    ('Rainbow Bagel', 0.00, 11, False),
    ('French Toast Bagel', 0.00, 12, False),
    ('Sun Dried Tomato Bagel', 0.00, 13, False),
    ('Multigrain Bagel', 0.00, 14, False),
    ('Cinnamon Raisin Bagel', 0.00, 15, False),
    ('Asiago Bagel', 0.00, 16, False),
    ('Jalapeno Cheddar Bagel', 0.00, 17, False),
    ('Bialy', 0.00, 18, False),
    ('Flagel', 0.00, 19, False),
    ('Gluten Free Bagel', 1.85, 20, False),
    ('Gluten Free Everything Bagel', 1.85, 21, False),
    ('Gluten Free Sesame Bagel', 1.85, 22, False),
    ('Gluten Free Cinnamon Raisin Bagel', 1.85, 23, False),
    ('Croissant', 1.80, 24, False),
    ('Wrap', 0.00, 25, False),
    ('Gluten Free Wrap', 1.00, 26, False),
]

# Bread configuration for salad_sandwich
SALAD_SANDWICH_BREAD_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),
    ('Everything Bagel', 0.00, 2, False),
    ('Sesame Bagel', 0.00, 3, False),
    ('Poppy Bagel', 0.00, 4, False),
    ('Onion Bagel', 0.00, 5, False),
    ('Salt Bagel', 0.00, 6, False),
    ('Garlic Bagel', 0.00, 7, False),
    ('Pumpernickel Bagel', 0.00, 8, False),
    ('Whole Wheat Bagel', 0.25, 9, False),
    ('Cinnamon Raisin Bagel', 0.25, 10, False),
    ('Bialy', 0.00, 11, False),
    ('Wrap', 0.00, 12, False),
    ('Artisan Bread', 0.50, 13, False),
]

# Bread configuration for spread_sandwich (same as salad_sandwich)
SPREAD_SANDWICH_BREAD_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),
    ('Everything Bagel', 0.00, 2, False),
    ('Sesame Bagel', 0.00, 3, False),
    ('Poppy Bagel', 0.00, 4, False),
    ('Onion Bagel', 0.00, 5, False),
    ('Salt Bagel', 0.00, 6, False),
    ('Garlic Bagel', 0.00, 7, False),
    ('Pumpernickel Bagel', 0.00, 8, False),
    ('Whole Wheat Bagel', 0.25, 9, False),
    ('Cinnamon Raisin Bagel', 0.25, 10, False),
    ('Bialy', 0.00, 11, False),
    ('Wrap', 0.00, 12, False),
    ('Artisan Bread', 0.50, 13, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new bread ingredients
    for name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_BREAD_INGREDIENTS:
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
                    VALUES (:name, 'bread', 'piece', true, 0.0, true,
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

    # Step 2: Link breads to egg_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        _create_bread_links(conn, egg_sandwich_id, EGG_SANDWICH_BREAD_CONFIG)
        _update_bread_attribute(conn, egg_sandwich_id)

    # Step 3: Link breads to salad_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'salad_sandwich'"))
    row = result.fetchone()
    if row:
        salad_sandwich_id = row[0]
        _create_bread_links(conn, salad_sandwich_id, SALAD_SANDWICH_BREAD_CONFIG)
        _update_bread_attribute(conn, salad_sandwich_id)

    # Step 4: Link breads to spread_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'spread_sandwich'"))
    row = result.fetchone()
    if row:
        spread_sandwich_id = row[0]
        _create_bread_links(conn, spread_sandwich_id, SPREAD_SANDWICH_BREAD_CONFIG)
        _update_bread_attribute(conn, spread_sandwich_id)


def _create_bread_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for breads."""
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'bread'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'bread', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_bread_attribute(conn, item_type_id: int) -> None:
    """Update bread attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'bread'
            WHERE item_type_id = :item_type_id AND slug = 'bread'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert bread attributes and remove links for all item types
    for item_type_slug in ['egg_sandwich', 'salad_sandwich', 'spread_sandwich']:
        result = conn.execute(
            text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": item_type_slug}
        )
        row = result.fetchone()
        if row:
            item_type_id = row[0]
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = 'bread'
                """),
                {"item_type_id": item_type_id}
            )
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = 'bread'
                """),
                {"item_type_id": item_type_id}
            )

    # Step 2: Remove newly added bread ingredients
    for name, *_ in NEW_BREAD_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name AND category = 'bread'"),
            {"name": name}
        )
