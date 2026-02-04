"""Merge cream_cheese and main branches

Revision ID: 58e00bead79b
Revises: cream_cheese_01, skip_rules_01
Create Date: 2026-02-04 13:42:49.261509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58e00bead79b'
down_revision: Union[str, Sequence[str], None] = ('cream_cheese_01', 'skip_rules_01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
