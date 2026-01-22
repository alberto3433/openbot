"""Move butter from toppings to spread options

Revision ID: move_butter_spread
Revises: shots_quantity_01
Create Date: 2026-01-22

Butter is logically a spread, not a topping. This migration:
1. Adds butter to the spread global attribute
2. Removes butter from the toppings global attribute
"""
from alembic import op
from sqlalchemy import text

revision = 'move_butter_spread'
down_revision = 'shots_quantity_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Get attribute IDs
    result = conn.execute(text("SELECT id FROM global_attributes WHERE slug = 'spread'"))
    spread_id = result.scalar()

    result = conn.execute(text("SELECT id FROM global_attributes WHERE slug = 'toppings'"))
    toppings_id = result.scalar()

    if not spread_id or not toppings_id:
        print("Warning: spread or toppings attribute not found")
        return

    # Step 1: Add butter to spread (if not already there)
    result = conn.execute(text(
        "SELECT id FROM global_attribute_options WHERE global_attribute_id = :attr_id AND slug = 'butter'"
    ), {"attr_id": spread_id})
    if not result.fetchone():
        # Get butter ingredient ID for alias/must_match support
        result = conn.execute(text("SELECT id FROM ingredients WHERE name = 'Butter'"))
        butter_ingr = result.fetchone()
        butter_ingr_id = butter_ingr[0] if butter_ingr else None

        # Get max display_order
        result = conn.execute(text(
            "SELECT COALESCE(MAX(display_order), 0) + 1 FROM global_attribute_options WHERE global_attribute_id = :attr_id"
        ), {"attr_id": spread_id})
        next_order = result.scalar()

        conn.execute(text("""
            INSERT INTO global_attribute_options
            (global_attribute_id, slug, display_name, price_modifier, is_default, is_available, display_order, ingredient_id)
            VALUES (:attr_id, 'butter', 'Butter', 0.50, false, true, :order, :ingr_id)
        """), {"attr_id": spread_id, "order": next_order, "ingr_id": butter_ingr_id})
        print("Added butter to spread options")

    # Step 2: Remove butter from toppings
    conn.execute(text(
        "DELETE FROM global_attribute_options WHERE global_attribute_id = :attr_id AND slug = 'butter'"
    ), {"attr_id": toppings_id})
    print("Removed butter from toppings")


def downgrade() -> None:
    conn = op.get_bind()

    # Get attribute IDs
    result = conn.execute(text("SELECT id FROM global_attributes WHERE slug = 'spread'"))
    spread_id = result.scalar()

    result = conn.execute(text("SELECT id FROM global_attributes WHERE slug = 'toppings'"))
    toppings_id = result.scalar()

    if not spread_id or not toppings_id:
        return

    # Step 1: Remove butter from spread
    conn.execute(text(
        "DELETE FROM global_attribute_options WHERE global_attribute_id = :attr_id AND slug = 'butter'"
    ), {"attr_id": spread_id})

    # Step 2: Add butter back to toppings
    result = conn.execute(text("SELECT id FROM ingredients WHERE name = 'Butter'"))
    butter_ingr = result.fetchone()
    butter_ingr_id = butter_ingr[0] if butter_ingr else None

    conn.execute(text("""
        INSERT INTO global_attribute_options
        (global_attribute_id, slug, display_name, price_modifier, is_default, is_available, display_order, ingredient_id)
        VALUES (:attr_id, 'butter', 'Butter', 0.55, false, true, 0, :ingr_id)
    """), {"attr_id": toppings_id, "ingr_id": butter_ingr_id})
