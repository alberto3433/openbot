"""Link spread_sandwich attributes to ingredients table

Revision ID: a4b5c6d7e8f9
Revises: z3a4b5c6d7e8
Create Date: 2026-01-07

This migration:
1. Creates item_type_ingredients links for spread, cheese, condiments, proteins, toppings
2. Updates spread_sandwich attributes to use loads_from_ingredients

Note: bread attribute was already migrated in a previous migration.
All required ingredients already exist from previous migrations.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'a4b5c6d7e8f9'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


# Spread configuration for spread_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
# Maps attribute option display names to ingredient names
SPREAD_SANDWICH_SPREAD_CONFIG = [
    ('Plain Cream Cheese', 0.00, 1, False),
    ('Scallion Cream Cheese', 0.00, 2, False),
    ('Vegetable Cream Cheese', 0.00, 3, False),
    ('Jalapeño Cream Cheese', 0.00, 4, False),  # Note: uses ñ character
    ('Blueberry Cream Cheese', 0.00, 5, False),
    ('Strawberry Cream Cheese', 0.00, 6, False),
    ('Maple Raisin Walnut Cream Cheese', 0.00, 7, False),
    ('Kalamata Olive Cream Cheese', 0.00, 8, False),
    ('Sun-Dried Tomato Cream Cheese', 0.00, 9, False),
    ('Nova Scotia Cream Cheese', 0.00, 10, False),
    ('Truffle Cream Cheese', 0.00, 11, False),
    ('Tofu Cream Cheese', 0.00, 12, False),  # "Tofu Plain" in options
    ('Tofu Scallion Cream Cheese', 0.00, 13, False),  # "Tofu Scallion" in options
    ('Tofu Vegetable Cream Cheese', 0.00, 14, False),  # "Tofu Vegetable" in options
    ('Tofu Nova Cream Cheese', 0.00, 15, False),  # "Tofu Nova" in options
    ('Butter', 0.00, 16, False),
    ('Peanut Butter', 0.00, 17, False),
    ('Nutella', 0.00, 18, False),
    ('Hummus', 0.00, 19, False),
    ('Avocado Spread', 0.00, 20, False),
]


# Cheese configuration for spread_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
SPREAD_SANDWICH_CHEESE_CONFIG = [
    ('American Cheese', 1.50, 1, False),
    ('Swiss Cheese', 1.50, 2, False),
    ('Cheddar Cheese', 1.50, 3, False),
    ('Muenster Cheese', 1.50, 4, False),
    ('Provolone Cheese', 1.50, 5, False),
    ('Pepper Jack Cheese', 1.50, 6, False),
    ('Havarti Cheese', 1.50, 7, False),
    ('Fresh Mozzarella Cheese', 1.50, 8, False),
]


# Condiments configuration for spread_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
SPREAD_SANDWICH_CONDIMENTS_CONFIG = [
    ('Mayo', 0.00, 1, False),
    ('Mustard', 0.00, 2, False),
    ('Russian Dressing', 0.00, 3, False),
    ('Olive Oil', 0.00, 4, False),
    ('Hot Sauce', 0.00, 5, False),
]


# Proteins configuration for spread_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
SPREAD_SANDWICH_PROTEINS_CONFIG = [
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


# Toppings configuration for spread_sandwich
# Format: (ingredient_name, price_modifier, display_order, is_default)
SPREAD_SANDWICH_TOPPINGS_CONFIG = [
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


def upgrade() -> None:
    conn = op.get_bind()

    # Get spread_sandwich item type id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'spread_sandwich'"))
    row = result.fetchone()
    if not row:
        print("Warning: spread_sandwich item type not found, skipping")
        return

    spread_sandwich_id = row[0]
    print(f"Found spread_sandwich item_type_id: {spread_sandwich_id}")

    # Create links for each attribute
    _create_ingredient_links(conn, spread_sandwich_id, 'spread', SPREAD_SANDWICH_SPREAD_CONFIG)
    _create_ingredient_links(conn, spread_sandwich_id, 'cheese', SPREAD_SANDWICH_CHEESE_CONFIG)
    _create_ingredient_links(conn, spread_sandwich_id, 'condiment', SPREAD_SANDWICH_CONDIMENTS_CONFIG)
    _create_ingredient_links(conn, spread_sandwich_id, 'protein', SPREAD_SANDWICH_PROTEINS_CONFIG)
    _create_ingredient_links(conn, spread_sandwich_id, 'topping', SPREAD_SANDWICH_TOPPINGS_CONFIG)

    # Update attributes to use loads_from_ingredients
    _update_attribute(conn, spread_sandwich_id, 'spread', 'spread')
    _update_attribute(conn, spread_sandwich_id, 'cheese', 'cheese')
    _update_attribute(conn, spread_sandwich_id, 'condiments', 'condiment')
    _update_attribute(conn, spread_sandwich_id, 'proteins', 'protein')
    _update_attribute(conn, spread_sandwich_id, 'toppings', 'topping')


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

    print(f"Created {created} {ingredient_group} links for spread_sandwich")


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

    # Revert attributes and remove links for spread_sandwich
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'spread_sandwich'"))
    row = result.fetchone()
    if row:
        spread_sandwich_id = row[0]

        # Revert attributes
        for attr_slug in ['spread', 'cheese', 'condiments', 'proteins', 'toppings']:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET loads_from_ingredients = false, ingredient_group = NULL
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": spread_sandwich_id, "slug": attr_slug}
            )

        # Remove links
        for ingredient_group in ['spread', 'cheese', 'condiment', 'protein', 'topping']:
            conn.execute(
                text("""
                    DELETE FROM item_type_ingredients
                    WHERE item_type_id = :item_type_id AND ingredient_group = :group
                """),
                {"item_type_id": spread_sandwich_id, "group": ingredient_group}
            )
