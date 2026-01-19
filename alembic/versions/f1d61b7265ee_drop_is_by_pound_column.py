"""drop_is_by_pound_column

Revision ID: f1d61b7265ee
Revises: add_standalone_instruction_001
Create Date: 2026-01-19 01:59:04.347065

This migration removes the redundant is_by_pound column from item_types.
Items sold by weight are now identified by MenuItem.unit_type = 'by_weight'.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1d61b7265ee'
down_revision: Union[str, Sequence[str], None] = 'add_standalone_instruction_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the redundant is_by_pound column from item_types."""
    op.drop_column('item_types', 'is_by_pound')


def downgrade() -> None:
    """Restore is_by_pound column on item_types."""
    op.add_column(
        'item_types',
        sa.Column(
            'is_by_pound',
            sa.BOOLEAN(),
            server_default=sa.text('false'),
            nullable=False
        )
    )
