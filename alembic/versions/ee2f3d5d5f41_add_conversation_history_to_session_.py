"""add_conversation_history_to_session_analytics

Revision ID: ee2f3d5d5f41
Revises: 07e15eb0609b
Create Date: 2025-12-13 21:44:39.665660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee2f3d5d5f41'
down_revision: Union[str, Sequence[str], None] = '07e15eb0609b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('session_analytics', sa.Column('conversation_history', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('session_analytics', 'conversation_history')
