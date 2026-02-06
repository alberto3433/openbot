"""Add quantity_per_unit column to menu_items

Allows menu items to specify how many items come in a single order unit.
For example, "Chocolate Dipped Macaroons" with unit_type='pack' and
quantity_per_unit=3 displays as "(3 pack)" to users.

Revision ID: add_qty_per_unit_01
Revises: drop_categories_01
Create Date: 2026-02-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'add_qty_per_unit_01'
down_revision: Union[str, None] = 'drop_categories_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add quantity_per_unit column
    # NULL means single item (same as 1)
    op.add_column(
        'menu_items',
        sa.Column('quantity_per_unit', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('menu_items', 'quantity_per_unit')
