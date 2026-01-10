"""Add toasted and scooped attributes to deli_sandwich item type

Revision ID: k5l6m7n8o9p1
Revises: j4k5l6m7n8o9
Create Date: 2026-01-08

This migration adds two new attributes to deli_sandwich:

1. toasted (boolean)
   - Required: No
   - Ask in conversation: Yes
   - Question: "Would you like it toasted?"

2. scooped (boolean)
   - Required: No
   - Ask in conversation: No (only if customer mentions it)
   - Question: "Would you like the bagel scooped?"

These are added after the 'bread' attribute in display order,
with 'scooped' immediately following 'toasted'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k5l6m7n8o9p1'
down_revision: Union[str, Sequence[str], None] = 'j4k5l6m7n8o9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add toasted and scooped attributes to deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        print("Warning: deli_sandwich item type not found, skipping")
        return

    deli_sandwich_id = row[0]
    print(f"Found deli_sandwich item_type_id: {deli_sandwich_id}")

    # Get the display_order of the 'bread' attribute to insert after it
    result = conn.execute(sa.text("""
        SELECT display_order FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'bread'
    """), {'item_type_id': deli_sandwich_id})
    bread_row = result.fetchone()

    if bread_row:
        bread_order = bread_row[0]
        toasted_order = bread_order + 1
        scooped_order = bread_order + 2

        # Shift existing attributes to make room
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET display_order = display_order + 2
            WHERE item_type_id = :item_type_id AND display_order > :bread_order
        """), {'item_type_id': deli_sandwich_id, 'bread_order': bread_order})
        print(f"Shifted existing attributes after bread (order={bread_order})")
    else:
        # No bread attribute found, add at the end
        result = conn.execute(sa.text("""
            SELECT COALESCE(MAX(display_order), 0) FROM item_type_attributes
            WHERE item_type_id = :item_type_id
        """), {'item_type_id': deli_sandwich_id})
        max_order = result.fetchone()[0]
        toasted_order = max_order + 1
        scooped_order = max_order + 2
        print(f"No bread attribute found, adding at end (order={toasted_order}, {scooped_order})")

    # Check if toasted attribute already exists
    result = conn.execute(sa.text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'toasted'
    """), {'item_type_id': deli_sandwich_id})

    if result.fetchone():
        print("toasted attribute already exists, skipping")
    else:
        # Create the toasted attribute (boolean, ask in conversation)
        conn.execute(sa.text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                question_text, loads_from_ingredients, display_order
            ) VALUES (
                :item_type_id, 'toasted', 'Toasted', 'boolean',
                FALSE, TRUE, TRUE,
                'Would you like it toasted?', FALSE, :display_order
            )
        """), {'item_type_id': deli_sandwich_id, 'display_order': toasted_order})
        print(f"Created toasted attribute with display_order={toasted_order}")

    # Check if scooped attribute already exists
    result = conn.execute(sa.text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'scooped'
    """), {'item_type_id': deli_sandwich_id})

    if result.fetchone():
        print("scooped attribute already exists, skipping")
    else:
        # Create the scooped attribute (boolean, don't ask unless mentioned)
        conn.execute(sa.text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type,
                is_required, allow_none, ask_in_conversation,
                question_text, loads_from_ingredients, display_order
            ) VALUES (
                :item_type_id, 'scooped', 'Scooped', 'boolean',
                FALSE, TRUE, FALSE,
                'Would you like the bagel scooped?', FALSE, :display_order
            )
        """), {'item_type_id': deli_sandwich_id, 'display_order': scooped_order})
        print(f"Created scooped attribute with display_order={scooped_order}")

    print("Successfully added toasted and scooped attributes to deli_sandwich")


def downgrade() -> None:
    """Remove toasted and scooped attributes from deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        return

    deli_sandwich_id = row[0]

    # Get the display_order of toasted to know how much to shift back
    result = conn.execute(sa.text("""
        SELECT display_order FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'toasted'
    """), {'item_type_id': deli_sandwich_id})
    toasted_row = result.fetchone()

    if toasted_row:
        toasted_order = toasted_row[0]

        # Delete the scooped attribute
        conn.execute(sa.text("""
            DELETE FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'scooped'
        """), {'item_type_id': deli_sandwich_id})

        # Delete the toasted attribute
        conn.execute(sa.text("""
            DELETE FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'toasted'
        """), {'item_type_id': deli_sandwich_id})

        # Shift attributes back
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET display_order = display_order - 2
            WHERE item_type_id = :item_type_id AND display_order > :toasted_order
        """), {'item_type_id': deli_sandwich_id, 'toasted_order': toasted_order})

        print("Removed toasted and scooped attributes from deli_sandwich")
    else:
        # Just try to delete both if they exist
        conn.execute(sa.text("""
            DELETE FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug IN ('toasted', 'scooped')
        """), {'item_type_id': deli_sandwich_id})
        print("Removed toasted and scooped attributes from deli_sandwich (no order adjustment)")
