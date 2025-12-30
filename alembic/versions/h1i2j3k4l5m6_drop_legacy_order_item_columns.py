"""drop_legacy_order_item_columns

Revision ID: h1i2j3k4l5m6
Revises: fae6b60169dd
Create Date: 2025-12-30

This migration removes the legacy columns from order_items table.
All item-specific data is now stored in the item_config JSON column.

Dropped columns:
- item_type (String) - now stored in item_config
- size (String) - now stored in item_config
- bread (String) - now stored in item_config
- protein (String) - now stored in item_config
- cheese (String) - now stored in item_config
- toppings (JSON) - now stored in item_config
- sauces (JSON) - now stored in item_config
- toasted (Boolean) - now stored in item_config
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, Sequence[str], None] = 'fae6b60169dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop legacy columns from order_items table."""
    op.drop_column('order_items', 'item_type')
    op.drop_column('order_items', 'size')
    op.drop_column('order_items', 'bread')
    op.drop_column('order_items', 'protein')
    op.drop_column('order_items', 'cheese')
    op.drop_column('order_items', 'toppings')
    op.drop_column('order_items', 'sauces')
    op.drop_column('order_items', 'toasted')


def downgrade() -> None:
    """Re-add legacy columns to order_items table."""
    op.add_column('order_items', sa.Column('toasted', sa.Boolean(), nullable=True))
    op.add_column('order_items', sa.Column('sauces', sa.JSON(), nullable=True))
    op.add_column('order_items', sa.Column('toppings', sa.JSON(), nullable=True))
    op.add_column('order_items', sa.Column('cheese', sa.String(), nullable=True))
    op.add_column('order_items', sa.Column('protein', sa.String(), nullable=True))
    op.add_column('order_items', sa.Column('bread', sa.String(), nullable=True))
    op.add_column('order_items', sa.Column('size', sa.String(), nullable=True))
    op.add_column('order_items', sa.Column('item_type', sa.String(), nullable=True))
