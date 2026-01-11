"""drop_item_type_field_table

Revision ID: a5b6c7d8e9f0
Revises: 20f3ceba966c
Create Date: 2026-01-10

This migration drops the deprecated item_type_field table.
The functionality was replaced by ItemTypeAttribute which provides
a more flexible attribute-based configuration system.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = '20f3ceba966c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the deprecated item_type_field table."""
    op.drop_table('item_type_field')


def downgrade() -> None:
    """Recreate the item_type_field table."""
    op.create_table(
        'item_type_field',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id', ondelete='CASCADE'), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, default=0),
        sa.Column('required', sa.Boolean(), nullable=False, default=False),
        sa.Column('ask', sa.Boolean(), nullable=False, default=True),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint('item_type_id', 'field_name', name='uq_item_type_field_item_type_field'),
        sa.Index('idx_item_type_field_item_type', 'item_type_id'),
    )
