"""rename_cookie_to_chocolate_chip_cookie

Revision ID: j3c4d5e6f7g8
Revises: i2b3c4d5e6f7
Create Date: 2025-12-14 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j3c4d5e6f7g8'
down_revision: Union[str, Sequence[str], None] = 'i2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename 'Cookie' menu item to 'Chocolate Chip Cookie'."""
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE menu_items SET name = 'Chocolate Chip Cookie' WHERE name = 'Cookie'")
    )


def downgrade() -> None:
    """Rename 'Chocolate Chip Cookie' back to 'Cookie'."""
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE menu_items SET name = 'Cookie' WHERE name = 'Chocolate Chip Cookie'")
    )
