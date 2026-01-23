"""Drop extra_metadata column from menu_items

Revision ID: drop_extra_metadata_column
Revises: populate_menu_item_ingredients
Create Date: 2026-01-22

This migration removes the extra_metadata column from the menu_items table.
The column was previously used to store default_config JSON for signature items,
but this data has been migrated to the menu_item_ingredients junction table.

The column is no longer read by any code, so it can be safely dropped.
"""
from alembic import op
import sqlalchemy as sa


revision = 'drop_extra_metadata_column'
down_revision = 'populate_menu_item_ingredients'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the extra_metadata column - data has been migrated to menu_item_ingredients
    op.drop_column('menu_items', 'extra_metadata')


def downgrade() -> None:
    # Recreate the column (but data will be lost)
    op.add_column('menu_items', sa.Column('extra_metadata', sa.Text(), nullable=True))
