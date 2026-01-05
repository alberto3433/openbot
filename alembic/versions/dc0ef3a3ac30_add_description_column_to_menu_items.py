"""Add description column to menu_items and neighborhood_zip_codes table

Revision ID: dc0ef3a3ac30
Revises: j0k1l2m3n4o5
Create Date: 2026-01-05 15:55:14.864904

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc0ef3a3ac30'
down_revision: Union[str, Sequence[str], None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add description column to menu_items
    op.add_column('menu_items', sa.Column('description', sa.Text(), nullable=True))

    # Create neighborhood_zip_codes table for neighborhood-to-zip mapping
    op.create_table(
        'neighborhood_zip_codes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('neighborhood', sa.String(100), nullable=False),
        sa.Column('zip_codes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('borough', sa.String(50), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('neighborhood', name='uq_neighborhood_zip_codes_neighborhood')
    )
    op.create_index('ix_neighborhood_zip_codes_neighborhood', 'neighborhood_zip_codes', ['neighborhood'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_neighborhood_zip_codes_neighborhood', table_name='neighborhood_zip_codes')
    op.drop_table('neighborhood_zip_codes')
    op.drop_column('menu_items', 'description')
