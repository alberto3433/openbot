"""Add unrecognized item suggestion and logging tables

Adds two new tables:
- unrecognized_item_suggestions: Curated responses for known unrecognized items
- unrecognized_item_log: Analytics for tracking unrecognized item requests

Revision ID: unrecognized_01
Revises: a524df39ae08
Create Date: 2026-01-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_01'
down_revision: Union[str, Sequence[str], None] = 'a524df39ae08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create unrecognized_item_suggestions table
    op.create_table(
        'unrecognized_item_suggestions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('input_pattern', sa.String(200), nullable=False),
        sa.Column('match_type', sa.String(20), server_default='exact', nullable=False),
        sa.Column('suggested_category_slug', sa.String(50), nullable=True),
        sa.Column('suggested_response', sa.Text(), nullable=True),
        sa.Column('suggested_menu_items', sa.JSON(), nullable=True),
        sa.Column('hit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_unrecognized_suggestions_pattern', 'unrecognized_item_suggestions', ['input_pattern'])
    op.create_index('ix_unrecognized_suggestions_category', 'unrecognized_item_suggestions', ['suggested_category_slug'])

    # Create unrecognized_item_log table
    op.create_table(
        'unrecognized_item_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_input', sa.String(500), nullable=False),
        sa.Column('normalized_input', sa.String(200), nullable=False),
        sa.Column('session_id', sa.String(100), nullable=True),
        sa.Column('order_item_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('fallback_level', sa.String(20), nullable=False),
        sa.Column('inferred_category', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_unrecognized_log_normalized', 'unrecognized_item_log', ['normalized_input'])
    op.create_index('ix_unrecognized_log_fallback', 'unrecognized_item_log', ['fallback_level'])
    op.create_index('ix_unrecognized_log_created', 'unrecognized_item_log', ['created_at'])

    # Seed initial curated suggestions for common unrecognized items
    op.execute("""
        INSERT INTO unrecognized_item_suggestions (input_pattern, match_type, suggested_category_slug) VALUES
        ('croissant', 'exact', 'pastry'),
        ('donut', 'exact', 'pastry'),
        ('doughnut', 'exact', 'pastry'),
        ('home fries', 'exact', 'side'),
        ('hash browns', 'exact', 'side'),
        ('hashbrowns', 'exact', 'side'),
        ('pepsi', 'exact', 'beverage'),
        ('sprite', 'exact', 'beverage'),
        ('mountain dew', 'exact', 'beverage'),
        ('dr pepper', 'exact', 'beverage'),
        ('expresso', 'exact', 'espresso'),
        ('capuccino', 'exact', 'espresso'),
        ('cappucino', 'exact', 'espresso'),
        ('frappuccino', 'exact', 'espresso'),
        ('frappe', 'exact', 'espresso'),
        ('toast', 'exact', 'bagel'),
        ('english muffin', 'exact', 'bagel'),
        ('biscuit', 'exact', 'pastry'),
        ('pancakes', 'exact', 'side'),
        ('pancake', 'exact', 'side'),
        ('waffles', 'exact', 'side'),
        ('waffle', 'exact', 'side'),
        ('french toast', 'exact', 'side'),
        ('eggs', 'exact', 'side'),
        ('scrambled eggs', 'exact', 'side'),
        ('fried eggs', 'exact', 'side')
    """)


def downgrade() -> None:
    op.drop_table('unrecognized_item_log')
    op.drop_table('unrecognized_item_suggestions')
