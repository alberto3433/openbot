"""disable_ask_in_conversation_for_extras

Revision ID: o9p0q1r2s3t5
Revises: n8o9p0q1r2s4
Create Date: 2026-01-08 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o9p0q1r2s3t5'
down_revision: Union[str, Sequence[str], None] = 'n8o9p0q1r2s4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set ask_in_conversation=False for cheese, extra_cheese, extra_protein, toppings, condiments."""
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE item_type_attributes
            SET ask_in_conversation = FALSE
            WHERE slug IN ('cheese', 'extra_cheese', 'extra_protein', 'toppings', 'condiments')
        """)
    )


def downgrade() -> None:
    """Restore ask_in_conversation=True for cheese, extra_cheese, extra_protein, toppings, condiments."""
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE item_type_attributes
            SET ask_in_conversation = TRUE
            WHERE slug IN ('cheese', 'extra_cheese', 'extra_protein', 'toppings', 'condiments')
        """)
    )
