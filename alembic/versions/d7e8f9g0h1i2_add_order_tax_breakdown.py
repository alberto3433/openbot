"""add_order_tax_breakdown

Revision ID: d7e8f9g0h1i2
Revises: cf65216705b5
Create Date: 2025-12-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9g0h1i2'
down_revision: Union[str, Sequence[str], None] = 'cf65216705b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tax breakdown columns to orders table."""
    op.add_column('orders', sa.Column('subtotal', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column('city_tax', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column('state_tax', sa.Float(), nullable=True))
    op.add_column('orders', sa.Column('delivery_fee', sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove tax breakdown columns from orders table."""
    op.drop_column('orders', 'delivery_fee')
    op.drop_column('orders', 'state_tax')
    op.drop_column('orders', 'city_tax')
    op.drop_column('orders', 'subtotal')
