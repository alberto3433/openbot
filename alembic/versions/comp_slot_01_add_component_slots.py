"""Add component slots tables for bundled items

Revision ID: comp_slot_01
Revises: egg_qty_02_standard
Create Date: 2026-02-01

This migration adds support for item types that include configurable sub-items.
For example, omelettes include a side (bagel or fruit salad) where the bagel
can be configured (bread type, toasted, etc.).

Tables added:
- item_type_component_slots: Defines slots for parent item types
- component_slot_options: Defines what can fill each slot with pricing rules
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'comp_slot_01'
down_revision: Union[str, Sequence[str], None] = 'egg_qty_02_standard'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create component slots tables."""
    # Create item_type_component_slots table
    op.create_table(
        'item_type_component_slots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('parent_item_type_id', sa.Integer(), nullable=False),
        sa.Column('slot_name', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=True),
        sa.Column('prompt_text', sa.Text(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('min_quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('max_quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['parent_item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('parent_item_type_id', 'slot_name', name='uq_component_slot_type_name'),
    )
    op.create_index('ix_component_slots_parent_type', 'item_type_component_slots', ['parent_item_type_id'])

    # Create component_slot_options table
    op.create_table(
        'component_slot_options',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slot_id', sa.Integer(), nullable=False),
        sa.Column('allowed_item_type_id', sa.Integer(), nullable=True),
        sa.Column('allowed_menu_item_id', sa.Integer(), nullable=True),
        sa.Column('price_rule', sa.String(20), nullable=False, server_default='included'),
        sa.Column('fixed_price', sa.Integer(), nullable=True),
        sa.Column('display_name', sa.String(100), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['slot_id'], ['item_type_component_slots.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['allowed_item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['allowed_menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_slot_option_slot', 'component_slot_options', ['slot_id'])
    op.create_index('ix_slot_option_item_type', 'component_slot_options', ['allowed_item_type_id'])
    op.create_index('ix_slot_option_menu_item', 'component_slot_options', ['allowed_menu_item_id'])


def downgrade() -> None:
    """Drop component slots tables."""
    op.drop_table('component_slot_options')
    op.drop_table('item_type_component_slots')
