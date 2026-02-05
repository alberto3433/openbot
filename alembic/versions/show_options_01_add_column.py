"""Add show_options_in_question column to item_type_global_attributes.

Revision ID: show_options_01
Revises: unrecognized_option_01
Create Date: 2026-02-05

Adds a boolean column to control whether attribute options should be
displayed inline in the question text.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "show_options_01"
down_revision = "unrecognized_option_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the column with default False (current behavior)
    op.add_column(
        "item_type_global_attributes",
        sa.Column(
            "show_options_in_question",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # Enable for the 'weight' attribute (used by fish and cream cheese by-the-pound items)
    # Also set question_text to "How much?" for natural phrasing with inline options
    op.execute("""
        UPDATE item_type_global_attributes
        SET show_options_in_question = TRUE,
            question_text = 'How much?'
        FROM global_attributes
        WHERE item_type_global_attributes.global_attribute_id = global_attributes.id
          AND global_attributes.slug = 'weight'
    """)


def downgrade() -> None:
    op.drop_column("item_type_global_attributes", "show_options_in_question")
