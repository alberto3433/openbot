"""drop item_types virtual category columns

Revision ID: drop_item_type_virtual_columns
Revises: drop_menu_item_category_column
Create Date: 2026-01-15

This migration removes three obsolete columns from item_types:
- expands_to: JSON array of slugs for meta-categories
- is_virtual: Boolean flag for virtual/meta categories
- name_filter: String filter for item names

Background:
-----------
These columns were used for "virtual" item types that expanded to other types.
For example, "sandwich" was a virtual type that expanded to ["egg_sandwich",
"fish_sandwich", "deli_sandwich", etc.].

This approach has been replaced by the categories table and menu_item_category
join table, which provides a cleaner many-to-many relationship between menu
items and categories. Now:
- "Bacon Egg Cheese" belongs to category "sandwich" via menu_item_category
- Querying "what sandwiches do you have?" queries via the join table

The new approach:
1. Categories are stored in the `categories` table
2. Menu items link to categories via `menu_item_category` join table
3. menu_cache._load_category_keywords() loads both ItemTypes and Categories
4. lookup_type field ("item_type" or "category") determines query method
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'drop_item_type_virtual_columns'
down_revision = 'drop_menu_item_category_column'
branch_labels = None
depends_on = None


def upgrade():
    """Drop expands_to, is_virtual, and name_filter columns from item_types."""
    # Drop the columns
    op.drop_column('item_types', 'expands_to')
    op.drop_column('item_types', 'is_virtual')
    op.drop_column('item_types', 'name_filter')


def downgrade():
    """Re-add the columns (without data - would need separate data migration)."""
    op.add_column('item_types', sa.Column('expands_to', sa.JSON(), nullable=True))
    op.add_column('item_types', sa.Column('is_virtual', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('item_types', sa.Column('name_filter', sa.String(), nullable=True))
