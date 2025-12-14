"""add_base_price_to_ingredients

Revision ID: 61dd27d8ff1c
Revises: ee2f3d5d5f41
Create Date: 2025-12-13 22:15:19.974070

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61dd27d8ff1c'
down_revision: Union[str, Sequence[str], None] = 'ee2f3d5d5f41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('ingredients', sa.Column('base_price', sa.Float(), nullable=False, server_default='0.0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ingredients', 'base_price')
