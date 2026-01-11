"""drop_deprecated_global_option_columns

Revision ID: c7d8e9f0g1h2
Revises: b6c7d8e9f0g1
Create Date: 2026-01-10

This migration drops the deprecated aliases and must_match columns from
GlobalAttributeOption. These values are now read exclusively from the
linked Ingredient record.

Prerequisites:
- Migration b6c7d8e9f0g1 must have run to link all options to Ingredients
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0g1h2'
down_revision: Union[str, Sequence[str], None] = 'b6c7d8e9f0g1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop deprecated aliases and must_match columns from global_attribute_options."""
    op.drop_column('global_attribute_options', 'aliases')
    op.drop_column('global_attribute_options', 'must_match')


def downgrade() -> None:
    """Re-add aliases and must_match columns to global_attribute_options."""
    op.add_column(
        'global_attribute_options',
        sa.Column('must_match', sa.Text(), nullable=True)
    )
    op.add_column(
        'global_attribute_options',
        sa.Column('aliases', sa.String(255), nullable=True)
    )
