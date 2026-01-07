"""Add loads_from_ingredients to item_type_attributes

Revision ID: l9m0n1o2p3q4
Revises: k8l9m0n1o2p3
Create Date: 2025-01-07

This migration adds columns to item_type_attributes that allow an attribute
to load its options from the ingredients table (via item_type_ingredients)
instead of from attribute_options.

This enables attributes like 'milk', 'sweetener', 'syrup' for beverages to
reference the same ingredients table used by food items, providing a unified
system for inventory management and 86'ing.

When loads_from_ingredients=True:
- Options come from item_type_ingredients filtered by ingredient_group
- Availability is determined by ingredients.is_available
- Prices come from item_type_ingredients.price_modifier

When loads_from_ingredients=False (default):
- Options come from attribute_options (existing behavior)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l9m0n1o2p3q4'
down_revision = 'k8l9m0n1o2p3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add loads_from_ingredients flag
    op.add_column(
        'item_type_attributes',
        sa.Column('loads_from_ingredients', sa.Boolean(), nullable=False, server_default='false')
    )

    # Add ingredient_group - links to item_type_ingredients.ingredient_group
    # when loads_from_ingredients is True
    op.add_column(
        'item_type_attributes',
        sa.Column('ingredient_group', sa.String(50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('item_type_attributes', 'ingredient_group')
    op.drop_column('item_type_attributes', 'loads_from_ingredients')
