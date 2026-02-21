"""merge heads for payment_provider

Revision ID: bcd7f641e3bc
Revises: 9c46f370fddc, a1b2c3d4e5f8, z6b7c8d9e0f1
Create Date: 2026-02-20 23:28:51.330967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bcd7f641e3bc'
down_revision: Union[str, Sequence[str], None] = ('9c46f370fddc', 'a1b2c3d4e5f8', 'z6b7c8d9e0f1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
