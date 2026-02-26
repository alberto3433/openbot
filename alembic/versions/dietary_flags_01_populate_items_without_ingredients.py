"""Populate dietary flags for menu items without linked ingredients.

198 menu items have no linked ingredients (menu_item_ingredients rows),
so their dietary flags are NULL. This migration sets sensible defaults
based on item type.

Items WITH linked ingredients compute dietary flags at runtime from their
ingredients - those are NOT touched by this migration.

Revision ID: dietary_flags_01
Revises: cheese_sandwich_01
Create Date: 2025-02-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision = 'dietary_flags_01'
down_revision = 'cheese_sandwich_01'
branch_labels = None
depends_on = None


# Dietary defaults by item type slug
# Key rationale:
# - is_kosher = TRUE for all (Borough Bagels is kosher certified)
# - Espresso/coffee drinks: Vegetarian but not vegan (default has dairy milk)
# - Plain espresso: Vegan (no milk in default config)
# - Pastries: Assume contain eggs/butter (not vegan, not dairy-free, not gluten-free)
# - Fish/Cold cuts: Not vegetarian (animal flesh)
# - Snacks: Mostly vegan (chips, pretzels, etc.)
# - Spreads: Cream cheese is vegetarian but not vegan/dairy-free
DIETARY_DEFAULTS = {
    # Beverages - plain drinks without dairy
    'beverage': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'soda': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'tea': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'iced_tea': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'espresso': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    # Beverages - default has dairy milk
    'espresso_based_beverage': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'coffee_based_beverage': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'chai_drink': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'cocoa_based_beverage': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    # Foods
    'pastry': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'side': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'snack': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': True, 'is_kosher': True
    },
    'spread': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'fish': {
        'is_vegan': False, 'is_vegetarian': False, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'cold_cut': {
        'is_vegan': False, 'is_vegetarian': False, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'cheese': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'bagel_package': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'breakfast': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'soup': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'salad': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': False, 'is_kosher': True
    },
    'fruit_salad': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': True,
        'is_dairy_free': True, 'is_kosher': True
    },
    'bagel': {
        'is_vegan': True, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': True, 'is_kosher': True
    },
    'egg_sandwich': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
    'spread_sandwich': {
        'is_vegan': False, 'is_vegetarian': True, 'is_gluten_free': False,
        'is_dairy_free': False, 'is_kosher': True
    },
}


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    update_count = 0
    for item_type_slug, flags in DIETARY_DEFAULTS.items():
        # Update menu items where:
        # 1. Item type matches the slug
        # 2. No linked ingredients (not in menu_item_ingredients)
        # 3. Dietary column is NULL (don't override existing values)
        #
        # We update each flag individually with its own NULL check to preserve
        # any manually set values.
        result = session.execute(
            sa.text("""
                UPDATE menu_items m
                SET
                    is_vegan = COALESCE(m.is_vegan, :is_vegan),
                    is_vegetarian = COALESCE(m.is_vegetarian, :is_vegetarian),
                    is_gluten_free = COALESCE(m.is_gluten_free, :is_gluten_free),
                    is_dairy_free = COALESCE(m.is_dairy_free, :is_dairy_free),
                    is_kosher = COALESCE(m.is_kosher, :is_kosher)
                FROM item_types it
                WHERE m.item_type_id = it.id
                  AND it.slug = :item_type_slug
                  AND NOT EXISTS (
                      SELECT 1 FROM menu_item_ingredients mii
                      WHERE mii.menu_item_id = m.id
                  )
            """),
            {
                'item_type_slug': item_type_slug,
                'is_vegan': flags['is_vegan'],
                'is_vegetarian': flags['is_vegetarian'],
                'is_gluten_free': flags['is_gluten_free'],
                'is_dairy_free': flags['is_dairy_free'],
                'is_kosher': flags['is_kosher'],
            }
        )
        update_count += result.rowcount

    session.commit()
    print(f"Updated dietary flags for {update_count} menu items without ingredients")


def downgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    # Reset all dietary flags to NULL for items without linked ingredients
    # that match our item types
    item_type_slugs = list(DIETARY_DEFAULTS.keys())

    for item_type_slug in item_type_slugs:
        session.execute(
            sa.text("""
                UPDATE menu_items m
                SET
                    is_vegan = NULL,
                    is_vegetarian = NULL,
                    is_gluten_free = NULL,
                    is_dairy_free = NULL,
                    is_kosher = NULL
                FROM item_types it
                WHERE m.item_type_id = it.id
                  AND it.slug = :item_type_slug
                  AND NOT EXISTS (
                      SELECT 1 FROM menu_item_ingredients mii
                      WHERE mii.menu_item_id = m.id
                  )
            """),
            {'item_type_slug': item_type_slug}
        )

    session.commit()
