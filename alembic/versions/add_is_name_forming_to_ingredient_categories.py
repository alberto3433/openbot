"""add_is_name_forming_to_ingredient_categories

Revision ID: add_is_name_forming_001
Revises: add_skip_response_patterns
Create Date: 2026-01-25

Adds is_name_forming boolean column to ingredient_categories table.
Categories marked as name-forming will have their ingredient display name
replace the base menu item name (e.g., "Garlic Bagel" instead of "Bagel, Garlic Bagel").
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_is_name_forming_001'
down_revision: Union[str, Sequence[str], None] = 'add_skip_response_patterns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_name_forming column and set bread category as name-forming."""
    # Add the column with default false
    op.add_column(
        'ingredient_categories',
        sa.Column('is_name_forming', sa.Boolean(), nullable=False, server_default='false')
    )

    # Set bread as name-forming
    op.execute("""
        UPDATE ingredient_categories
        SET is_name_forming = true
        WHERE slug = 'bread'
    """)


def downgrade() -> None:
    """Remove is_name_forming column."""
    op.drop_column('ingredient_categories', 'is_name_forming')
