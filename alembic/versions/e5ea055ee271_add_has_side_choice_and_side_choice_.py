"""Add has_side_choice and side_choice_attribute_id to item_types

Revision ID: e5ea055ee271
Revises: drop_item_type_virtual_columns
Create Date: 2026-01-16 15:19:15.181029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5ea055ee271'
down_revision: Union[str, Sequence[str], None] = 'drop_item_type_virtual_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add has_side_choice boolean column with default false
    op.add_column(
        'item_types',
        sa.Column('has_side_choice', sa.Boolean(), nullable=False, server_default='false')
    )
    # Add side_choice_attribute_id FK column
    op.add_column(
        'item_types',
        sa.Column('side_choice_attribute_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_item_types_side_choice_attribute',
        'item_types',
        'item_type_attributes',
        ['side_choice_attribute_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_item_types_side_choice_attribute', 'item_types', type_='foreignkey')
    op.drop_column('item_types', 'side_choice_attribute_id')
    op.drop_column('item_types', 'has_side_choice')
