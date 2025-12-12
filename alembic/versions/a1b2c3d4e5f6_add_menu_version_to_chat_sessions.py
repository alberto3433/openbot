"""add menu_version_sent to chat_sessions

Revision ID: a1b2c3d4e5f6
Revises: 54bf4cb0b74b
Create Date: 2025-12-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '54bf4cb0b74b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add menu_version_sent column to chat_sessions table."""
    # Check if the column already exists (for idempotent migrations)
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Get existing columns in chat_sessions table
    existing_columns = []
    if 'chat_sessions' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('chat_sessions')]

    # Add the column if it doesn't exist
    if 'menu_version_sent' not in existing_columns:
        op.add_column(
            'chat_sessions',
            sa.Column('menu_version_sent', sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Remove menu_version_sent column from chat_sessions table."""
    op.drop_column('chat_sessions', 'menu_version_sent')
