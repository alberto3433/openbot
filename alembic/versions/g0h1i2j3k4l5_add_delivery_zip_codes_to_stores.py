"""add_delivery_zip_codes_to_stores

Revision ID: g0h1i2j3k4l5
Revises: f9g0h1i2j3k4
Create Date: 2025-12-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g0h1i2j3k4l5'
down_revision: Union[str, Sequence[str], None] = 'f9g0h1i2j3k4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add delivery_zip_codes column to stores table."""
    op.add_column('stores', sa.Column('delivery_zip_codes', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Remove delivery_zip_codes column from stores table."""
    op.drop_column('stores', 'delivery_zip_codes')
