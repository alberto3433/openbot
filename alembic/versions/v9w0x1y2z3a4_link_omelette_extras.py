"""Link omelette extras to ingredients table

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0x1y2z3
Create Date: 2025-01-07

This migration:
1. Adds missing extras ingredients (Pico de Gallo, Salsa, Sour Cream)
2. Creates item_type_ingredients links for omelette extras
3. Updates omelette extras attribute to use loads_from_ingredients

Extras are add-ons that can be added to omelettes - many are included free,
some have upcharges for premium items.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'v9w0x1y2z3a4'
down_revision = 'u8v9w0x1y2z3'
branch_labels = None
depends_on = None


# New extras ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_EXTRAS_INGREDIENTS = [
    ('Pico de Gallo', 'condiment', True, True, True, True),
    ('Salsa', 'condiment', True, True, True, True),
    ('Sour Cream', 'condiment', False, True, True, False),
]

# Extras configuration for omelette
# Format: (ingredient_name, price_modifier, display_order, is_default)
OMELETTE_EXTRAS_CONFIG = [
    # Vegetables/sides (included)
    ('Breakfast Potato Latke', 0.00, 1, False),
    ('Sauteed Onions', 0.00, 2, False),
    ('Green Pepper', 0.00, 3, False),
    ('Onion', 0.00, 4, False),
    ('Tomato', 0.00, 5, False),
    ('Red Pepper', 0.00, 6, False),
    ('Sauteed Mushrooms', 0.00, 7, False),
    ('Pico de Gallo', 0.00, 8, False),
    ('Spinach', 0.00, 9, False),
    ('Avocado', 0.00, 10, False),
    ('Mushrooms', 0.00, 11, False),

    # Premium extras (upcharges)
    ('Bacon', 2.50, 12, False),  # "Extra Bacon"
    ('Plain Cream Cheese', 2.00, 13, False),  # "Side of Cream Cheese"

    # Condiments
    ('Hot Sauce', 0.00, 14, False),
    ('Salsa', 0.50, 15, False),
    ('Sour Cream', 0.75, 16, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new extras ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_EXTRAS_INGREDIENTS:
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

    # Step 2: Link extras to omelette
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        _create_extras_links(conn, omelette_id, OMELETTE_EXTRAS_CONFIG)
        _update_extras_attribute(conn, omelette_id)


def _create_extras_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for extras."""
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'extras'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'extras', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_extras_attribute(conn, item_type_id: int) -> None:
    """Update extras attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'extras'
            WHERE item_type_id = :item_type_id AND slug = 'extras'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert extras attribute and remove links for omelette
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'extras'
            """),
            {"item_type_id": omelette_id}
        )
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'extras'
            """),
            {"item_type_id": omelette_id}
        )

    # Step 2: Remove newly added extras ingredients
    for name, *_ in NEW_EXTRAS_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
