"""add_must_match_to_ingredients

Revision ID: 77bcd21f5bf2
Revises: o9p0q1r2s3t5
Create Date: 2026-01-08 23:15:19.818877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77bcd21f5bf2'
down_revision: Union[str, Sequence[str], None] = 'o9p0q1r2s3t5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add must_match column to ingredients table."""
    op.add_column(
        'ingredients',
        sa.Column('must_match', sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove must_match column from ingredients table."""
    op.drop_column('ingredients', 'must_match')
