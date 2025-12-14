"""add_is_available_to_ingredients

Revision ID: c041faf84a65
Revises: 61dd27d8ff1c
Create Date: 2025-12-14 00:12:24.143204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c041faf84a65'
down_revision: Union[str, Sequence[str], None] = '61dd27d8ff1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_available column to ingredients table."""
    # Check if column already exists (for idempotency)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('ingredients')]

    if 'is_available' not in columns:
        op.add_column('ingredients', sa.Column('is_available', sa.Boolean(), nullable=False, server_default='1'))


def downgrade() -> None:
    """Remove is_available column from ingredients table."""
    op.drop_column('ingredients', 'is_available')
