"""Populate milk_sweetener_syrup global attribute options.

Revision ID: u1v2w3x4y5z6
Revises: t1u2v3w4x5y6
Create Date: 2026-01-09

This migration populates the global_attribute_options table for the
milk_sweetener_syrup attribute (id=15) with options from item_type_ingredients.
This enables the generic menu_item_config_handler to properly configure
espresso and coffee items.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'u1v2w3x4y5z6'
down_revision = 't1u2v3w4x5y6'
branch_labels = None
depends_on = None


# Options for milk_sweetener_syrup (global_attribute_id=15)
# Grouped by category for proper display ordering
MILK_OPTIONS = [
    {"slug": "whole_milk", "display_name": "Whole Milk", "price_modifier": 0.00, "category": "milk", "display_order": 1},
    {"slug": "skim_milk", "display_name": "Skim Milk", "price_modifier": 0.00, "category": "milk", "display_order": 2},
    {"slug": "oat_milk", "display_name": "Oat Milk", "price_modifier": 0.50, "category": "milk", "display_order": 3},
    {"slug": "almond_milk", "display_name": "Almond Milk", "price_modifier": 0.50, "category": "milk", "display_order": 4},
    {"slug": "soy_milk", "display_name": "Soy Milk", "price_modifier": 0.50, "category": "milk", "display_order": 5},
    {"slug": "half_n_half", "display_name": "Half N Half", "price_modifier": 0.00, "category": "milk", "display_order": 6},
    {"slug": "lactose_free_milk", "display_name": "Lactose Free Milk", "price_modifier": 0.00, "category": "milk", "display_order": 7},
]

SWEETENER_OPTIONS = [
    {"slug": "sugar", "display_name": "Sugar", "price_modifier": 0.00, "category": "sweetener", "display_order": 10, "aliases": "domino sugar|regular sugar"},
    {"slug": "sugar_in_the_raw", "display_name": "Sugar in the Raw", "price_modifier": 0.00, "category": "sweetener", "display_order": 11},
    {"slug": "splenda", "display_name": "Splenda", "price_modifier": 0.00, "category": "sweetener", "display_order": 12},
    {"slug": "equal", "display_name": "Equal", "price_modifier": 0.00, "category": "sweetener", "display_order": 13},
    {"slug": "sweet_n_low", "display_name": "Sweet N Low", "price_modifier": 0.00, "category": "sweetener", "display_order": 14},
]

SYRUP_OPTIONS = [
    {"slug": "vanilla_syrup", "display_name": "Vanilla Syrup", "price_modifier": 0.65, "category": "syrup", "display_order": 20, "aliases": "vanilla"},
    {"slug": "hazelnut_syrup", "display_name": "Hazelnut Syrup", "price_modifier": 0.65, "category": "syrup", "display_order": 21, "aliases": "hazelnut"},
    {"slug": "caramel_syrup", "display_name": "Caramel Syrup", "price_modifier": 0.65, "category": "syrup", "display_order": 22, "aliases": "caramel"},
    {"slug": "peppermint_syrup", "display_name": "Peppermint Syrup", "price_modifier": 1.00, "category": "syrup", "display_order": 23, "aliases": "peppermint"},
]

ALL_OPTIONS = MILK_OPTIONS + SWEETENER_OPTIONS + SYRUP_OPTIONS


def upgrade():
    conn = op.get_bind()

    # Check if options already exist
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM global_attribute_options WHERE global_attribute_id = 15"
    ))
    count = result.scalar()

    if count > 0:
        print(f"milk_sweetener_syrup already has {count} options, skipping population")
        return

    # Insert all options
    for opt in ALL_OPTIONS:
        aliases = opt.get("aliases")
        conn.execute(sa.text("""
            INSERT INTO global_attribute_options
            (global_attribute_id, slug, display_name, price_modifier, iced_price_modifier, is_default, is_available, display_order, aliases)
            VALUES (15, :slug, :display_name, :price_modifier, 0, false, true, :display_order, :aliases)
        """), {
            "slug": opt["slug"],
            "display_name": opt["display_name"],
            "price_modifier": opt["price_modifier"],
            "display_order": opt["display_order"],
            "aliases": aliases,
        })

    print(f"Populated {len(ALL_OPTIONS)} options for milk_sweetener_syrup")


def downgrade():
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM global_attribute_options WHERE global_attribute_id = 15"
    ))
