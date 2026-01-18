"""add is_regex column to response_pattern

Revision ID: 082a2cf2a883
Revises: e5ea055ee271
Create Date: 2026-01-17 21:42:25.410087

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '082a2cf2a883'
down_revision: Union[str, Sequence[str], None] = 'e5ea055ee271'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_regex column to response_pattern table."""
    op.add_column(
        'response_pattern',
        sa.Column('is_regex', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    """Remove is_regex column from response_pattern table."""
    op.drop_column('response_pattern', 'is_regex')
