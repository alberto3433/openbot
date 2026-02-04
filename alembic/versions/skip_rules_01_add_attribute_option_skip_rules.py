"""Add global_attribute_option_skips table

Enables data-driven attribute skipping based on selected options.
For example, when "black" is selected for coffee, skip asking about
milk, sweetener, and syrup attributes.

Revision ID: skip_rules_01
Revises: bagel_phrases_01
Create Date: 2026-02-04
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "skip_rules_01"
down_revision = "bagel_phrases_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the skip rules table
    op.create_table(
        "global_attribute_option_skips",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "triggering_option_id",
            sa.Integer(),
            sa.ForeignKey("global_attribute_options.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "skipped_attribute_id",
            sa.Integer(),
            sa.ForeignKey("global_attributes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "triggering_option_id",
            "skipped_attribute_id",
            name="uq_option_skip_rule",
        ),
    )

    # Seed skip rules for "black" option -> skip milk, sweetener, syrup
    # First, find the "black" option ID in global_attribute_options
    # Then find the attribute IDs for milk_sweetener_syrup (or individual ones if separate)
    op.execute("""
        INSERT INTO global_attribute_option_skips (triggering_option_id, skipped_attribute_id)
        SELECT opt.id, attr.id
        FROM global_attribute_options opt
        CROSS JOIN global_attributes attr
        WHERE opt.slug = 'black'
        AND attr.slug IN ('milk_sweetener_syrup')
        AND NOT EXISTS (
            SELECT 1 FROM global_attribute_option_skips
            WHERE triggering_option_id = opt.id
            AND skipped_attribute_id = attr.id
        )
    """)


def downgrade() -> None:
    op.drop_table("global_attribute_option_skips")
