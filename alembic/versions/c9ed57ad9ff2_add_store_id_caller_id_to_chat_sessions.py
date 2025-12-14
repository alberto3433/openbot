"""add_store_id_caller_id_to_chat_sessions

Revision ID: c9ed57ad9ff2
Revises: k4d5e6f7g8h9
Create Date: 2025-12-14 16:35:25.512237

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9ed57ad9ff2'
down_revision: Union[str, Sequence[str], None] = 'k4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add store_id and caller_id columns to chat_sessions for per-store availability."""
    op.add_column('chat_sessions', sa.Column('store_id', sa.String(), nullable=True))
    op.add_column('chat_sessions', sa.Column('caller_id', sa.String(), nullable=True))
    op.create_index('ix_chat_sessions_store_id', 'chat_sessions', ['store_id'])


def downgrade() -> None:
    """Remove store_id and caller_id columns from chat_sessions."""
    op.drop_index('ix_chat_sessions_store_id', 'chat_sessions')
    op.drop_column('chat_sessions', 'caller_id')
    op.drop_column('chat_sessions', 'store_id')
