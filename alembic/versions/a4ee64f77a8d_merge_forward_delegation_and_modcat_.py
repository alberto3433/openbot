"""Merge forward_delegation and modcat migrations

Revision ID: a4ee64f77a8d
Revises: forward_delegation_01, modcat01
Create Date: 2026-02-08 16:57:23.958878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4ee64f77a8d'
down_revision: Union[str, Sequence[str], None] = ('forward_delegation_01', 'modcat01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
