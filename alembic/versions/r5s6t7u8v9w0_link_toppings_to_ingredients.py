"""Link toppings to ingredients table

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2025-01-07

This migration:
1. Adds missing topping ingredients (Roasted Peppers, Jalapeno, Sauteed Mushrooms,
   Sauteed Onions, Hash Browns, Breakfast Potato Latke)
2. Creates item_type_ingredients links for bagel and egg_sandwich
3. Updates topping/toppings attributes to use loads_from_ingredients

Pricing per item type based on current attribute_options values.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'r5s6t7u8v9w0'
down_revision = 'q4r5s6t7u8v9'
branch_labels = None
depends_on = None


# New topping ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_TOPPING_INGREDIENTS = [
    ('Roasted Peppers', 'topping', True, True, True, True),
    ('Jalapeno', 'topping', True, True, True, True),
    ('Sauteed Mushrooms', 'topping', True, True, True, True),
    ('Sauteed Onions', 'topping', True, True, True, True),
    ('Hash Browns', 'topping', True, True, False, True),  # May contain gluten
    ('Breakfast Potato Latke', 'topping', True, True, False, True),  # Contains gluten
]

# Topping configuration per item type
# Format: (ingredient_name, price_modifier, display_order, is_default)
BAGEL_TOPPING_CONFIG = [
    ('Lettuce', 0.00, 1, False),
    ('Tomato', 0.50, 2, False),
    ('Onion', 0.50, 3, False),
    ('Cucumber', 0.25, 4, False),
    ('Pickles', 0.25, 5, False),
    ('Spinach', 0.50, 6, False),
    ('Capers', 0.75, 7, False),
    ('Mushrooms', 0.50, 8, False),
    ('Green Pepper', 0.50, 9, False),
    ('Red Pepper', 0.50, 10, False),
    ('Avocado', 2.00, 11, False),  # Uses existing Avocado from protein category
]

EGG_SANDWICH_TOPPING_CONFIG = [
    ('Lettuce', 0.60, 1, False),
    ('Tomato', 1.00, 2, False),
    ('Onion', 0.75, 3, False),
    ('Red Onion', 0.75, 4, False),
    ('Cucumber', 0.75, 5, False),
    ('Pickles', 0.75, 6, False),
    ('Spinach', 1.00, 7, False),
    ('Capers', 1.00, 8, False),
    ('Roasted Peppers', 1.00, 9, False),
    ('Jalapeno', 0.75, 10, False),
    ('Sauteed Mushrooms', 1.50, 11, False),
    ('Sauteed Onions', 1.00, 12, False),
    ('Hash Browns', 2.50, 13, False),
    ('Breakfast Potato Latke', 2.80, 14, False),
    ('Avocado', 3.50, 15, False),
    ('Hot Sauce', 0.00, 16, False),  # Uses existing Hot Sauce from sauce category
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new topping ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_TOPPING_INGREDIENTS:
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

    # Step 2: Link toppings to bagel item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row:
        bagel_id = row[0]
        _create_topping_links(conn, bagel_id, BAGEL_TOPPING_CONFIG)
        _update_topping_attribute(conn, bagel_id, 'topping')

    # Step 3: Link toppings to egg_sandwich item type
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        _create_topping_links(conn, egg_sandwich_id, EGG_SANDWICH_TOPPING_CONFIG)
        _update_topping_attribute(conn, egg_sandwich_id, 'toppings')


def _create_topping_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for toppings."""
    for ingredient_name, price_modifier, display_order, is_default in config:
        # Get ingredient id (search across categories since some toppings may be in other categories)
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'topping'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'topping', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_topping_attribute(conn, item_type_id: int, attr_slug: str) -> None:
    """Update topping attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'topping'
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": attr_slug}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert topping attributes and remove links for bagel
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row:
        bagel_id = row[0]
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'topping'
            """),
            {"item_type_id": bagel_id}
        )
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'topping'
            """),
            {"item_type_id": bagel_id}
        )

    # Step 2: Revert topping attributes and remove links for egg_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'toppings'
            """),
            {"item_type_id": egg_sandwich_id}
        )
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'topping'
            """),
            {"item_type_id": egg_sandwich_id}
        )

    # Step 3: Remove newly added topping ingredients
    for name, *_ in NEW_TOPPING_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
