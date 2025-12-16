"""add_customer_email_to_orders

Revision ID: 53ccd3ff25dd
Revises: bb88d8cca4a0
Create Date: 2025-12-16 10:32:06.025803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53ccd3ff25dd'
down_revision: Union[str, Sequence[str], None] = 'bb88d8cca4a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('orders', sa.Column('customer_email', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('orders', 'customer_email')
