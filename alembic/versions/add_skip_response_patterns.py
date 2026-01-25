"""add_skip_response_patterns

Revision ID: add_skip_response_patterns
Revises: rename_item_type_categories_to_overall
Create Date: 2026-01-25

Adds 'skip' pattern type to response_pattern table for negation patterns
that indicate user wants to remove/clear an attribute (e.g., "no milk", "black coffee").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_skip_response_patterns'
down_revision: Union[str, Sequence[str], None] = 'rename_item_type_categories_to_overall'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Negation patterns that indicate user wants to remove/clear an attribute
SKIP_PATTERNS = [
    'no',
    'none',
    'nothing',
    'without',
    'remove',
    'black',
    'skip',
    'pass',
    'na',
    'n/a',
    'plain',
    'regular',
]


def upgrade() -> None:
    """Add skip response patterns."""
    conn = op.get_bind()

    # Update the check constraint to include 'skip'
    conn.execute(sa.text(
        "ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"
    ))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done', 'greeting', 'standalone_instruction', 'skip'))"
    ))

    # Add skip patterns
    for pattern in SKIP_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern) "
                "VALUES (:pattern_type, :pattern) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "skip", "pattern": pattern}
        )


def downgrade() -> None:
    """Remove skip response patterns."""
    conn = op.get_bind()

    # Remove skip patterns
    conn.execute(sa.text(
        "DELETE FROM response_pattern WHERE pattern_type = 'skip'"
    ))

    # Restore original check constraint (without 'skip')
    conn.execute(sa.text(
        "ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"
    ))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done', 'greeting', 'standalone_instruction'))"
    ))
