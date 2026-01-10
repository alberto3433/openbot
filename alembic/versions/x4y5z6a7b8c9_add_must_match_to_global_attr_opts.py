"""Add must_match column to global_attribute_options.

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-01-10

This migration adds a must_match column to global_attribute_options table
and populates it from the ingredients table based on matching slugs.

The must_match column specifies which input phrases must be present for
an option to match. For example:
- "oat_milk" has must_match = "oat milk" - only matches if user says "oat milk"
- "whole_milk" has must_match = None - matches plain "milk" (default option)
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'x4y5z6a7b8c9'
down_revision = 'w3x4y5z6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    # Add must_match column
    op.add_column('global_attribute_options', sa.Column('must_match', sa.Text(), nullable=True))

    conn = op.get_bind()

    # Populate must_match from ingredients table
    # Match by slug (global_attribute_options.slug <-> ingredients.slug)
    result = conn.execute(sa.text("""
        UPDATE global_attribute_options gao
        SET must_match = i.must_match
        FROM ingredients i
        WHERE gao.slug = i.slug AND i.must_match IS NOT NULL
    """))
    print(f"Updated {result.rowcount} options with must_match from ingredients")

    # Also try matching with category prefix removed (e.g., "espresso_vanilla_syrup" -> "vanilla_syrup")
    result = conn.execute(sa.text("""
        UPDATE global_attribute_options gao
        SET must_match = i.must_match
        FROM ingredients i
        WHERE gao.must_match IS NULL
          AND gao.slug LIKE '%_' || i.slug
          AND i.must_match IS NOT NULL
    """))
    print(f"Updated {result.rowcount} additional options with prefix matching")


def downgrade():
    op.drop_column('global_attribute_options', 'must_match')
