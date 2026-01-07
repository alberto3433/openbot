"""Link bagel spreads to ingredients table

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2025-01-07

This migration links the bagel item type's spread attribute to the ingredients
table, enabling unified inventory management and 86 functionality for all
cream cheese varieties and other spreads.

Pricing is set as price_modifier (upcharge from base bagel price):
- Plain Cream Cheese: $1.50 (matches current)
- Standard specialty CC: $1.75 (Scallion, Vegetable, etc.)
- Premium CC: $2.00-$2.50 (Truffle, Nova, Honey Walnut)
- Butter: $0.50
- Other spreads: $1.00-$2.00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'o2p3q4r5s6t7'
down_revision = 'n1o2p3q4r5s6'
branch_labels = None
depends_on = None


# Bagel spread ingredients configuration
# Format: (ingredient_name, price_modifier, display_order, is_default)
# Pricing based on current attribute_options and ingredient value
BAGEL_SPREAD_CONFIG = [
    # Cream Cheeses - most popular first
    ('Plain Cream Cheese', 1.50, 1, True),  # Default spread
    ('Scallion Cream Cheese', 1.75, 2, False),
    ('Vegetable Cream Cheese', 1.75, 3, False),
    ('Strawberry Cream Cheese', 1.75, 4, False),
    ('Blueberry Cream Cheese', 1.75, 5, False),
    ('Jalapeño Cream Cheese', 1.75, 6, False),
    ('Olive Cream Cheese', 1.75, 7, False),
    ('Sun-Dried Tomato Cream Cheese', 2.00, 8, False),
    ('Kalamata Olive Cream Cheese', 2.00, 9, False),
    ('Honey Walnut Cream Cheese', 2.25, 10, False),
    ('Maple Raisin Walnut Cream Cheese', 2.25, 11, False),
    ('Nova Scotia Cream Cheese', 2.50, 12, False),
    ('Truffle Cream Cheese', 2.75, 13, False),

    # Tofu cream cheeses (dairy-free options)
    ('Tofu Cream Cheese', 1.75, 14, False),
    ('Tofu Scallion Cream Cheese', 2.00, 15, False),
    ('Tofu Vegetable Cream Cheese', 2.00, 16, False),
    ('Tofu Nova Cream Cheese', 2.50, 17, False),

    # Other spreads
    ('Butter', 0.50, 18, False),
    ('Peanut Butter', 1.25, 19, False),
    ('Nutella', 1.50, 20, False),
    ('Hummus', 1.75, 21, False),
    ('Avocado Spread', 2.25, 22, False),
    ('Jam', 0.75, 23, False),
    ('Jelly', 0.75, 24, False),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Get the bagel item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row is None:
        print("Warning: bagel item type not found, skipping migration")
        return
    bagel_id = row[0]

    # Step 2: Create item_type_ingredients links for bagel spreads
    for ingredient_name, price_modifier, display_order, is_default in BAGEL_SPREAD_CONFIG:
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
            {"item_type_id": bagel_id, "ingredient_id": ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'spread', :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": bagel_id,
                    "ingredient_id": ingredient_id,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )

    # Step 3: Update bagel spread attribute to use loads_from_ingredients
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = true, ingredient_group = 'spread'
            WHERE item_type_id = :item_type_id AND slug = 'spread'
        """),
        {"item_type_id": bagel_id}
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Get bagel item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'bagel'"))
    row = result.fetchone()
    if row is None:
        return
    bagel_id = row[0]

    # Step 1: Revert bagel spread attribute
    conn.execute(
        text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = false, ingredient_group = NULL
            WHERE item_type_id = :item_type_id AND slug = 'spread'
        """),
        {"item_type_id": bagel_id}
    )

    # Step 2: Remove item_type_ingredients links for bagel spreads
    conn.execute(
        text("""
            DELETE FROM item_type_ingredients
            WHERE item_type_id = :item_type_id AND ingredient_group = 'spread'
        """),
        {"item_type_id": bagel_id}
    )
