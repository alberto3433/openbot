"""Add modifies_ingredient_slug column to global_attributes

This enables data-driven linkage between quantity attributes (like egg_quantity)
and their corresponding ingredient modifiers. When a user says "3 eggs", the
system can update the existing egg modifier's quantity instead of creating
a duplicate entry.

Revision ID: egg_qty_01_modifies
Revises: fix_plain_cc_mm
Create Date: 2026-02-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'egg_qty_01_modifies'
down_revision = 'be2d3239236a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add modifies_ingredient_slug column to global_attributes
    op.add_column(
        'global_attributes',
        sa.Column('modifies_ingredient_slug', sa.String(100), nullable=True)
    )

    # Link egg_quantity attribute to the "egg" ingredient
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE global_attributes
            SET modifies_ingredient_slug = 'egg'
            WHERE slug = 'egg_quantity'
        """)
    )


def downgrade() -> None:
    op.drop_column('global_attributes', 'modifies_ingredient_slug')
