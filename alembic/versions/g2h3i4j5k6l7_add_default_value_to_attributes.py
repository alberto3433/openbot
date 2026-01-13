"""Add default_value to item_type_attributes

This migration adds a default_value column to store default field values,
enabling data-driven field configuration instead of hardcoded Python constants.

The ask_in_conversation column already serves as ask_if_empty.

Revision ID: g2h3i4j5k6l7
Revises: 0dca5ef5e171
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "g2h3i4j5k6l7"
down_revision = "0dca5ef5e171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add default_value column for storing default field values (JSON-encoded)
    op.add_column(
        "item_type_attributes",
        sa.Column("default_value", sa.Text(), nullable=True),
    )

    # Populate default values from field_config.py hardcoded constants
    # This data enables us to remove the hardcoded DEFAULT_BAGEL_FIELDS and DEFAULT_COFFEE_FIELDS
    # Note: Database uses 'bread' slug, code uses 'bagel_type' - they map to each other

    # Bagel defaults - 'bread' attribute defaults to 'plain bagel'
    op.execute("""
        UPDATE item_type_attributes
        SET default_value = '"plain bagel"'
        WHERE slug = 'bread'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
    """)

    # Coffee/sized_beverage defaults - 'shots' defaults to 0
    op.execute("""
        UPDATE item_type_attributes
        SET default_value = '0'
        WHERE slug = 'shots'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
    """)

    # Update ask_in_conversation to FALSE for fields that shouldn't be asked
    # shots: don't ask about extra shots (only capture if mentioned)
    op.execute("""
        UPDATE item_type_attributes
        SET ask_in_conversation = FALSE
        WHERE slug = 'shots'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'sized_beverage')
    """)

    # scooped: don't ask about scooping (only capture if mentioned)
    op.execute("""
        UPDATE item_type_attributes
        SET ask_in_conversation = FALSE
        WHERE slug = 'scooped'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
    """)

    # Update question_text for spread to match field_config.py style
    op.execute("""
        UPDATE item_type_attributes
        SET question_text = 'Would you like cream cheese or butter on that?',
            ask_in_conversation = TRUE
        WHERE slug = 'spread'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
    """)

    # Update question_text for toasted to match field_config.py style
    op.execute("""
        UPDATE item_type_attributes
        SET question_text = 'Would you like that toasted?',
            ask_in_conversation = TRUE
        WHERE slug = 'toasted'
        AND item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
    """)


def downgrade() -> None:
    op.drop_column("item_type_attributes", "default_value")
