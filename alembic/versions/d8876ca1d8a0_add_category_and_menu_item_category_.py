"""add_category_and_menu_item_category_tables

Revision ID: d8876ca1d8a0
Revises: 96d2570f0921
Create Date: 2026-01-13 23:44:01.076748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8876ca1d8a0'
down_revision: Union[str, Sequence[str], None] = '96d2570f0921'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create Category and MenuItemCategory tables for many-to-many categorization."""
    # Create categories table (lookup table for predefined categories)
    op.create_table(
        'categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_categories_id', 'categories', ['id'])
    op.create_index('ix_categories_slug', 'categories', ['slug'])

    # Create menu_item_categories join table (many-to-many)
    op.create_table(
        'menu_item_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('menu_item_id', 'category_id', name='uix_menu_item_category'),
    )
    op.create_index('ix_menu_item_categories_id', 'menu_item_categories', ['id'])
    op.create_index('ix_menu_item_categories_menu_item_id', 'menu_item_categories', ['menu_item_id'])
    op.create_index('ix_menu_item_categories_category_id', 'menu_item_categories', ['category_id'])

    # Seed initial categories: drink and food
    op.execute("""
        INSERT INTO categories (name, slug, description)
        VALUES
            ('Drink', 'drink', 'Beverages including coffee, tea, juice, and sodas'),
            ('Food', 'food', 'Food items including bagels, sandwiches, and sides')
    """)


def downgrade() -> None:
    """Drop Category and MenuItemCategory tables."""
    op.drop_table('menu_item_categories')
    op.drop_table('categories')
