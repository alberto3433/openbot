"""Drop categories and menu_item_categories tables

These tables are no longer used - categories are now derived from:
menu_item -> item_type -> display_group -> overall_category

Revision ID: drop_categories_01
Revises: 7508fc64a9f6
Create Date: 2025-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'drop_categories_01'
down_revision: Union[str, None] = '7508fc64a9f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop menu_item_categories first (has FKs to both tables)
    op.drop_table('menu_item_categories')

    # Then drop categories
    op.drop_table('categories')


def downgrade() -> None:
    # Recreate categories table
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index(op.f('ix_categories_id'), 'categories', ['id'], unique=False)
    op.create_index(op.f('ix_categories_slug'), 'categories', ['slug'], unique=False)

    # Recreate menu_item_categories junction table
    op.create_table(
        'menu_item_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('menu_item_id', 'category_id', name='uix_menu_item_category'),
    )
    op.create_index(op.f('ix_menu_item_categories_id'), 'menu_item_categories', ['id'], unique=False)
    op.create_index(op.f('ix_menu_item_categories_menu_item_id'), 'menu_item_categories', ['menu_item_id'], unique=False)
    op.create_index(op.f('ix_menu_item_categories_category_id'), 'menu_item_categories', ['category_id'], unique=False)
