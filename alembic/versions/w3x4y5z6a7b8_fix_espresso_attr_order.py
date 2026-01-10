"""Fix espresso attribute display order.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-01-09

This migration fixes the display order for espresso global attributes.
The correct order should be:
1. shots (display_order=1)
2. milk_sweetener_syrup (display_order=2)
3. decaf (display_order=3)

Currently in production, decaf has order=2 and milk_sweetener_syrup has order=3,
which causes decaf to be asked before milk_sweetener_syrup.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'w3x4y5z6a7b8'
down_revision = 'v2w3x4y5z6a7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Get espresso item_type_id
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'espresso'"
    ))
    row = result.fetchone()
    if not row:
        print("Espresso item type not found, skipping")
        return

    espresso_id = row[0]
    print(f"Found espresso item_type_id: {espresso_id}")

    # Update milk_sweetener_syrup (global_attribute_id=15) to display_order=2
    result = conn.execute(sa.text("""
        UPDATE item_type_global_attributes
        SET display_order = 2
        WHERE item_type_id = :item_type_id AND global_attribute_id = 15
    """), {"item_type_id": espresso_id})
    print(f"Updated milk_sweetener_syrup display_order to 2: {result.rowcount} rows")

    # Update decaf (global_attribute_id=6) to display_order=3
    result = conn.execute(sa.text("""
        UPDATE item_type_global_attributes
        SET display_order = 3
        WHERE item_type_id = :item_type_id AND global_attribute_id = 6
    """), {"item_type_id": espresso_id})
    print(f"Updated decaf display_order to 3: {result.rowcount} rows")


def downgrade():
    conn = op.get_bind()

    # Get espresso item_type_id
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'espresso'"
    ))
    row = result.fetchone()
    if not row:
        return

    espresso_id = row[0]

    # Revert to original order
    conn.execute(sa.text("""
        UPDATE item_type_global_attributes
        SET display_order = 3
        WHERE item_type_id = :item_type_id AND global_attribute_id = 15
    """), {"item_type_id": espresso_id})

    conn.execute(sa.text("""
        UPDATE item_type_global_attributes
        SET display_order = 2
        WHERE item_type_id = :item_type_id AND global_attribute_id = 6
    """), {"item_type_id": espresso_id})
