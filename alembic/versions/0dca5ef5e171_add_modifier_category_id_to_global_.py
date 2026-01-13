"""Add modifier_category_id to global_attribute_options

Revision ID: 0dca5ef5e171
Revises: f2g3h4i5j6k7
Create Date: 2026-01-12 21:42:57.856197

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0dca5ef5e171'
down_revision: Union[str, Sequence[str], None] = 'f2g3h4i5j6k7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add modifier_category_id FK to global_attribute_options for sub-categorization."""
    op.add_column('global_attribute_options', sa.Column('modifier_category_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_global_attribute_options_modifier_category_id'), 'global_attribute_options', ['modifier_category_id'], unique=False)
    op.create_foreign_key(
        'fk_global_attribute_options_modifier_category',
        'global_attribute_options',
        'modifier_categories',
        ['modifier_category_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Remove modifier_category_id FK from global_attribute_options."""
    op.drop_constraint('fk_global_attribute_options_modifier_category', 'global_attribute_options', type_='foreignkey')
    op.drop_index(op.f('ix_global_attribute_options_modifier_category_id'), table_name='global_attribute_options')
    op.drop_column('global_attribute_options', 'modifier_category_id')
