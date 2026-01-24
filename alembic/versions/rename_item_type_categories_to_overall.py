"""rename_item_type_categories_to_overall_categories

Revision ID: rename_item_type_categories_to_overall
Revises: add_global_attr_option_aliases
Create Date: 2026-01-24

Renames:
- Table: item_type_categories -> overall_categories
- Column: item_types.item_type_category_id -> item_types.overall_category_id
- Updates related indexes and foreign key constraints

This rename better reflects the dual purpose of this table:
1. Classifying item types (bagel -> food, coffee -> beverage)
2. Classifying ingredient categories via modifier_type field
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'rename_item_type_categories_to_overall'
down_revision: Union[str, Sequence[str], None] = 'add_global_attr_option_aliases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename item_type_categories to overall_categories."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # 1. Drop the FK constraint on item_types.item_type_category_id
    op.drop_constraint('fk_item_types_item_type_category_id', 'item_types', type_='foreignkey')

    # 2. Drop the index on item_types.item_type_category_id
    op.drop_index('ix_item_types_item_type_category_id', table_name='item_types')

    # 3. Rename the column in item_types
    op.alter_column('item_types', 'item_type_category_id', new_column_name='overall_category_id')

    # 4. Drop the index on item_type_categories.slug
    op.drop_index('ix_item_type_categories_slug', table_name='item_type_categories')

    # 5. Rename the table
    op.rename_table('item_type_categories', 'overall_categories')

    # 6. Re-create the index on overall_categories.slug
    op.create_index('ix_overall_categories_slug', 'overall_categories', ['slug'], unique=True)

    # 7. Re-create the index on item_types.overall_category_id
    op.create_index('ix_item_types_overall_category_id', 'item_types', ['overall_category_id'], unique=False)

    # 8. Re-create the FK constraint with new names
    op.create_foreign_key(
        'fk_item_types_overall_category_id',
        'item_types', 'overall_categories',
        ['overall_category_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Revert: rename overall_categories back to item_type_categories."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # 1. Drop the FK constraint
    op.drop_constraint('fk_item_types_overall_category_id', 'item_types', type_='foreignkey')

    # 2. Drop the index on item_types.overall_category_id
    op.drop_index('ix_item_types_overall_category_id', table_name='item_types')

    # 3. Rename the column back
    op.alter_column('item_types', 'overall_category_id', new_column_name='item_type_category_id')

    # 4. Drop the index on overall_categories.slug
    op.drop_index('ix_overall_categories_slug', table_name='overall_categories')

    # 5. Rename the table back
    op.rename_table('overall_categories', 'item_type_categories')

    # 6. Re-create the index on item_type_categories.slug
    op.create_index('ix_item_type_categories_slug', 'item_type_categories', ['slug'], unique=True)

    # 7. Re-create the index on item_types.item_type_category_id
    op.create_index('ix_item_types_item_type_category_id', 'item_types', ['item_type_category_id'], unique=False)

    # 8. Re-create the FK constraint with old names
    op.create_foreign_key(
        'fk_item_types_item_type_category_id',
        'item_types', 'item_type_categories',
        ['item_type_category_id'], ['id'],
        ondelete='SET NULL'
    )
