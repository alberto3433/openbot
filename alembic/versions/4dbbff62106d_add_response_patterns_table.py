"""add_response_patterns_table

Revision ID: 4dbbff62106d
Revises: 1e4a082d3f5d
Create Date: 2026-01-06 11:47:18.492945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dbbff62106d'
down_revision: Union[str, Sequence[str], None] = '1e4a082d3f5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create response_pattern table and seed data."""
    # Create the response_pattern table
    op.create_table(
        'response_pattern',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('pattern_type', sa.String(50), nullable=False),
        sa.Column('pattern', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pattern_type', 'pattern', name='uq_response_pattern_type_pattern')
    )
    op.create_index('idx_response_pattern_type', 'response_pattern', ['pattern_type'], unique=False)

    # Seed affirmative responses
    op.execute("""
        INSERT INTO response_pattern (pattern_type, pattern) VALUES
        ('affirmative', 'yes'),
        ('affirmative', 'yeah'),
        ('affirmative', 'yep'),
        ('affirmative', 'yup'),
        ('affirmative', 'sure'),
        ('affirmative', 'ok'),
        ('affirmative', 'okay'),
        ('affirmative', 'correct'),
        ('affirmative', 'right'),
        ('affirmative', 'that''s right'),
        ('affirmative', 'that''s correct'),
        ('affirmative', 'looks good'),
        ('affirmative', 'perfect'),
        ('affirmative', 'sounds good'),
        ('affirmative', 'please'),
        ('affirmative', 'definitely'),
        ('affirmative', 'absolutely');
    """)

    # Seed negative responses
    op.execute("""
        INSERT INTO response_pattern (pattern_type, pattern) VALUES
        ('negative', 'no'),
        ('negative', 'nope'),
        ('negative', 'nah'),
        ('negative', 'no thanks'),
        ('negative', 'no thank you'),
        ('negative', 'not really'),
        ('negative', 'i''m good'),
        ('negative', 'none'),
        ('negative', 'nothing');
    """)

    # Seed cancel responses
    op.execute("""
        INSERT INTO response_pattern (pattern_type, pattern) VALUES
        ('cancel', 'cancel'),
        ('cancel', 'cancel that'),
        ('cancel', 'cancel order'),
        ('cancel', 'never mind'),
        ('cancel', 'nevermind'),
        ('cancel', 'forget it'),
        ('cancel', 'forget that'),
        ('cancel', 'scratch that');
    """)

    # Seed done responses
    op.execute("""
        INSERT INTO response_pattern (pattern_type, pattern) VALUES
        ('done', 'that''s all'),
        ('done', 'that''s it'),
        ('done', 'nothing else'),
        ('done', 'i''m done'),
        ('done', 'all set'),
        ('done', 'that''s everything'),
        ('done', 'done');
    """)


def downgrade() -> None:
    """Drop response_pattern table."""
    op.drop_index('idx_response_pattern_type', table_name='response_pattern')
    op.drop_table('response_pattern')
