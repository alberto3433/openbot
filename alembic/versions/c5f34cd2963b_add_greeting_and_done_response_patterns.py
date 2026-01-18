"""add greeting and done response patterns

Revision ID: c5f34cd2963b
Revises: 082a2cf2a883
Create Date: 2026-01-17 21:48:13.525466

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5f34cd2963b'
down_revision: Union[str, Sequence[str], None] = '082a2cf2a883'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Greeting patterns (exact strings - simple words/phrases)
GREETING_PATTERNS = [
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "yo",
]

# Done patterns - regex patterns that replace DONE_PATTERNS in constants.py
# These patterns are used to detect when user is done ordering
DONE_REGEX_PATTERNS = [
    # "that's all", "that's it", "thats all", "that all", "that's all for now"
    r"that'?s?\s*(all|it)(\s+for\s+now)?",
    # "no", "nope", "nothing", "no else", "no more", "nothing else", "nothing more"
    r"no(pe|thing)?(\s*(else|more))?",
    # "i'm good", "i'm done", "i'm all set", "im good", "im done", "im all set"
    r"i'?m\s*(good|done|all\s*set)",
    # "nothing", "nothing else", "nothing more"
    r"nothing(\s*(else|more))?",
    # "that will be all"
    r"that\s*will\s*be\s*all",
    # "just the bagel", "just the plain bagel", "just that"
    r"just\s+the\s+\w+(\s+\w+)?",
    r"just\s+that",
    # "only the bagel", "only the plain bagel"
    r"only\s+the\s+\w+(\s+\w+)?",
]

# Done patterns - exact strings (already in DB but listed for reference)
# These are simpler patterns that don't need regex
DONE_EXACT_PATTERNS = [
    "done",
    "all set",
    "nah",
]


def upgrade() -> None:
    """Add greeting and done response patterns."""
    conn = op.get_bind()

    # First, update the check constraint to include 'greeting'
    conn.execute(sa.text("ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done', 'greeting'))"
    ))

    # Add greeting patterns (exact strings)
    for pattern in GREETING_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "greeting", "pattern": pattern, "is_regex": False}
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

    # Add done exact patterns (some may already exist)
    for pattern in DONE_EXACT_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "done", "pattern": pattern, "is_regex": False}
        )


def downgrade() -> None:
    """Remove greeting and done response patterns."""
    conn = op.get_bind()

    # Remove greeting patterns
    for pattern in GREETING_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "greeting", "pattern": pattern}
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

    # Remove done exact patterns we added
    for pattern in DONE_EXACT_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "done", "pattern": pattern}
        )

    # Restore original check constraint
    conn.execute(sa.text("ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done'))"
    ))
