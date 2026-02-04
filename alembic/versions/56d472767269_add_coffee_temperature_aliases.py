"""Remove required_match_phrases from Iced Coffee

The required_match_phrases on Iced Coffee was incorrectly causing
text_matches_exclusion_phrase to exclude valid "iced coffee" orders
from the configurable item parsing flow.

The display name "Iced Coffee" already provides matching for "iced coffee"
input - no alias is needed.

Revision ID: 56d472767269
Revises: add_generic_omelette
Create Date: 2026-02-03 09:09:06.458144

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '56d472767269'
down_revision: Union[str, Sequence[str], None] = 'add_generic_omelette'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove required_match_phrases from Iced Coffee."""
    conn = op.get_bind()

    # Remove required_match_phrases from Iced Coffee
    # This was incorrectly causing text_matches_exclusion_phrase to exclude
    # valid "iced coffee" orders from the configurable item flow
    conn.execute(
        sa.text(
            "UPDATE menu_items SET required_match_phrases = NULL WHERE name = 'Iced Coffee'"
        )
    )


def downgrade() -> None:
    """Restore required_match_phrases to Iced Coffee."""
    conn = op.get_bind()

    conn.execute(
        sa.text(
            "UPDATE menu_items SET required_match_phrases = 'iced coffee' WHERE name = 'Iced Coffee'"
        )
    )
