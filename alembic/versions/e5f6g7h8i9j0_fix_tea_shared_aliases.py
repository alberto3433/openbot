"""Fix tea shared aliases - remove generic 'tea' alias.

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-01-05 12:00:00.000000

All 7 tea items previously shared the same "tea" alias, causing the last one
loaded (Peppermint Tea) to win. This migration removes the shared "tea" alias
and keeps only specific aliases for each tea type.

After this migration:
- "hot tea" -> Hot Tea
- "iced tea" -> Iced Tea
- "green tea" -> Green Tea
- "earl grey" -> Earl Grey Tea
- "english breakfast" -> English Breakfast Tea
- "chamomile" -> Chamomile Tea
- "peppermint" -> Peppermint Tea

Users saying just "tea" will no longer match any specific item, which allows
the system to prompt for clarification or search for tea options.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# New aliases for tea items (removing shared "tea" alias)
TEA_ALIAS_FIXES = [
    # (item_name, new_aliases)
    ("Hot Tea", "hot tea"),
    ("Iced Tea", "iced tea"),
    ("Green Tea", "green tea"),
    ("Earl Grey Tea", "earl grey"),
    ("English Breakfast Tea", "english breakfast"),
    ("Chamomile Tea", "chamomile"),
    ("Peppermint Tea", "peppermint"),
]


def upgrade() -> None:
    conn = op.get_bind()

    for item_name, new_aliases in TEA_ALIAS_FIXES:
        result = conn.execute(
            sa.text("SELECT id FROM menu_items WHERE name = :name"),
            {"name": item_name}
        )
        row = result.fetchone()

        if row:
            item_id = row[0]
            conn.execute(
                sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
                {"aliases": new_aliases, "id": item_id}
            )
            print(f"Updated {item_name}: aliases = '{new_aliases}'")
        else:
            print(f"Warning: Menu item '{item_name}' not found")


def downgrade() -> None:
    """Restore original aliases with shared 'tea' keyword."""
    conn = op.get_bind()

    # Original aliases from p0q1r2s3t4u5_add_matcha_and_coffee_aliases.py
    ORIGINAL_ALIASES = [
        ("Hot Tea", "tea"),
        ("Iced Tea", "tea"),
        ("Green Tea", "tea, green tea"),
        ("Earl Grey Tea", "tea, earl grey"),
        ("English Breakfast Tea", "tea, english breakfast"),
        ("Chamomile Tea", "tea, chamomile"),
        ("Peppermint Tea", "tea, peppermint"),
    ]

    for item_name, original_aliases in ORIGINAL_ALIASES:
        result = conn.execute(
            sa.text("SELECT id FROM menu_items WHERE name = :name"),
            {"name": item_name}
        )
        row = result.fetchone()

        if row:
            item_id = row[0]
            conn.execute(
                sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
                {"aliases": original_aliases, "id": item_id}
            )
