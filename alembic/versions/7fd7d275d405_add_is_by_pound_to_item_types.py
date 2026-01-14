"""add_is_by_pound_to_item_types

Revision ID: 7fd7d275d405
Revises: h3i4j5k6l7m8
Create Date: 2026-01-13 19:16:41.402512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7fd7d275d405'
down_revision: Union[str, Sequence[str], None] = 'h3i4j5k6l7m8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ItemTypes that are sold by-the-pound
BY_POUND_SLUGS = ["cheese", "cold_cut", "fish", "salad", "spread"]


def upgrade() -> None:
    """Add is_by_pound column to item_types and set True for by-pound categories."""
    # Add the column with default False
    op.add_column(
        'item_types',
        sa.Column('is_by_pound', sa.Boolean(), nullable=False, server_default='0')
    )

    # Set is_by_pound=True for existing by-pound ItemTypes
    item_types = sa.table(
        'item_types',
        sa.column('slug', sa.String),
        sa.column('is_by_pound', sa.Boolean),
    )

    op.execute(
        item_types.update()
        .where(item_types.c.slug.in_(BY_POUND_SLUGS))
        .values(is_by_pound=True)
    )


def downgrade() -> None:
    """Remove is_by_pound column from item_types."""
    op.drop_column('item_types', 'is_by_pound')
