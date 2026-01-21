"""Move special_instructions from OrderItem.notes to Order.special_instructions

Revision ID: move_special_instructions_to_order
Revises: remove_iced_price_modifier
Create Date: 2025-01-20

This migration:
1. Adds special_instructions TEXT column to orders table
2. Drops notes column from order_items table
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'move_special_instructions_to_order'
down_revision: Union[str, Sequence[str], None] = 'remove_iced_price_modifier'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add special_instructions column to orders table
    op.add_column('orders', sa.Column('special_instructions', sa.Text(), nullable=True))

    # Drop notes column from order_items table
    op.drop_column('order_items', 'notes')


def downgrade() -> None:
    # Re-add notes column to order_items table
    op.add_column('order_items', sa.Column('notes', sa.String(), nullable=True))

    # Drop special_instructions column from orders table
    op.drop_column('orders', 'special_instructions')
