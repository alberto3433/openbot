"""Add lox and nova aliases for nova_scotia_salmon ingredient

Revision ID: add_lox_nova_aliases
Revises: efebef2f5442
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_lox_nova_aliases'
down_revision: Union[str, Sequence[str], None] = 'efebef2f5442'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'lox' and 'nova' as aliases for nova_scotia_salmon ingredient."""
    conn = op.get_bind()

    # Add "lox" alias
    conn.execute(sa.text("""
        INSERT INTO ingredient_aliases (ingredient_id, alias)
        SELECT id, 'lox'
        FROM ingredients
        WHERE slug = 'nova_scotia_salmon'
        ON CONFLICT (alias) DO NOTHING
    """))

    # Add "nova" alias
    conn.execute(sa.text("""
        INSERT INTO ingredient_aliases (ingredient_id, alias)
        SELECT id, 'nova'
        FROM ingredients
        WHERE slug = 'nova_scotia_salmon'
        ON CONFLICT (alias) DO NOTHING
    """))


def downgrade() -> None:
    """Remove lox and nova aliases."""
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM ingredient_aliases WHERE alias IN ('lox', 'nova')"
    ))
