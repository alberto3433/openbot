"""Link remaining omelette attributes to ingredients table

Revision ID: omelette_ingr01
Revises: d8e9f0g1h2i3
Create Date: 2026-01-07

This migration:
1. Adds missing side ingredients (Fruit Salad, Small Fruit Salad)
2. Creates item_type_ingredients links for bagel_choice, condiments, side_choice,
   side_options, spread, veggies
3. Updates omelette attributes to use loads_from_ingredients

Note: cheese, extras, filling, protein attributes were already migrated.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'omelette_ingr01'
down_revision = 'd8e9f0g1h2i3'
branch_labels = None
depends_on = None


# New side ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_SIDE_INGREDIENTS = [
    ('Fruit Salad', 'side', True, True, True, True),
    ('Small Fruit Salad', 'side', True, True, True, True),
]


# Bagel choice configuration for omelette
# Format: (ingredient_name, price_modifier, display_order, is_default)
OMELETTE_BAGEL_CHOICE_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),
    ('Everything Bagel', 0.00, 2, False),
    ('Sesame Bagel', 0.00, 3, False),
    ('Poppy Bagel', 0.00, 4, False),
    ('Onion Bagel', 0.00, 5, False),
    ('Salt Bagel', 0.00, 6, False),
    ('Garlic Bagel', 0.00, 7, False),
    ('Pumpernickel Bagel', 0.00, 8, False),
    ('Cinnamon Raisin Bagel', 0.00, 9, False),
    ('Whole Wheat Bagel', 0.00, 10, False),
    ('Everything Wheat Bagel', 0.00, 11, False),
    ('Bialy', 0.00, 12, False),
]


# Condiments configuration for omelette
OMELETTE_CONDIMENTS_CONFIG = [
    ('Mayo', 0.00, 1, False),
    ('Mustard', 0.00, 2, False),
    ('Russian Dressing', 0.00, 3, False),
    ('Olive Oil', 0.00, 4, False),
    ('Hot Sauce', 0.00, 5, False),
]


# Side choice configuration for omelette
# Maps "Bagel" option to "Plain Bagel" ingredient
OMELETTE_SIDE_CHOICE_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),  # "Bagel" in options
    ('Fruit Salad', 0.00, 2, False),
]


# Side options configuration for omelette
OMELETTE_SIDE_OPTIONS_CONFIG = [
    ('Plain Bagel', 0.00, 1, True),  # "Bagel" in options
    ('Small Fruit Salad', 0.00, 2, False),
]


# Spread configuration for omelette
OMELETTE_SPREAD_CONFIG = [
    ('Chipotle Cream Cheese', 0.00, 1, False),
    ('Truffle Cream Cheese', 0.00, 2, False),
]


# Veggies configuration for omelette
# Maps attribute option names to ingredient names
OMELETTE_VEGGIES_CONFIG = [
    ('Spinach', 0.00, 1, True),
    ('Tomato', 0.00, 2, False),  # "Tomatoes" in options
    ('Onion', 0.00, 3, False),  # "Onions" in options
    ('Bell Pepper', 0.00, 4, False),  # "Peppers" in options
    ('Mushrooms', 0.00, 5, False),
    ('Broccoli', 0.00, 6, False),
    ('Roasted Peppers', 0.00, 7, False),
    ('Jalapeno', 0.00, 8, False),  # "Jalapenos" in options
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new side ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_SIDE_INGREDIENTS:
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
            print(f"Added side ingredient: {name}")

    # Step 2: Get omelette item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if not row:
        print("Warning: omelette item type not found, skipping")
        return

    omelette_id = row[0]
    print(f"Found omelette item_type_id: {omelette_id}")

    # Step 3: Create links for each attribute
    _create_ingredient_links(conn, omelette_id, 'bagel_choice', OMELETTE_BAGEL_CHOICE_CONFIG)
    _create_ingredient_links(conn, omelette_id, 'condiment', OMELETTE_CONDIMENTS_CONFIG)
    _create_ingredient_links(conn, omelette_id, 'side_choice', OMELETTE_SIDE_CHOICE_CONFIG)
    _create_ingredient_links(conn, omelette_id, 'side_options', OMELETTE_SIDE_OPTIONS_CONFIG)
    _create_ingredient_links(conn, omelette_id, 'spread', OMELETTE_SPREAD_CONFIG)
    _create_ingredient_links(conn, omelette_id, 'veggies', OMELETTE_VEGGIES_CONFIG)

    # Step 4: Update attributes to use loads_from_ingredients
    _update_attribute(conn, omelette_id, 'bagel_choice', 'bagel_choice')
    _update_attribute(conn, omelette_id, 'condiments', 'condiment')
    _update_attribute(conn, omelette_id, 'side_choice', 'side_choice')
    _update_attribute(conn, omelette_id, 'side_options', 'side_options')
    _update_attribute(conn, omelette_id, 'spread', 'spread')
    _update_attribute(conn, omelette_id, 'veggies', 'veggies')


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

    print(f"Created {created} {ingredient_group} links for omelette")


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

    # Step 1: Revert attributes and remove links for omelette
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'omelette'"))
    row = result.fetchone()
    if row:
        omelette_id = row[0]

        # Revert attributes
        for attr_slug in ['bagel_choice', 'condiments', 'side_choice', 'side_options', 'spread', 'veggies']:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": omelette_id, "slug": attr_slug}
            )

        # Remove links
        for ingredient_group in ['bagel_choice', 'condiment', 'side_choice', 'side_options', 'spread', 'veggies']:
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = :group
                """),
                {"item_type_id": omelette_id, "group": ingredient_group}
            )

    # Step 2: Remove newly added side ingredients
    for name, *_ in NEW_SIDE_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
