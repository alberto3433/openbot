"""Remove is_configurable and skip_config columns from item_types

Revision ID: r6s7t8u9v0w1
Revises: 57a09fe179d1
Create Date: 2026-01-09 12:00:00.000000

This migration removes the is_configurable and skip_config columns from the
item_types table. These values are now derived from linked global attributes:
- is_configurable = True if item type has ANY linked global attributes
- skip_config = True if item type has NO attributes with ask_in_conversation=True

Use sandwich_bot.services.item_type_helpers for these derived values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r6s7t8u9v0w1'
down_revision: Union[str, Sequence[str], None] = '57a09fe179d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove is_configurable and skip_config columns from item_types."""
    conn = op.get_bind()

    # Check if columns exist before trying to remove them
    result = conn.execute(sa.text("SELECT column_name FROM information_schema.columns WHERE table_name = 'item_types'"))
    columns = [row[0] for row in result]

    # Use batch_alter_table for compatibility
    with op.batch_alter_table('item_types') as batch_op:
        if 'is_configurable' in columns:
            batch_op.drop_column('is_configurable')
        if 'skip_config' in columns:
            batch_op.drop_column('skip_config')


def downgrade() -> None:
    """Re-add is_configurable and skip_config columns."""
    with op.batch_alter_table('item_types') as batch_op:
        batch_op.add_column(sa.Column('is_configurable', sa.Boolean(), nullable=False, server_default='true'))
        batch_op.add_column(sa.Column('skip_config', sa.Boolean(), nullable=False, server_default='false'))

    # Remove server defaults after adding columns
    with op.batch_alter_table('item_types') as batch_op:
        batch_op.alter_column('is_configurable', server_default=None)
        batch_op.alter_column('skip_config', server_default=None)
