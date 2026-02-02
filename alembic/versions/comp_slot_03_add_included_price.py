"""Add included_price_cents to component_slot_options

Revision ID: comp_slot_03
Revises: comp_slot_02
Create Date: 2026-02-01

This migration adds the included_price_cents column for differential pricing.
When an item type has size variants (like fruit salad), this allows specifying
the base amount included in the parent's price.

Examples:
- Bagel: included_price_cents=NULL (entire base is free, upcharges apply)
- Fruit Salad: included_price_cents=795 (small fruit salad price of $7.95 is included,
  so large fruit salad only charges the $2.00 difference)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'comp_slot_03'
down_revision: Union[str, Sequence[str], None] = 'comp_slot_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add included_price_cents column to component_slot_options."""
    op.add_column(
        'component_slot_options',
        sa.Column('included_price_cents', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    """Remove included_price_cents column from component_slot_options."""
    op.drop_column('component_slot_options', 'included_price_cents')
