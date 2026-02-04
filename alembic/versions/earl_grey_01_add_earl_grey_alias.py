"""Add 'earl grey' alias for earl_gray ingredient.

The ingredient is spelled "Earl Gray" (with 'a') but users commonly type
"earl grey" (with 'e'). This migration adds the alias so both spellings work.

Revision ID: earl_grey_01
Revises: followup_01
Create Date: 2026-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "earl_grey_01"
down_revision: Union[str, Sequence[str], None] = "followup_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'earl grey' as an alias for earl_gray ingredient."""
    conn = op.get_bind()

    conn.execute(sa.text("""
        INSERT INTO ingredient_aliases (ingredient_id, alias)
        SELECT id, 'earl grey'
        FROM ingredients
        WHERE slug = 'earl_gray'
        ON CONFLICT (alias) DO NOTHING
    """))


def downgrade() -> None:
    """Remove earl grey alias."""
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM ingredient_aliases WHERE alias = 'earl grey'"
    ))
