"""add common restaurant phrases to response patterns

Revision ID: b7e2a1f4c893
Revises: a3ba59fb3da9
Create Date: 2026-02-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2a1f4c893'
down_revision: Union[str, Sequence[str], None] = 'a3ba59fb3da9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New negative patterns (exact strings) - common polite declines
NEGATIVE_PATTERNS = [
    "i'll pass",
    "not today",
    "not right now",
    "not for me",
    "i'm fine",
    "i'm okay",
    "i'm all good",
    "no i'm good",
]

# New affirmative patterns (exact strings) - common confirmations
AFFIRMATIVE_PATTERNS = [
    "go ahead",
    "sounds great",
    "sounds perfect",
    "that sounds good",
    "for sure",
    "works for me",
    "let's do it",
    "why not",
    "of course",
]

# New done patterns (regex) - extends existing done detection
DONE_REGEX_PATTERNS = [
    # "I'm fine", "I'm okay" — extends existing "i'm (good|done|all set)"
    r"i'?m\s*(fine|okay)",
]


def upgrade() -> None:
    """Add common restaurant phrases to response patterns."""
    conn = op.get_bind()

    # Add negative patterns
    for pattern in NEGATIVE_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "negative", "pattern": pattern, "is_regex": False}
        )

    # Add affirmative patterns
    for pattern in AFFIRMATIVE_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "affirmative", "pattern": pattern, "is_regex": False}
        )

    # Add done regex patterns
    for pattern in DONE_REGEX_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "done", "pattern": pattern, "is_regex": True}
        )


def downgrade() -> None:
    """Remove common restaurant phrases from response patterns."""
    conn = op.get_bind()

    # Remove negative patterns
    for pattern in NEGATIVE_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "negative", "pattern": pattern}
        )

    # Remove affirmative patterns
    for pattern in AFFIRMATIVE_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "affirmative", "pattern": pattern}
        )

    # Remove done regex patterns
    for pattern in DONE_REGEX_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "done", "pattern": pattern}
        )
