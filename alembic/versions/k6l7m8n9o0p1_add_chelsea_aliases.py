"""Add Chelsea aliases to The Chelsea Club menu item

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-01-09

This migration adds "the chelsea" and "chelsea" as aliases for "The Chelsea Club"
menu item to enable partial matching when customers say "the chelsea" or just "chelsea".
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Get current aliases for The Chelsea Club
    result = conn.execute(
        text("SELECT id, aliases FROM menu_items WHERE name = 'The Chelsea Club'")
    )
    row = result.fetchone()

    if not row:
        print("Warning: 'The Chelsea Club' menu item not found")
        return

    item_id = row[0]
    current_aliases = row[1] or ""

    # Parse existing aliases
    existing = set()
    if current_aliases:
        existing = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}

    # New aliases to add
    new_aliases = ["the chelsea", "chelsea", "chelsea club"]

    # Add only aliases that don't already exist
    aliases_to_add = [a for a in new_aliases if a.lower() not in existing]

    if not aliases_to_add:
        print("All Chelsea aliases already exist")
        return

    # Build new aliases string
    if current_aliases:
        updated_aliases = current_aliases + ", " + ", ".join(aliases_to_add)
    else:
        updated_aliases = ", ".join(aliases_to_add)

    # Update the menu item
    conn.execute(
        text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
        {"aliases": updated_aliases, "id": item_id}
    )

    print(f"Added aliases to The Chelsea Club: {aliases_to_add}")


def downgrade() -> None:
    conn = op.get_bind()

    # Get current aliases
    result = conn.execute(
        text("SELECT id, aliases FROM menu_items WHERE name = 'The Chelsea Club'")
    )
    row = result.fetchone()

    if not row:
        return

    item_id = row[0]
    current_aliases = row[1] or ""

    if not current_aliases:
        return

    # Remove the added aliases
    aliases_to_remove = {"the chelsea", "chelsea", "chelsea club"}
    remaining = [
        a.strip() for a in current_aliases.split(",")
        if a.strip() and a.strip().lower() not in aliases_to_remove
    ]

    updated_aliases = ", ".join(remaining) if remaining else None

    conn.execute(
        text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
        {"aliases": updated_aliases, "id": item_id}
    )

    print("Removed Chelsea aliases from The Chelsea Club")
