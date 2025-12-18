"""add timezone to stores

Revision ID: dc9c835db52b
Revises: 53ccd3ff25dd
Create Date: 2025-12-16 12:33:11.109859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc9c835db52b'
down_revision: Union[str, Sequence[str], None] = '53ccd3ff25dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stores', sa.Column('timezone', sa.String(), nullable=False, server_default='America/New_York'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('stores', 'timezone')
