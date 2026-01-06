"""Add abbreviation column to ingredients and menu_items tables.

Abbreviations are short forms that get expanded to canonical names before parsing.
Unlike aliases (used for matching), abbreviations perform text replacement.
Example: "cc" -> "cream cheese", so "strawberry cc" becomes "strawberry cream cheese"

Revision ID: b2c3d4e5f6g7
Revises: e0b14c1ef231
Create Date: 2026-01-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'e0b14c1ef231'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add abbreviation column to ingredients table
    op.add_column('ingredients', sa.Column('abbreviation', sa.String(), nullable=True))

    # Add abbreviation column to menu_items table
    op.add_column('menu_items', sa.Column('abbreviation', sa.String(), nullable=True))

    # Seed initial abbreviation for cream cheese
    op.execute("""
        UPDATE ingredients
        SET abbreviation = 'cc'
        WHERE LOWER(name) = 'cream cheese'
    """)


def downgrade() -> None:
    op.drop_column('menu_items', 'abbreviation')
    op.drop_column('ingredients', 'abbreviation')
