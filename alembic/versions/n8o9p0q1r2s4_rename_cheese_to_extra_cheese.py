"""rename_cheese_to_extra_cheese_for_non_bagels

Revision ID: n8o9p0q1r2s4
Revises: m7n8o9p0q1r3
Create Date: 2026-01-08 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n8o9p0q1r2s4'
down_revision: Union[str, Sequence[str], None] = 'm7n8o9p0q1r3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename 'cheese' to 'extra_cheese' for all item types except bagel."""
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE item_type_attributes
            SET slug = 'extra_cheese', display_name = 'Extra Cheese'
            WHERE slug = 'cheese'
            AND item_type_id NOT IN (
                SELECT id FROM item_types WHERE slug = 'bagel'
            )
        """)
    )


def downgrade() -> None:
    """Rename 'extra_cheese' back to 'cheese' for all item types except bagel."""
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE item_type_attributes
            SET slug = 'cheese', display_name = 'Cheese'
            WHERE slug = 'extra_cheese'
            AND item_type_id NOT IN (
                SELECT id FROM item_types WHERE slug = 'bagel'
            )
        """)
    )
