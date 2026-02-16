"""add_default_modifiers_to_slot_options

Revision ID: 1922a6249144
Revises: 96d013b41cd3
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = '1922a6249144'
down_revision: Union[str, Sequence[str], None] = '96d013b41cd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add default_modifiers JSONB column to component_slot_options."""
    op.add_column(
        'component_slot_options',
        sa.Column('default_modifiers', JSONB, nullable=True)
    )


def downgrade() -> None:
    """Remove default_modifiers column from component_slot_options."""
    op.drop_column('component_slot_options', 'default_modifiers')
