"""add_item_type_fields_table

Revision ID: 1e4a082d3f5d
Revises: c3d4e5f6g7h8
Create Date: 2026-01-06 11:42:42.442877

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e4a082d3f5d'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create item_type_field table and seed data."""
    # Create the item_type_field table
    op.create_table(
        'item_type_field',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_type_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(100), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('ask', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('question_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_type_id', 'field_name', name='uq_item_type_field_item_type_field')
    )
    op.create_index('idx_item_type_field_item_type', 'item_type_field', ['item_type_id'], unique=False)

    # Seed data for bagel fields
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'bagel_type', 1, true, true, 'What kind of bagel would you like?'
        FROM item_types WHERE slug = 'bagel';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'toasted', 2, true, true, 'Would you like it toasted?'
        FROM item_types WHERE slug = 'bagel';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'spread', 3, false, true, 'Any spread on that?'
        FROM item_types WHERE slug = 'bagel';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'extras', 4, false, true, 'Anything else on it?'
        FROM item_types WHERE slug = 'bagel';
    """)

    # Seed data for sized_beverage (coffee/tea) fields
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'drink_type', 1, true, true, 'What kind of drink would you like?'
        FROM item_types WHERE slug = 'sized_beverage';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'size', 2, true, true, 'What size?'
        FROM item_types WHERE slug = 'sized_beverage';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'iced', 3, true, true, 'Hot or iced?'
        FROM item_types WHERE slug = 'sized_beverage';
    """)
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'milk', 4, false, false, 'Any milk preference?'
        FROM item_types WHERE slug = 'sized_beverage';
    """)

    # Seed data for espresso fields
    op.execute("""
        INSERT INTO item_type_field (item_type_id, field_name, display_order, required, ask, question_text)
        SELECT id, 'shots', 1, false, false, 'How many shots?'
        FROM item_types WHERE slug = 'espresso';
    """)


def downgrade() -> None:
    """Drop item_type_field table."""
    op.drop_index('idx_item_type_field_item_type', table_name='item_type_field')
    op.drop_table('item_type_field')
