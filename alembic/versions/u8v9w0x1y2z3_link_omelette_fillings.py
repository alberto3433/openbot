"""Link omelette fillings to ingredients table

Revision ID: u8v9w0x1y2z3
Revises: t7u8v9w0x1y2
Create Date: 2025-01-07

This migration:
1. Adds missing filling ingredient (Broccoli)
2. Creates item_type_ingredients links for omelette fillings
3. Updates omelette filling attribute to use loads_from_ingredients

Fillings include cheeses, proteins, and vegetables - all reusing existing
ingredients from other categories for unified 86 functionality.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'u8v9w0x1y2z3'
down_revision = 't7u8v9w0x1y2'
branch_labels = None
depends_on = None


# New filling ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_FILLING_INGREDIENTS = [
    ('Broccoli', 'vegetable', True, True, True, True),
]

# Filling configuration for omelette
# Format: (ingredient_name, price_modifier, display_order, is_default)
# Uses existing ingredients from cheese, protein, and topping categories
OMELETTE_FILLING_CONFIG = [
    # Cheeses (included in omelette price)
    ('American Cheese', 0.00, 1, False),
    ('Cheddar Cheese', 0.00, 2, False),
    ('Swiss Cheese', 0.00, 3, False),
    ('Muenster Cheese', 0.00, 4, False),

    # Proteins (upcharges)
    ('Turkey Bacon', 2.00, 5, False),
    ('Sausage', 2.00, 6, False),
    ('Nova Scotia Salmon', 4.00, 7, False),
    ('Corned Beef', 3.00, 8, False),
    ('Pastrami', 3.00, 9, False),
    ('Ham', 2.00, 10, False),

    # Vegetables
    ('Onion', 0.00, 11, False),
    ('Bell Pepper', 0.00, 12, False),  # "Peppers" in options
    ('Tomato', 0.00, 13, False),
    ('Mushrooms', 0.75, 14, False),
    ('Spinach', 0.75, 15, False),
    ('Avocado', 2.50, 16, False),
    ('Broccoli', 0.75, 17, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new filling ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_FILLING_INGREDIENTS:
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

    # Step 2: Link fillings to omelette
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        _create_filling_links(conn, omelette_id, OMELETTE_FILLING_CONFIG)
        _update_filling_attribute(conn, omelette_id)


def _create_filling_links(conn, item_type_id: int, config: list) -> None:
    """Create item_type_ingredients links for fillings."""
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = 'filling'
            """),
            {"item_type_id": item_type_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'filling', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": item_type_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )


def _update_filling_attribute(conn, item_type_id: int) -> None:
    """Update filling attribute to use loads_from_ingredients."""
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'filling'
            WHERE item_type_id = :item_type_id AND slug = 'filling'
        """),
        {"item_type_id": item_type_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Revert filling attribute and remove links for omelette
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = 'filling'
            """),
            {"item_type_id": omelette_id}
        )
        conn.execute(
            text("""
                DELETE FROM item_type_ingredients
                WHERE item_type_id = :item_type_id AND ingredient_group = 'filling'
            """),
            {"item_type_id": omelette_id}
        )

    # Step 2: Remove newly added filling ingredients
    for name, *_ in NEW_FILLING_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
