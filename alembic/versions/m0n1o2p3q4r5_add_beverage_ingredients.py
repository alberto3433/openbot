"""Add beverage ingredients and link to sized_beverage

Revision ID: m0n1o2p3q4r5
Revises: l9m0n1o2p3q4
Create Date: 2025-01-07

This migration:
1. Adds beverage ingredients (milks, sweeteners, syrups) to the ingredients table
2. Creates item_type_ingredients links for the sized_beverage item type
3. Updates item_type_attributes (milk, sweetener, syrup) to use loads_from_ingredients

This consolidates beverage add-ins into the unified ingredient system, enabling:
- Consistent 86 functionality with food items
- Single source of truth for inventory
- Per-item-type pricing via item_type_ingredients
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'm0n1o2p3q4r5'
down_revision = 'l9m0n1o2p3q4'
branch_labels = None
depends_on = None


# Beverage ingredients to add
# Format: (name, category, unit, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free)
BEVERAGE_INGREDIENTS = [
    # Milks
    ('Whole Milk', 'milk', 'oz', False, True, True, False),
    ('Half N Half', 'milk', 'oz', False, True, True, False),
    ('Lactose Free Milk', 'milk', 'oz', False, True, True, False),
    ('Skim Milk', 'milk', 'oz', False, True, True, False),
    ('Oat Milk', 'milk', 'oz', True, True, True, True),
    ('Almond Milk', 'milk', 'oz', True, True, True, True),
    ('Soy Milk', 'milk', 'oz', True, True, True, True),

    # Sweeteners
    ('Sugar in the Raw', 'sweetener', 'packet', True, True, True, True),
    ('Domino Sugar', 'sweetener', 'packet', True, True, True, True),
    ('Equal', 'sweetener', 'packet', True, True, True, True),
    ('Splenda', 'sweetener', 'packet', True, True, True, True),
    ('Sweet N Low', 'sweetener', 'packet', True, True, True, True),

    # Syrups
    ('Vanilla Syrup', 'syrup', 'pump', True, True, True, True),
    ('Hazelnut Syrup', 'syrup', 'pump', True, True, True, True),
    ('Caramel Syrup', 'syrup', 'pump', True, True, True, True),
    ('Peppermint Syrup', 'syrup', 'pump', True, True, True, True),
]

# Item type ingredients configuration
# Format: (ingredient_name, ingredient_group, price_modifier, display_order, is_default)
ITEM_TYPE_INGREDIENTS_CONFIG = [
    # Milks - prices from attribute_options
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

    # Syrups - prices from attribute_options
    ('Vanilla Syrup', 'syrup', 0.65, 1, False),
    ('Hazelnut Syrup', 'syrup', 0.65, 2, False),
    ('Caramel Syrup', 'syrup', 0.65, 3, False),
    ('Peppermint Syrup', 'syrup', 1.00, 4, False),  # Seasonal/premium
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add beverage ingredients to ingredients table
    for name, category, unit, is_vegan, is_vegetarian, is_gluten_free, is_dairy_free in BEVERAGE_INGREDIENTS:
        # Check if ingredient already exists (by name)
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, base_price, is_available,
                                           is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                    VALUES (:name, :category, :unit, true, 0.0, true,
                            :is_vegan, :is_vegetarian, :is_gluten_free, :is_dairy_free, true)
                """),
                {
                    "name": name,
                    "category": category,
                    "unit": unit,
                    "is_vegan": is_vegan,
                    "is_vegetarian": is_vegetarian,
                    "is_gluten_free": is_gluten_free,
                    "is_dairy_free": is_dairy_free,
                }
            )

    # Step 2: Get the sized_beverage item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'sized_beverage'"))
    row = result.fetchone()
    if row is None:
        raise Exception("sized_beverage item type not found")
    sized_beverage_id = row[0]

    # Step 3: Create item_type_ingredients links
    for ingredient_name, ingredient_group, price_modifier, display_order, is_default in ITEM_TYPE_INGREDIENTS_CONFIG:
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
            {"item_type_id": sized_beverage_id, "ingredient_id": ingredient_id, "group": ingredient_group}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, price_modifier, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, :group, :price, :order, :is_default, true)
                """),
                {
                    "item_type_id": sized_beverage_id,
                    "ingredient_id": ingredient_id,
                    "group": ingredient_group,
                    "price": price_modifier,
                    "order": display_order,
                    "is_default": is_default,
                }
            )

    # Step 4: Update item_type_attributes to use loads_from_ingredients
    for attr_slug, ingredient_group in [('milk', 'milk'), ('sweetener', 'sweetener'), ('syrup', 'syrup')]:
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = true, ingredient_group = :group
                WHERE item_type_id = :item_type_id AND slug = :slug
            """),
            {"item_type_id": sized_beverage_id, "slug": attr_slug, "group": ingredient_group}
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Get sized_beverage item_type_id
    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'sized_beverage'"))
    row = result.fetchone()
    if row is None:
        return
    sized_beverage_id = row[0]

    # Step 1: Revert item_type_attributes
    for attr_slug in ['milk', 'sweetener', 'syrup']:
        conn.execute(
            text("""
                UPDATE item_type_attributes
                SET loads_from_ingredients = false, ingredient_group = NULL
                WHERE item_type_id = :item_type_id AND slug = :slug
            """),
            {"item_type_id": sized_beverage_id, "slug": attr_slug}
        )

    # Step 2: Remove item_type_ingredients links for sized_beverage
    conn.execute(
        text("DELETE FROM item_type_ingredients WHERE item_type_id = :item_type_id"),
        {"item_type_id": sized_beverage_id}
    )

    # Step 3: Remove beverage ingredients
    # Only remove if they were added by this migration (check category)
    for name, category, *_ in BEVERAGE_INGREDIENTS:
        conn.execute(
            text("DELETE FROM ingredients WHERE name = :name AND category = :category"),
            {"name": name, "category": category}
        )
