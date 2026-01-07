"""make attribute_definition_id nullable

Revision ID: 40602bcb141d
Revises: 5f7a8b9c0d1e
Create Date: 2026-01-06 13:58:56.848918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40602bcb141d'
down_revision: Union[str, Sequence[str], None] = '5f7a8b9c0d1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make attribute_definition_id nullable to support new item_type_attribute_id FK."""
    # Make attribute_definition_id nullable (transitioning to item_type_attribute_id)
    op.alter_column('attribute_options', 'attribute_definition_id',
               existing_type=sa.INTEGER(),
               nullable=True)

    # Add index on item_type_attribute_id for efficient lookups
    op.create_index(
        'ix_attribute_options_item_type_attribute_id',
        'attribute_options',
        ['item_type_attribute_id'],
        unique=False,
        if_not_exists=True
    )


def downgrade() -> None:
    """Revert attribute_definition_id to non-nullable."""
    op.drop_index('ix_attribute_options_item_type_attribute_id', table_name='attribute_options', if_exists=True)
    op.alter_column('attribute_options', 'attribute_definition_id',
               existing_type=sa.INTEGER(),
               nullable=False)
