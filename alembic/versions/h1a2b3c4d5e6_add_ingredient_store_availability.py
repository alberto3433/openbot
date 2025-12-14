"""add_ingredient_store_availability

Revision ID: h1a2b3c4d5e6
Revises: g9b0c3d4e5f6
Create Date: 2025-12-14 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'g9b0c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ingredient_store_availability table for per-store 86 tracking."""
    op.create_table(
        'ingredient_store_availability',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.String(), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ingredient_id', 'store_id', name='uix_ingredient_store')
    )
    op.create_index('ix_ingredient_store_availability_id', 'ingredient_store_availability', ['id'])
    op.create_index('ix_ingredient_store_availability_store_id', 'ingredient_store_availability', ['store_id'])


def downgrade() -> None:
    """Drop ingredient_store_availability table."""
    op.drop_index('ix_ingredient_store_availability_store_id', 'ingredient_store_availability')
    op.drop_index('ix_ingredient_store_availability_id', 'ingredient_store_availability')
    op.drop_table('ingredient_store_availability')
