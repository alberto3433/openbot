"""Add delivery_fee column to stores

Revision ID: e0b14c1ef231
Revises: dc0ef3a3ac30
Create Date: 2026-01-05 16:17:00.318472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0b14c1ef231'
down_revision: Union[str, Sequence[str], None] = 'dc0ef3a3ac30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add delivery_fee column to stores with default 2.99
    op.add_column(
        'stores',
        sa.Column('delivery_fee', sa.Float(), nullable=False, server_default='2.99')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('stores', 'delivery_fee')
