"""Add item_type_ingredients table

Revision ID: k8l9m0n1o2p3
Revises: 0dca7d5b8668
Create Date: 2025-01-07

This migration creates the item_type_ingredients table which links ingredients
to item types with configuration specific to that item type (price modifiers,
display order, defaults, etc.).

This enables a unified ingredient system where physical items like milk,
sweeteners, and syrups can be managed alongside proteins, toppings, and spreads
in a single ingredients table, with per-item-type configuration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'k8l9m0n1o2p3'
down_revision = '0dca7d5b8668'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the item_type_ingredients table
    op.create_table(
        'item_type_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_type_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),

        # Grouping - which selector/category this appears in
        # e.g., 'milk', 'sweetener', 'syrup', 'spread', 'protein', 'topping', 'cheese'
        sa.Column('ingredient_group', sa.String(50), nullable=False),

        # Pricing - can vary by item type (oat milk might cost different for latte vs iced coffee)
        sa.Column('price_modifier', sa.Numeric(10, 2), nullable=False, server_default='0.00'),

        # Display configuration
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('display_name_override', sa.String(100), nullable=True),  # e.g., "Oat" instead of "Oat Milk"

        # Selection behavior
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='true'),  # Per-item-type override

        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),

        # Primary key
        sa.PrimaryKeyConstraint('id'),

        # Foreign keys
        sa.ForeignKeyConstraint(['item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='CASCADE'),

        # Unique constraint - one entry per item_type + ingredient + group combination
        sa.UniqueConstraint('item_type_id', 'ingredient_id', 'ingredient_group', name='uq_item_type_ingredient_group'),
    )

    # Create indexes for efficient lookups
    op.create_index('idx_item_type_ingredients_item_type', 'item_type_ingredients', ['item_type_id'])
    op.create_index('idx_item_type_ingredients_ingredient', 'item_type_ingredients', ['ingredient_id'])
    op.create_index('idx_item_type_ingredients_group', 'item_type_ingredients', ['ingredient_group'])
    op.create_index('idx_item_type_ingredients_item_type_group', 'item_type_ingredients', ['item_type_id', 'ingredient_group'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_item_type_ingredients_item_type_group', table_name='item_type_ingredients')
    op.drop_index('idx_item_type_ingredients_group', table_name='item_type_ingredients')
    op.drop_index('idx_item_type_ingredients_ingredient', table_name='item_type_ingredients')
    op.drop_index('idx_item_type_ingredients_item_type', table_name='item_type_ingredients')

    # Drop table
    op.drop_table('item_type_ingredients')
