"""Link espresso item type to its global attributes.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-01-09

This migration adds the item_type_global_attributes links for espresso.
The seed migration used item_type_id=30 but espresso is actually id=17 in production.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'v2w3x4y5z6a7'
down_revision = 'u1v2w3x4y5z6'
branch_labels = None
depends_on = None


# Espresso global attribute links
# global_attribute_id 18 = shots
# global_attribute_id 15 = milk_sweetener_syrup
# global_attribute_id 6 = decaf
ESPRESSO_LINKS = [
    {
        "global_attribute_id": 18,  # shots
        "display_order": 1,
        "is_required": False,
        "allow_none": True,
        "ask_in_conversation": True,
        "question_text": "How many shots?",
    },
    {
        "global_attribute_id": 15,  # milk_sweetener_syrup
        "display_order": 2,
        "is_required": False,
        "allow_none": True,
        "ask_in_conversation": True,
        "question_text": "Any milk, sweetener, or syrup?",
    },
    {
        "global_attribute_id": 6,  # decaf
        "display_order": 3,
        "is_required": False,
        "allow_none": True,
        "ask_in_conversation": True,
        "question_text": None,  # Will use fallback "Would you like it decaf?"
    },
]


def upgrade():
    conn = op.get_bind()

    # Get the actual espresso item_type_id from the database
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'espresso'"
    ))
    row = result.fetchone()
    if not row:
        print("Espresso item type not found, skipping")
        return

    espresso_id = row[0]
    print(f"Found espresso item_type_id: {espresso_id}")

    # Check if links already exist
    result = conn.execute(sa.text(
        "SELECT COUNT(*) FROM item_type_global_attributes WHERE item_type_id = :id"
    ), {"id": espresso_id})
    count = result.scalar()

    if count > 0:
        print(f"Espresso already has {count} global attribute links, skipping")
        return

    # Insert the links
    for link in ESPRESSO_LINKS:
        conn.execute(sa.text("""
            INSERT INTO item_type_global_attributes
            (item_type_id, global_attribute_id, display_order, is_required, allow_none, ask_in_conversation, question_text)
            VALUES (:item_type_id, :global_attribute_id, :display_order, :is_required, :allow_none, :ask_in_conversation, :question_text)
        """), {
            "item_type_id": espresso_id,
            "global_attribute_id": link["global_attribute_id"],
            "display_order": link["display_order"],
            "is_required": link["is_required"],
            "allow_none": link["allow_none"],
            "ask_in_conversation": link["ask_in_conversation"],
            "question_text": link["question_text"],
        })

    print(f"Inserted {len(ESPRESSO_LINKS)} global attribute links for espresso")


def downgrade():
    conn = op.get_bind()

    # Get espresso item_type_id
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'espresso'"
    ))
    row = result.fetchone()
    if row:
        conn.execute(sa.text(
            "DELETE FROM item_type_global_attributes WHERE item_type_id = :id"
        ), {"id": row[0]})
