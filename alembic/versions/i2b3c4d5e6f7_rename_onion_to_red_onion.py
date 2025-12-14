"""rename_onion_to_red_onion

Revision ID: i2b3c4d5e6f7
Revises: h1a2b3c4d5e6
Create Date: 2025-12-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'h1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename 'Onion' ingredient to 'Red Onion'."""
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE ingredients SET name = 'Red Onion' WHERE name = 'Onion'")
    )


def downgrade() -> None:
    """Rename 'Red Onion' back to 'Onion'."""
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE ingredients SET name = 'Onion' WHERE name = 'Red Onion'")
    )
