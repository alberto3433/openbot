"""drop_ingredients_base_price

Revision ID: c5071c50236f
Revises: b5071c50235f
Create Date: 2026-01-20 15:10:00.000000

This migration removes the base_price column from ingredients table.
Pricing for ingredients is now managed exclusively via GlobalAttributeOption.price_modifier.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5071c50236f'
down_revision: Union[str, Sequence[str], None] = 'b5071c50235f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove base_price column from ingredients.

    Pricing is now managed via GlobalAttributeOption.price_modifier (where ingredient_id matches),
    not in Ingredient.base_price.

    Also drops the check constraint that enforced non-negative base_price.
    """
    # Drop the check constraint first (added in e1f2g3h4i5j6_add_database_integrity_constraints.py)
    op.drop_constraint('ck_ingredients_base_price_non_negative', 'ingredients', type_='check')
    # Drop the column
    op.drop_column('ingredients', 'base_price')


def downgrade() -> None:
    """Re-add base_price column to ingredients."""
    op.add_column(
        'ingredients',
        sa.Column('base_price', sa.Float(), nullable=False, server_default='0.0')
    )
    # Re-add the check constraint
    op.create_check_constraint(
        'ck_ingredients_base_price_non_negative',
        'ingredients',
        sa.column('base_price') >= 0
    )
