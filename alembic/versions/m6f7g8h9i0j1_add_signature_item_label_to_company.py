"""add signature_item_label to company

Revision ID: m6f7g8h9i0j1
Revises: dc9c835db52b
Create Date: 2025-12-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm6f7g8h9i0j1'
down_revision: Union[str, Sequence[str], None] = 'dc9c835db52b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('company', sa.Column('signature_item_label', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('company', 'signature_item_label')
