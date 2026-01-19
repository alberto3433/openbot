"""Add standalone_instruction patterns to response_pattern table

Revision ID: add_standalone_instruction_001
Revises: split_mss_001
Create Date: 2026-01-19

This migration moves STANDALONE_INSTRUCTION_PATTERNS from hardcoded constants
to the database, making special instruction detection fully data-driven.

These patterns match special preparation instructions like:
- "leave room for cream", "not too hot", "lukewarm"
- "lightly toasted", "well done", "cut in half"
- "spread thin", "on one side", "melted"
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_standalone_instruction_001'
down_revision: Union[str, Sequence[str], None] = 'split_mss_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Standalone instruction patterns (all regex)
# These detect special preparation instructions in user input
STANDALONE_INSTRUCTION_PATTERNS = [
    # Coffee/beverage preparation
    r'\b(?:leave\s+)?room\s+(?:for\s+(?:cream|milk))?\b',  # "leave room", "room for cream"
    r'\bnot\s+too\s+hot\b',  # "not too hot"
    r'\blukewarm\b',  # "lukewarm"
    r'\bupside\s+down\b',  # "upside down" (espresso poured last)
    r'\bwell\s+stirred\b',  # "well stirred"
    r'\b(?:well\s+)?mixed\b',  # "mixed", "well mixed"
    # Toast/bread preparation
    r'\blightly\s+toasted\b',  # "lightly toasted"
    r'\bwell\s+done\b',  # "well done"
    r'\bcut\s+in\s+half\b',  # "cut in half"
    r'\bsliced\b',  # "sliced"
    r'\bopen\s+faced\b',  # "open faced"
    # Spread/topping application
    r'\bspread\s+thin\b',  # "spread thin"
    r'\b(?:only\s+)?on\s+one\s+side\b',  # "on one side", "only on one side"
    r'\bon\s+both\s+(?:halves|sides)\b',  # "on both halves", "on both sides"
    r'\bmelted\b',  # "melted" (for cheese)
]


def upgrade() -> None:
    """Add standalone_instruction patterns to response_pattern table."""
    conn = op.get_bind()

    # Update the check constraint to include 'standalone_instruction'
    conn.execute(sa.text("ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done', 'greeting', 'standalone_instruction'))"
    ))

    # Add standalone instruction patterns (all regex)
    for pattern in STANDALONE_INSTRUCTION_PATTERNS:
        conn.execute(
            sa.text(
                "INSERT INTO response_pattern (pattern_type, pattern, is_regex) "
                "VALUES (:pattern_type, :pattern, :is_regex) "
                "ON CONFLICT (pattern_type, pattern) DO NOTHING"
            ),
            {"pattern_type": "standalone_instruction", "pattern": pattern, "is_regex": True}
        )


def downgrade() -> None:
    """Remove standalone_instruction patterns from response_pattern table."""
    conn = op.get_bind()

    # Remove standalone instruction patterns
    for pattern in STANDALONE_INSTRUCTION_PATTERNS:
        conn.execute(
            sa.text(
                "DELETE FROM response_pattern "
                "WHERE pattern_type = :pattern_type AND pattern = :pattern"
            ),
            {"pattern_type": "standalone_instruction", "pattern": pattern}
        )

    # Restore original check constraint (without 'standalone_instruction')
    conn.execute(sa.text("ALTER TABLE response_pattern DROP CONSTRAINT ck_response_pattern_pattern_type"))
    conn.execute(sa.text(
        "ALTER TABLE response_pattern ADD CONSTRAINT ck_response_pattern_pattern_type "
        "CHECK (pattern_type IN ('affirmative', 'negative', 'cancel', 'done', 'greeting'))"
    ))
