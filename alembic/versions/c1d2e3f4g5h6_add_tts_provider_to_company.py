"""Add tts_provider and tts_default_voice to company table

Revision ID: c1d2e3f4g5h6
Revises: bcd7f641e3bc
Create Date: 2026-02-22

Adds TTS provider columns to the company table to allow toggling between
OpenAI, ElevenLabs, and Cartesia for text-to-speech synthesis.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1d2e3f4g5h6"
down_revision = "bcd7f641e3bc"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column already exists in a table."""
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    ).fetchone()
    return result is not None


def upgrade() -> None:
    if not _column_exists("company", "tts_provider"):
        op.add_column(
            "company",
            sa.Column("tts_provider", sa.String(), nullable=False, server_default="openai"),
        )
    if not _column_exists("company", "tts_default_voice"):
        op.add_column(
            "company",
            sa.Column("tts_default_voice", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("company", "tts_default_voice")
    op.drop_column("company", "tts_provider")
