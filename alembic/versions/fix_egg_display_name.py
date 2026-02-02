"""Fix attribute display_name from Egg to Eggs

Revision ID: fix_egg_display
Revises: comp_slot_03
Create Date: 2026-02-02

Changes:
- Updates item_type_attributes.display_name from 'Egg' to 'Eggs'
  for a more natural category label in customization checkpoints.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'fix_egg_display'
down_revision: Union[str, Sequence[str], None] = 'comp_slot_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Update 'Egg' to 'Eggs' for attribute display names."""
    # Update any item_type_attribute with display_name='Egg' to 'Eggs'
    op.execute("""
        UPDATE item_type_attributes
        SET display_name = 'Eggs'
        WHERE display_name = 'Egg'
    """)


def downgrade() -> None:
    """Revert 'Eggs' back to 'Egg' for attribute display names."""
    op.execute("""
        UPDATE item_type_attributes
        SET display_name = 'Egg'
        WHERE display_name = 'Eggs'
    """)
