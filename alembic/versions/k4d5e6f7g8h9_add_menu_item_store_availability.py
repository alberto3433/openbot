"""add_menu_item_store_availability

Revision ID: k4d5e6f7g8h9
Revises: j3c4d5e6f7g8
Create Date: 2025-12-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k4d5e6f7g8h9'
down_revision: Union[str, Sequence[str], None] = 'j3c4d5e6f7g8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create menu_item_store_availability table for per-store 86 tracking."""
    op.create_table(
        'menu_item_store_availability',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.String(), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False, default=True),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('menu_item_id', 'store_id', name='uix_menu_item_store')
    )
    op.create_index('ix_menu_item_store_availability_id', 'menu_item_store_availability', ['id'])
    op.create_index('ix_menu_item_store_availability_store_id', 'menu_item_store_availability', ['store_id'])


def downgrade() -> None:
    """Drop menu_item_store_availability table."""
    op.drop_index('ix_menu_item_store_availability_store_id', 'menu_item_store_availability')
    op.drop_index('ix_menu_item_store_availability_id', 'menu_item_store_availability')
    op.drop_table('menu_item_store_availability')
