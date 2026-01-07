"""Link egg_sandwich spreads to ingredients table

Revision ID: t7u8v9w0x1y2
Revises: s6t7u8v9w0x1
Create Date: 2025-01-07

This migration:
1. Adds missing spread ingredients (Chipotle Cream Cheese, Lox Cream Cheese,
   Olive Pimento Cream Cheese)
2. Creates item_type_ingredients links for egg_sandwich spreads
3. Updates egg_sandwich spread attribute to use loads_from_ingredients

Pricing for egg_sandwich is lower than bagel since it's a small portion add-on.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 't7u8v9w0x1y2'
down_revision = 's6t7u8v9w0x1'
branch_labels = None
depends_on = None


# New spread ingredients to add
# Format: (name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_SPREAD_INGREDIENTS = [
    ('Chipotle Cream Cheese', False, True, True, False),
    ('Lox Cream Cheese', False, False, True, False),  # Contains fish
    ('Olive Pimento Cream Cheese', False, True, True, False),
]

# Spread configuration for egg_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
# Pricing based on current attribute_options (lower than bagel spreads)
EGG_SANDWICH_SPREAD_CONFIG = [
    ('Plain Cream Cheese', 0.80, 1, False),
    ('Scallion Cream Cheese', 0.90, 2, False),
    ('Vegetable Cream Cheese', 0.90, 3, False),
    ('Lox Cream Cheese', 0.90, 4, False),
    ('Maple Raisin Walnut Cream Cheese', 0.90, 5, False),  # "Walnut Raisin" in options
    ('Jalapeño Cream Cheese', 0.90, 6, False),
    ('Honey Walnut Cream Cheese', 0.90, 7, False),
    ('Strawberry Cream Cheese', 0.90, 8, False),
    ('Blueberry Cream Cheese', 0.90, 9, False),
    ('Olive Pimento Cream Cheese', 0.90, 10, False),
    ('Nova Scotia Cream Cheese', 1.85, 11, False),
    ('Chipotle Cream Cheese', 1.85, 12, False),
    ('Truffle Cream Cheese', 1.85, 13, False),
    ('Tofu Cream Cheese', 0.90, 14, False),  # "Plain Tofu" in options
    ('Tofu Scallion Cream Cheese', 0.90, 15, False),  # "Scallion Tofu" in options
    ('Tofu Vegetable Cream Cheese', 0.90, 16, False),  # "Veggie Tofu" in options
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new spread ingredients
    for name, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_SPREAD_INGREDIENTS:
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
                    VALUES (:name, 'spread', 'portion', true, 0.0, true,
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

    # Step 2: Link spreads to egg_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        _create_spread_links(conn, egg_sandwich_id, EGG_SANDWICH_SPREAD_CONFIG)
        _update_spread_attribute(conn, egg_sandwich_id)


def _create_spread_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for spreads."""
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'spread'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'spread', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_spread_attribute(conn, item_type_id: int) -> None:
    """Update spread attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'spread'
            WHERE item_type_id = :item_type_id AND slug = 'spread'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert spread attribute and remove links for egg_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'"))
    row = result.fetchone()
    if row:
        egg_sandwich_id = row[0]
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'spread'
            """),
            {"item_type_id": egg_sandwich_id}
        )
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'spread'
            """),
            {"item_type_id": egg_sandwich_id}
        )

    # Step 2: Remove newly added spread ingredients
    for name, *_ in NEW_SPREAD_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name AND category = 'spread'"),
            {"name": name}
        )
