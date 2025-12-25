"""Add speed_menu_bagel item type

Revision ID: f9g0h1i2j3k4
Revises: e8f9g0h1i2j3
Create Date: 2025-12-23 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9g0h1i2j3k4'
down_revision: Union[str, Sequence[str], None] = 'e8f9g0h1i2j3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Speed menu bagel items to migrate (by name)
SPEED_MENU_BAGEL_ITEMS = [
    'The Classic',
    'The Classic BEC',
    'The Avocado Toast',
    'The Chelsea Club',
    'The Flatiron Traditional',
    'The Max Zucker',
    'The Old School Tuna Sandwich',
    'The Traditional',
]


def upgrade() -> None:
    """Add speed_menu_bagel item type and migrate items."""
    # Get connection for data operations
    conn = op.get_bind()

    # Insert the new item type
    conn.execute(
        sa.text("""
            INSERT INTO item_types (slug, display_name, is_configurable, skip_config)
            VALUES ('speed_menu_bagel', 'Speed Menu Bagel', 0, 1)
        """)
    )

    # Get the new item type ID
    result = conn.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'speed_menu_bagel'")
    )
    new_type_id = result.fetchone()[0]

    # Update menu items to use the new type
    for item_name in SPEED_MENU_BAGEL_ITEMS:
        conn.execute(
            sa.text("UPDATE menu_items SET item_type_id = :type_id WHERE name = :name"),
            {"type_id": new_type_id, "name": item_name}
        )


def downgrade() -> None:
    """Remove speed_menu_bagel item type."""
    conn = op.get_bind()

    # Set menu items back to NULL (or their original types if tracked)
    conn.execute(
        sa.text("UPDATE menu_items SET item_type_id = NULL WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'speed_menu_bagel')")
    )

    # Delete the item type
    conn.execute(
        sa.text("DELETE FROM item_types WHERE slug = 'speed_menu_bagel'")
    )
