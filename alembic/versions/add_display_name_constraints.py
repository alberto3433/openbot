"""Add CHECK constraints for display name characters

Restricts display names in menu_items, ingredients, and item_types to only
allow: letters, numbers, spaces, hyphens, apostrophes, ampersands, and periods.

This prevents parsing issues caused by special characters like parentheses,
commas, or other symbols.

Revision ID: display_name_chars_01
Revises: add_qty_per_unit_01
Create Date: 2026-02-06

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'display_name_chars_01'
down_revision: Union[str, None] = 'add_qty_per_unit_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Pattern: only letters, numbers, spaces, hyphens, apostrophes, ampersands, periods
# Using PostgreSQL regex: ~ '^[a-zA-Z0-9 \-''&.]+$'
# Note: apostrophe is doubled ('') for PostgreSQL string escaping
ALLOWED_CHARS_PATTERN = "^[a-zA-Z0-9 \\-''&.]+$"


def upgrade() -> None:
    # Add CHECK constraint to menu_items.name
    op.execute(
        f"""
        ALTER TABLE menu_items
        ADD CONSTRAINT menu_items_name_allowed_chars
        CHECK (name ~ '{ALLOWED_CHARS_PATTERN}')
        """
    )

    # Add CHECK constraint to ingredients.name
    op.execute(
        f"""
        ALTER TABLE ingredients
        ADD CONSTRAINT ingredients_name_allowed_chars
        CHECK (name ~ '{ALLOWED_CHARS_PATTERN}')
        """
    )

    # Add CHECK constraint to item_types.display_name
    op.execute(
        f"""
        ALTER TABLE item_types
        ADD CONSTRAINT item_types_display_name_allowed_chars
        CHECK (display_name ~ '{ALLOWED_CHARS_PATTERN}')
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE menu_items DROP CONSTRAINT menu_items_name_allowed_chars")
    op.execute("ALTER TABLE ingredients DROP CONSTRAINT ingredients_name_allowed_chars")
    op.execute("ALTER TABLE item_types DROP CONSTRAINT item_types_display_name_allowed_chars")
