"""set_gf_everything_must_match

Revision ID: 97ebee1dd4a0
Revises: 77bcd21f5bf2
Create Date: 2026-01-08 23:30:39.864550

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97ebee1dd4a0'
down_revision: Union[str, Sequence[str], None] = '77bcd21f5bf2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set must_match for Gluten Free Everything Bagel to prevent false matches."""
    op.execute(
        """
        UPDATE ingredients
        SET must_match = 'Gluten Free Everything, GF Everything'
        WHERE name = 'Gluten Free Everything Bagel'
        """
    )


def downgrade() -> None:
    """Clear must_match for Gluten Free Everything Bagel."""
    op.execute(
        """
        UPDATE ingredients
        SET must_match = NULL
        WHERE name = 'Gluten Free Everything Bagel'
        """
    )
