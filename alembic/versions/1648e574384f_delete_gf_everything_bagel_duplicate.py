"""delete_gf_everything_bagel_duplicate

Revision ID: 1648e574384f
Revises: 97ebee1dd4a0
Create Date: 2026-01-08 23:31:35.104513

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1648e574384f'
down_revision: Union[str, Sequence[str], None] = '97ebee1dd4a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Delete duplicate GF Everything Bagel ingredient."""
    # First delete any store availability records
    op.execute(
        """
        DELETE FROM ingredient_store_availability
        WHERE ingredient_id IN (
            SELECT id FROM ingredients WHERE name = 'GF Everything Bagel'
        )
        """
    )
    # Then delete the ingredient
    op.execute(
        """
        DELETE FROM ingredients
        WHERE name = 'GF Everything Bagel'
        """
    )


def downgrade() -> None:
    """Re-create GF Everything Bagel ingredient (if needed)."""
    # Note: This is a simplified downgrade - exact original data may differ
    op.execute(
        """
        INSERT INTO ingredients (name, slug, category, unit, is_available)
        VALUES ('GF Everything Bagel', 'gf_everything_bagel', 'bread', 'piece', true)
        """
    )
