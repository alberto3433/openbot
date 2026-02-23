"""add preferred_voice to customers

Revision ID: 2acf98f5eb09
Revises: d2e3f4g5h6i7
Create Date: 2026-02-22 21:21:41.393047

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2acf98f5eb09'
down_revision: Union[str, Sequence[str], None] = 'd2e3f4g5h6i7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('customers', sa.Column('preferred_voice', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('customers', 'preferred_voice')
