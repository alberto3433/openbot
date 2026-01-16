"""drop menu_item category column

Revision ID: drop_menu_item_category_column
Revises: migrate_by_pound_drop_base_price
Create Date: 2026-01-15

This migration removes the obsolete `category` string column from menu_items.

Background:
-----------
The `category` column was a legacy field that stored item categorization as a
free-form string. This has been superseded by two better mechanisms:

1. `item_type_id` - Links to ItemType for item type identification (bagel, beverage, etc.)
2. `menu_item_categories` join table - Many-to-many relationship with the `categories`
   table for proper categorization (drink, food, soda, etc.)

The old `category` column contained inconsistent data (mix of display names,
slugs, and item types) and is no longer needed.

Code Updates Required:
---------------------
Before running this migration, ensure the following code has been updated:
- MenuItemOut schema: Remove `category` field or derive from item_type
- MenuItemCreate/Update schemas: Remove `category` field
- admin_menu.py: Remove category handling in create/update
- menu_index_builder.py: Use item_type.display_name instead of item.category
- helpers.py: Update serialize functions
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'drop_menu_item_category_column'
down_revision: Union[str, Sequence[str], None] = 'migrate_by_pound_drop_base_price'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the obsolete category column from menu_items."""
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_columns = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'category' in existing_columns:
        op.drop_column('menu_items', 'category')
        print("  Dropped 'category' column from menu_items table")
    else:
        print("  'category' column already dropped")


def downgrade() -> None:
    """Re-add category column (data will not be restored)."""
    op.add_column('menu_items', sa.Column('category', sa.String(), nullable=False, server_default=''))

    # Populate from item_type display_name where available
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE menu_items m
        SET category = COALESCE(
            (SELECT it.display_name FROM item_types it WHERE it.id = m.item_type_id),
            ''
        )
    """))
