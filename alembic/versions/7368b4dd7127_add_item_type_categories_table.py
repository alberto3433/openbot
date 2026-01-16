"""add_item_type_categories_table

Revision ID: 7368b4dd7127
Revises: merge_sauce_into_topping
Create Date: 2026-01-15 16:48:40.760308

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '7368b4dd7127'
down_revision: Union[str, Sequence[str], None] = 'merge_sauce_into_topping'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Create item_type_categories table if it doesn't exist
    if 'item_type_categories' not in existing_tables:
        op.create_table(
            'item_type_categories',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('slug', sa.String(50), nullable=False),
            sa.Column('display_name', sa.String(100), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug'),
        )
        op.create_index('ix_item_type_categories_slug', 'item_type_categories', ['slug'], unique=True)

    # 2. Seed with "food" and "beverage" categories (if not already present)
    conn.execute(sa.text("""
        INSERT INTO item_type_categories (slug, display_name)
        VALUES ('food', 'Food'), ('beverage', 'Beverage')
        ON CONFLICT (slug) DO NOTHING
    """))

    # 3. Add FK column to item_types if it doesn't exist
    existing_columns = [col['name'] for col in inspector.get_columns('item_types')]
    if 'item_type_category_id' not in existing_columns:
        op.add_column('item_types', sa.Column('item_type_category_id', sa.Integer(), nullable=True))
        op.create_index('ix_item_types_item_type_category_id', 'item_types', ['item_type_category_id'], unique=False)
        op.create_foreign_key(
            'fk_item_types_item_type_category_id',
            'item_types', 'item_type_categories',
            ['item_type_category_id'], ['id'],
            ondelete='SET NULL'
        )

    # 4. Migrate existing modifier_category values to the new FK
    conn.execute(sa.text("""
        UPDATE item_types
        SET item_type_category_id = (
            SELECT id FROM item_type_categories WHERE slug = item_types.modifier_category
        )
        WHERE modifier_category IS NOT NULL AND item_type_category_id IS NULL
    """))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Remove FK and column from item_types
    existing_columns = [col['name'] for col in inspector.get_columns('item_types')]
    if 'item_type_category_id' in existing_columns:
        op.drop_constraint('fk_item_types_item_type_category_id', 'item_types', type_='foreignkey')
        op.drop_index('ix_item_types_item_type_category_id', table_name='item_types')
        op.drop_column('item_types', 'item_type_category_id')

    # Drop the categories table
    existing_tables = inspector.get_table_names()
    if 'item_type_categories' in existing_tables:
        op.drop_index('ix_item_type_categories_slug', table_name='item_type_categories')
        op.drop_table('item_type_categories')
