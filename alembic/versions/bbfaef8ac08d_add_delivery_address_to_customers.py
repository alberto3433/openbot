"""add_delivery_address_to_customers

Revision ID: bbfaef8ac08d
Revises: 2acf98f5eb09
Create Date: 2026-02-23 00:15:38.407949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbfaef8ac08d'
down_revision: Union[str, Sequence[str], None] = '2acf98f5eb09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('customers', sa.Column('delivery_address', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('customers', 'delivery_address')
