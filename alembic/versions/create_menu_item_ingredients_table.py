"""Create menu_item_ingredients junction table

Revision ID: create_menu_item_ingredients
Revises: move_butter_spread
Create Date: 2026-01-22

This migration creates a junction table to establish a many-to-many relationship
between menu items and their default ingredients. This replaces the JSON-based
approach of storing ingredients in extra_metadata.default_config.

Benefits:
- Data integrity via FK constraints
- Accurate ingredient-based search
- Easier maintenance and querying
"""
from alembic import op
import sqlalchemy as sa


revision = 'create_menu_item_ingredients'
down_revision = 'move_butter_spread'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the junction table
    op.create_table(
        'menu_item_ingredients',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('menu_item_id', sa.Integer(), sa.ForeignKey('menu_items.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), sa.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create unique constraint
    op.create_unique_constraint(
        'uq_menu_item_ingredient',
        'menu_item_ingredients',
        ['menu_item_id', 'ingredient_id']
    )

    # Create indexes for efficient lookups
    op.create_index('idx_menu_item_ingredients_menu_item', 'menu_item_ingredients', ['menu_item_id'])
    op.create_index('idx_menu_item_ingredients_ingredient', 'menu_item_ingredients', ['ingredient_id'])


def downgrade() -> None:
    op.drop_index('idx_menu_item_ingredients_ingredient', 'menu_item_ingredients')
    op.drop_index('idx_menu_item_ingredients_menu_item', 'menu_item_ingredients')
    op.drop_constraint('uq_menu_item_ingredient', 'menu_item_ingredients', type_='unique')
    op.drop_table('menu_item_ingredients')
