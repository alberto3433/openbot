"""add_unique_constraint_on_menu_item_name

Revision ID: 3c21925714be
Revises: 40602bcb141d
Create Date: 2026-01-06 22:51:29.237899

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '3c21925714be'
down_revision: Union[str, Sequence[str], None] = '40602bcb141d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on menu_items.name."""
    op.create_unique_constraint('uq_menu_items_name', 'menu_items', ['name'])


def downgrade() -> None:
    """Remove unique constraint on menu_items.name."""
    op.drop_constraint('uq_menu_items_name', 'menu_items', type_='unique')
