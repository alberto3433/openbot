"""add_required_match_phrases_to_menu_items

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-01-01

Adds a column to allow menu items to specify required match phrases.
This prevents false positive matches like "coffee" matching "Russian Coffee Cake".

Example: Russian Coffee Cake with required_match_phrases="coffee cake, cake"
- "coffee" -> NO match (doesn't contain "coffee cake" OR "cake")
- "coffee cake" -> MATCH (contains "coffee cake")
- "cake" -> MATCH (contains "cake")
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i2j3k4l5m6n7'
down_revision: Union[str, Sequence[str], None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add required_match_phrases column to menu_items table."""
    op.add_column(
        'menu_items',
        sa.Column('required_match_phrases', sa.String(), nullable=True)
    )


def downgrade() -> None:
    """Remove required_match_phrases column from menu_items table."""
    op.drop_column('menu_items', 'required_match_phrases')
