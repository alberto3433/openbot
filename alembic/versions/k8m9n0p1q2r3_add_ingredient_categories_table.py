"""add_ingredient_categories_table

Revision ID: k8m9n0p1q2r3
Revises: 7fd7d275d405
Create Date: 2026-01-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k8m9n0p1q2r3'
down_revision: Union[str, Sequence[str], None] = '7fd7d275d405'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Initial ingredient categories with their modifier types
INGREDIENT_CATEGORIES = [
    # Food modifiers (used on bagels, sandwiches, omelettes, etc.)
    {"slug": "protein", "display_name": "Proteins", "modifier_type": "food", "display_order": 1},
    {"slug": "topping", "display_name": "Toppings", "modifier_type": "food", "display_order": 2},
    {"slug": "sauce", "display_name": "Sauces", "modifier_type": "food", "display_order": 3},
    {"slug": "cheese", "display_name": "Cheeses", "modifier_type": "food", "display_order": 4},
    {"slug": "spread", "display_name": "Spreads", "modifier_type": "food", "display_order": 5},
    # Beverage modifiers (used on coffee, tea, etc.)
    {"slug": "milk", "display_name": "Milks", "modifier_type": "beverage", "display_order": 10},
    {"slug": "sweetener", "display_name": "Sweeteners", "modifier_type": "beverage", "display_order": 11},
    {"slug": "syrup", "display_name": "Syrups", "modifier_type": "beverage", "display_order": 12},
    # Non-modifier categories
    {"slug": "bread", "display_name": "Breads", "modifier_type": None, "display_order": 20},
]


def upgrade() -> None:
    """Create ingredient_categories table and populate with initial data."""
    # Create the table
    op.create_table(
        'ingredient_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('modifier_type', sa.String(length=20), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ingredient_categories_id'), 'ingredient_categories', ['id'], unique=False)
    op.create_index(op.f('ix_ingredient_categories_slug'), 'ingredient_categories', ['slug'], unique=True)

    # Populate with initial data
    ingredient_categories = sa.table(
        'ingredient_categories',
        sa.column('slug', sa.String),
        sa.column('display_name', sa.String),
        sa.column('modifier_type', sa.String),
        sa.column('display_order', sa.Integer),
    )

    op.bulk_insert(ingredient_categories, INGREDIENT_CATEGORIES)


def downgrade() -> None:
    """Drop ingredient_categories table."""
    op.drop_index(op.f('ix_ingredient_categories_slug'), table_name='ingredient_categories')
    op.drop_index(op.f('ix_ingredient_categories_id'), table_name='ingredient_categories')
    op.drop_table('ingredient_categories')
