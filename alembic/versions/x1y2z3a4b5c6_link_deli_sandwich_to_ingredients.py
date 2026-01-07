"""Link deli_sandwich attributes to ingredients table

Revision ID: x1y2z3a4b5c6
Revises: w0x1y2z3a4b5
Create Date: 2026-01-07

This migration:
1. Adds missing ingredients for deli_sandwich options
2. Creates item_type_ingredients links for bread, cheese, toppings, condiments, extra_proteins
3. Updates deli_sandwich attributes to use loads_from_ingredients

This enables unified 86 functionality for deli sandwiches - mark an ingredient
unavailable once and it affects all item types that use it.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'x1y2z3a4b5c6'
down_revision = 'w0x1y2z3a4b5'
branch_labels = None
depends_on = None


# New ingredients to add
# Format: (name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
NEW_INGREDIENTS = [
    # Special bread option
    ('No Bread', 'bread', True, True, True, True),
]


# Bread configuration for deli_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
# Maps attribute option display_name to ingredient name
DELI_SANDWICH_BREAD_CONFIG = [
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
    ('No Bread', 2.00, 27, False),  # In a bowl option
]


# Cheese configuration for deli_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
DELI_SANDWICH_CHEESE_CONFIG = [
    ('American Cheese', 1.50, 1, False),
    ('Swiss Cheese', 1.50, 2, False),
    ('Cheddar Cheese', 1.50, 3, False),
    ('Muenster Cheese', 1.50, 4, False),
    ('Provolone Cheese', 1.50, 5, False),
    ('Pepper Jack Cheese', 1.50, 6, False),
    ('Havarti Cheese', 1.50, 7, False),
    ('Fresh Mozzarella Cheese', 1.50, 8, False),
]


# Toppings configuration for deli_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
DELI_SANDWICH_TOPPINGS_CONFIG = [
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
]


# Condiments configuration for deli_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
DELI_SANDWICH_CONDIMENTS_CONFIG = [
    ('Mayo', 0.00, 1, False),
    ('Mustard', 0.00, 2, False),
    ('Russian Dressing', 0.00, 3, False),
    ('Olive Oil', 0.00, 4, False),
    ('Hot Sauce', 0.00, 5, False),
]


# Extra proteins configuration for deli_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
DELI_SANDWICH_EXTRA_PROTEINS_CONFIG = [
    ('Bacon', 2.50, 1, False),
    ('Applewood Smoked Bacon', 2.50, 2, False),
    ('Turkey Bacon', 2.95, 3, False),
    ('Sausage', 2.75, 4, False),
    ('Sausage Patty', 2.75, 5, False),
    ('Chicken Sausage', 2.95, 6, False),
    ('Ham', 2.50, 7, False),
    ('Corned Beef', 3.45, 8, False),
    ('Pastrami', 3.45, 9, False),
    ('Roast Beef', 3.45, 10, False),
    ('Smoked Turkey', 3.45, 11, False),
    ('Nova Scotia Salmon', 6.00, 12, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add new ingredients
    for name, category, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in NEW_INGREDIENTS:
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
            print(f"Added ingredient: {name}")

    # Step 2: Get deli_sandwich item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'deli_sandwich'"))
    row = result.fetchone()
    if not row:
        print("Warning: deli_sandwich item type not found, skipping")
        return

    deli_sandwich_id = row[0]
    print(f"Found deli_sandwich item_type_id: {deli_sandwich_id}")

    # Step 3: Create links for each attribute
    _create_ingredient_links(conn, deli_sandwich_id, 'bread', DELI_SANDWICH_BREAD_CONFIG)
    _create_ingredient_links(conn, deli_sandwich_id, 'cheese', DELI_SANDWICH_CHEESE_CONFIG)
    _create_ingredient_links(conn, deli_sandwich_id, 'topping', DELI_SANDWICH_TOPPINGS_CONFIG)
    _create_ingredient_links(conn, deli_sandwich_id, 'condiment', DELI_SANDWICH_CONDIMENTS_CONFIG)
    _create_ingredient_links(conn, deli_sandwich_id, 'extra_protein', DELI_SANDWICH_EXTRA_PROTEINS_CONFIG)

    # Step 4: Update attributes to use loads_from_ingredients
    _update_attribute(conn, deli_sandwich_id, 'bread', 'bread')
    _update_attribute(conn, deli_sandwich_id, 'cheese', 'cheese')
    _update_attribute(conn, deli_sandwich_id, 'toppings', 'topping')
    _update_attribute(conn, deli_sandwich_id, 'condiments', 'condiment')
    _update_attribute(conn, deli_sandwich_id, 'extra_proteins', 'extra_protein')


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

    print(f"Created {created} {ingredient_group} links for deli_sandwich")


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

    # Step 1: Revert attributes and remove links for deli_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'deli_sandwich'"))
    row = result.fetchone()
    if row:
        deli_sandwich_id = row[0]

        # Revert attributes
        for attr_slug in ['bread', 'cheese', 'toppings', 'condiments', 'extra_proteins']:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": deli_sandwich_id, "slug": attr_slug}
            )

        # Remove links
        for ingredient_group in ['bread', 'cheese', 'topping', 'condiment', 'extra_protein']:
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = :group
                """),
                {"item_type_id": deli_sandwich_id, "group": ingredient_group}
            )

    # Step 2: Remove newly added ingredients
    for name, *_ in NEW_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name"),
            {"name": name}
        )
