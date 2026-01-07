"""Link espresso to beverage ingredients

Revision ID: n1o2p3q4r5s6
Revises: m0n1o2p3q4r5
Create Date: 2025-01-07

This migration links the espresso item type to the same beverage ingredients
(milk, sweetener, syrup) used by sized_beverage, enabling unified inventory
management and 86 functionality.

The espresso will use the same pricing as sized_beverage for these modifiers.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'n1o2p3q4r5s6'
down_revision = 'm0n1o2p3q4r5'
branch_labels = None
depends_on = None


# Item type ingredients configuration for espresso
# Format: (ingredient_name, ingredient_group, price_modifier, display_order, is_default)
# Using same pricing as sized_beverage
ESPRESSO_INGREDIENTS_CONFIG = [
    # Milks - same as sized_beverage
    ('Whole Milk', 'milk', 0.00, 1, True),  # Default milk
    ('Half N Half', 'milk', 0.00, 2, False),
    ('Lactose Free Milk', 'milk', 0.00, 3, False),
    ('Skim Milk', 'milk', 0.00, 4, False),
    ('Oat Milk', 'milk', 0.50, 5, False),
    ('Almond Milk', 'milk', 0.50, 6, False),
    ('Soy Milk', 'milk', 0.50, 7, False),

    # Sweeteners - all free
    ('Sugar in the Raw', 'sweetener', 0.00, 1, False),
    ('Domino Sugar', 'sweetener', 0.00, 2, False),
    ('Equal', 'sweetener', 0.00, 3, False),
    ('Splenda', 'sweetener', 0.00, 4, False),
    ('Sweet N Low', 'sweetener', 0.00, 5, False),

    # Syrups - same as sized_beverage
    ('Vanilla Syrup', 'syrup', 0.65, 1, False),
    ('Hazelnut Syrup', 'syrup', 0.65, 2, False),
    ('Caramel Syrup', 'syrup', 0.65, 3, False),
    ('Peppermint Syrup', 'syrup', 1.00, 4, False),  # Seasonal/premium
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Get the espresso item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'espresso'"))
    row = result.fetchone()
    if row is None:
        print("Warning: espresso item type not found, skipping migration")
        return
    espresso_id = row[0]

    # Step 2: Create item_type_ingredients links for espresso
    for ingredient_name, ingredient_group, price_modifier, display_order, is_default in ESPRESSO_INGREDIENTS_CONFIG:
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
                WHERE item_type_id = :item_type_id AND ingredient_id = :ingredient_id AND ingredient_group = :group
            """),
            {"item_type_id": espresso_id, "ingredient_id": ingredient_id, "group": ingredient_group}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, :group, :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": espresso_id,
                    "ingredient_id": ingredient_id,
                    "group": ingredient_group,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )

    # Step 3: Update item_type_attributes to use loads_from_ingredients
    for attr_slug, ingredient_group in [('milk', 'milk'), ('sweetener', 'sweetener'), ('syrup', 'syrup')]:
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = true, ingredient_group = :group
                WHERE item_type_id = :item_type_id AND slug = :slug
            """),
            {"item_type_id": espresso_id, "slug": attr_slug, "group": ingredient_group}
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Get espresso item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'espresso'"))
    row = result.fetchone()
    if row is None:
        return
    espresso_id = row[0]

    # Step 1: Revert item_type_attributes
    for attr_slug in ['milk', 'sweetener', 'syrup']:
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = :slug
            """),
            {"item_type_id": espresso_id, "slug": attr_slug}
        )

    # Step 2: Remove item_type_ingredients links for espresso
    conn.execute(
        text("DELETE FROM item_type_ingredients WHERE item_type_id = :item_type_id"),
        {"item_type_id": espresso_id}
    )
