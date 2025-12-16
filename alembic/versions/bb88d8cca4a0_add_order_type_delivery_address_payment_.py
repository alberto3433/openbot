"""Add order_type delivery_address payment fields to orders

Revision ID: bb88d8cca4a0
Revises: l5e6f7g8h9i0
Create Date: 2025-12-16 00:03:12.815432

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bb88d8cca4a0'
down_revision: Union[str, Sequence[str], None] = 'l5e6f7g8h9i0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('order_type', sa.String(), nullable=False, server_default='pickup'))
    op.add_column('orders', sa.Column('delivery_address', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('payment_status', sa.String(), nullable=False, server_default='unpaid'))
    op.add_column('orders', sa.Column('payment_method', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'payment_method')
    op.drop_column('orders', 'payment_status')
    op.drop_column('orders', 'delivery_address')
    op.drop_column('orders', 'order_type')
