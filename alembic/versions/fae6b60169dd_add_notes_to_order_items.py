"""add_notes_to_order_items

Revision ID: fae6b60169dd
Revises: g0h1i2j3k4l5
Create Date: 2025-12-27 23:14:12.361943

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fae6b60169dd'
down_revision: Union[str, Sequence[str], None] = 'g0h1i2j3k4l5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('order_items', sa.Column('notes', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('order_items', 'notes')
