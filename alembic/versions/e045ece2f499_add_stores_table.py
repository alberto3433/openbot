"""add_stores_table

Revision ID: e045ece2f499
Revises: c9ed57ad9ff2
Create Date: 2025-12-14 17:32:27.936288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e045ece2f499'
down_revision: Union[str, Sequence[str], None] = 'c9ed57ad9ff2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create stores table for multi-location support."""
    op.create_table(
        'stores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('address', sa.String(), nullable=False),
        sa.Column('city', sa.String(), nullable=False),
        sa.Column('state', sa.String(2), nullable=False),
        sa.Column('zip_code', sa.String(10), nullable=False),
        sa.Column('phone', sa.String(), nullable=False),
        sa.Column('hours', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='open'),
        sa.Column('payment_methods', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('store_id')
    )
    op.create_index('ix_stores_id', 'stores', ['id'])
    op.create_index('ix_stores_store_id', 'stores', ['store_id'])


def downgrade() -> None:
    """Drop stores table."""
    op.drop_index('ix_stores_store_id', 'stores')
    op.drop_index('ix_stores_id', 'stores')
    op.drop_table('stores')
