"""Add coffee alias for sized_beverage

Revision ID: a2c4c83b1a12
Revises: 148706983bdb
Create Date: 2026-01-13 21:38:13.471051

This migration adds 'coffee' as an alias for the 'sized_beverage' item type.
This allows data-driven resolution of item type names, eliminating the need
for hardcoded mappings like _ITEM_TYPE_TO_SLUG_MAP in field_config.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2c4c83b1a12'
down_revision: Union[str, Sequence[str], None] = '148706983bdb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'coffee' as an alias for the 'sized_beverage' item type."""
    conn = op.get_bind()

    # Get the sized_beverage item type ID
    result = conn.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
    ).fetchone()

    if result:
        item_type_id = result[0]
        # Insert the alias (only if it doesn't already exist)
        conn.execute(
            sa.text("""
                INSERT INTO item_type_aliases (item_type_id, alias)
                SELECT :item_type_id, 'coffee'
                WHERE NOT EXISTS (
                    SELECT 1 FROM item_type_aliases WHERE alias = 'coffee'
                )
            """),
            {"item_type_id": item_type_id}
        )


def downgrade() -> None:
    """Remove the 'coffee' alias."""
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM item_type_aliases WHERE alias = 'coffee'"))
