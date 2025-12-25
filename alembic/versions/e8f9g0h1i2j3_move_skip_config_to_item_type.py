"""Move skip_config from MenuItem to ItemType

Revision ID: e8f9g0h1i2j3
Revises: 035be2e89964
Create Date: 2025-12-23 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f9g0h1i2j3'
down_revision: Union[str, Sequence[str], None] = '035be2e89964'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - move skip_config from menu_items to item_types."""
    # Add skip_config to item_types table
    op.add_column('item_types', sa.Column('skip_config', sa.Boolean(), nullable=False, server_default='false'))

    # Remove skip_config from menu_items table
    op.drop_column('menu_items', 'skip_config')


def downgrade() -> None:
    """Downgrade schema - move skip_config back to menu_items."""
    # Add skip_config back to menu_items
    op.add_column('menu_items', sa.Column('skip_config', sa.Boolean(), nullable=False, server_default='false'))

    # Remove skip_config from item_types
    op.drop_column('item_types', 'skip_config')
