"""drop_menu_item_attributes_tables

Revision ID: drop_mi_attrs01
Revises: ea1b14f8078d
Create Date: 2026-01-14

This migration removes the unused menu item attribute tables.
These tables were designed for per-menu-item attribute overrides,
but all attribute configuration comes from item_type_attributes.

Dropped tables:
- menu_item_attribute_selections (multi-select values)
- menu_item_attribute_values (single-select, boolean, text values)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'drop_mi_attrs01'
down_revision: Union[str, Sequence[str], None] = 'ea1b14f8078d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop menu item attribute tables."""
    # Drop selections table first (depends on values conceptually)
    op.drop_table('menu_item_attribute_selections')
    op.drop_table('menu_item_attribute_values')


def downgrade() -> None:
    """Recreate menu item attribute tables."""
    # Recreate menu_item_attribute_values table
    op.create_table(
        'menu_item_attribute_values',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('attribute_id', sa.Integer(), nullable=False),
        sa.Column('option_id', sa.Integer(), nullable=True),
        sa.Column('value_boolean', sa.Boolean(), nullable=True),
        sa.Column('value_text', sa.Text(), nullable=True),
        sa.Column('still_ask', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attribute_id'], ['item_type_attributes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['option_id'], ['attribute_options.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('menu_item_id', 'attribute_id', name='uq_menu_item_attribute_values'),
    )
    op.create_index('ix_menu_item_attribute_values_menu_item_id', 'menu_item_attribute_values', ['menu_item_id'])
    op.create_index('ix_menu_item_attribute_values_attribute_id', 'menu_item_attribute_values', ['attribute_id'])

    # Recreate menu_item_attribute_selections table
    op.create_table(
        'menu_item_attribute_selections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('attribute_id', sa.Integer(), nullable=False),
        sa.Column('option_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attribute_id'], ['item_type_attributes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['option_id'], ['attribute_options.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('menu_item_id', 'attribute_id', 'option_id', name='uq_menu_item_attr_selection'),
    )
    op.create_index('ix_menu_item_attribute_selections_menu_item_id', 'menu_item_attribute_selections', ['menu_item_id'])
