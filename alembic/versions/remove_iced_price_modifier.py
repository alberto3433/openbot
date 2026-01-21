"""Remove unused iced_price_modifier column from global_attribute_options

Revision ID: remove_iced_price_modifier
Revises: fix_syrup_price_02
Create Date: 2026-01-20

This column was added but never used. Iced drinks are handled as separate
menu items, not via a price modifier on size options.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'remove_iced_price_modifier'
down_revision: Union[str, Sequence[str], None] = 'fix_syrup_price_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the iced_price_modifier column."""
    op.drop_column('global_attribute_options', 'iced_price_modifier')


def downgrade() -> None:
    """Re-add iced_price_modifier column."""
    op.add_column(
        'global_attribute_options',
        sa.Column('iced_price_modifier', sa.Float(), nullable=False, server_default='0.0')
    )
