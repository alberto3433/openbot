"""Add display_name_plural column to item_types table.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-01-05 12:00:00.000000

This migration adds a display_name_plural column to item_types for cases where
automatic pluralization doesn't work well (e.g., "sized_beverage" -> "coffees and teas").

This replaces the hardcoded ITEM_TYPE_DISPLAY_NAMES constant in constants.py.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Display name overrides for item types where automatic pluralization doesn't work
DISPLAY_NAME_PLURAL_OVERRIDES = [
    ("by_the_lb", "food by the pound"),
    ("cream_cheese", "cream cheeses"),
    ("sized_beverage", "coffees and teas"),
]


def upgrade() -> None:
    # Add the new column
    op.add_column("item_types", sa.Column("display_name_plural", sa.String(), nullable=True))

    # Populate the values for item types that need custom plural forms
    conn = op.get_bind()
    for slug, plural_name in DISPLAY_NAME_PLURAL_OVERRIDES:
        conn.execute(
            sa.text("UPDATE item_types SET display_name_plural = :plural WHERE slug = :slug"),
            {"plural": plural_name, "slug": slug}
        )
        print(f"Set display_name_plural for '{slug}' to '{plural_name}'")


def downgrade() -> None:
    op.drop_column("item_types", "display_name_plural")
