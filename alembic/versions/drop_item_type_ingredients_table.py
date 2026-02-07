"""Drop item_type_ingredients table

This table is no longer used - ingredient validity for item types is now derived from:
GlobalAttributeOption -> GlobalAttribute -> ItemTypeGlobalAttribute -> ItemType

Revision ID: drop_iti_table_01
Revises: move_question_text_01
Create Date: 2026-02-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'drop_iti_table_01'
down_revision: Union[str, None] = 'move_question_text_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the item_type_ingredients table
    op.drop_table('item_type_ingredients')


def downgrade() -> None:
    # Recreate item_type_ingredients table
    op.create_table(
        'item_type_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_type_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_group', sa.String(length=50), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('display_name_override', sa.String(length=100), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_available', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['item_type_id'], ['item_types.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_type_id', 'ingredient_id', 'ingredient_group', name='uq_item_type_ingredient_group'),
    )
    op.create_index('idx_item_type_ingredients_item_type', 'item_type_ingredients', ['item_type_id'], unique=False)
    op.create_index('idx_item_type_ingredients_ingredient', 'item_type_ingredients', ['ingredient_id'], unique=False)
    op.create_index('idx_item_type_ingredients_group', 'item_type_ingredients', ['ingredient_group'], unique=False)
    op.create_index('idx_item_type_ingredients_item_type_group', 'item_type_ingredients', ['item_type_id', 'ingredient_group'], unique=False)
    op.create_index(op.f('ix_item_type_ingredients_id'), 'item_type_ingredients', ['id'], unique=False)
