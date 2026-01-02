"""Add iced_price_modifier to attribute_options

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-01-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j3k4l5m6n7o8'
down_revision: Union[str, Sequence[str], None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add iced_price_modifier column for size-dependent iced upcharges."""
    op.add_column(
        'attribute_options',
        sa.Column('iced_price_modifier', sa.Float(), nullable=False, server_default='0.0')
    )


def downgrade() -> None:
    """Remove iced_price_modifier column."""
    op.drop_column('attribute_options', 'iced_price_modifier')
