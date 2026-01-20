"""drop_item_type_ingredients_price_modifier

Revision ID: b5071c50235f
Revises: add_toasted_scooped_opts_001
Create Date: 2026-01-20 14:55:15.094117

This migration removes the price_modifier column from item_type_ingredients table.
Pricing for ingredients is now managed exclusively via GlobalAttributeOption.price_modifier.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5071c50235f'
down_revision: Union[str, Sequence[str], None] = 'add_toasted_scooped_opts_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove price_modifier column from item_type_ingredients.

    Pricing is now managed via GlobalAttributeOption.price_modifier (where ingredient_id matches),
    not in ItemTypeIngredient.
    """
    op.drop_column('item_type_ingredients', 'price_modifier')


def downgrade() -> None:
    """Re-add price_modifier column to item_type_ingredients."""
    op.add_column(
        'item_type_ingredients',
        sa.Column('price_modifier', sa.NUMERIC(precision=10, scale=2), nullable=False, server_default='0')
    )
