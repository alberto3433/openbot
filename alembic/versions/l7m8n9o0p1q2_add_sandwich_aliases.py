"""Add aliases to deli classics and smoked fish sandwiches

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2026-01-09

This migration adds partial-match aliases for sandwiches that currently have
no aliases, enabling customers to order using common short names like
"turkey sandwich" instead of "All-Natural Smoked Turkey Sandwich".

Deli Classics:
- All-Natural Smoked Turkey Sandwich -> turkey sandwich, smoked turkey sandwich
- Black Forest Ham Sandwich -> ham sandwich, black forest ham sandwich
- Chicken Cutlet Sandwich -> chicken cutlet sandwich, chicken sandwich
- Homemade Roast Turkey Sandwich -> roast turkey sandwich
- Hot Corned Beef Sandwich -> corned beef sandwich, hot corned beef sandwich
- Kosher Beef Salami Sandwich -> salami sandwich, beef salami sandwich
- Top Round Roast Beef Sandwich -> roast beef sandwich

Smoked Fish:
- Baked Kippered Salmon Sandwich -> kippered salmon sandwich, kippered sandwich
- Everything Seeded Salmon Sandwich -> everything salmon sandwich, seeded salmon sandwich
- Pastrami Salmon Sandwich -> pastrami salmon sandwich
- Scottish Salmon Sandwich -> scottish salmon sandwich
- Wild Coho Salmon Sandwich -> coho salmon sandwich, coho sandwich
- Wild Pacific Salmon Sandwich -> pacific salmon sandwich
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'l7m8n9o0p1q2'
down_revision = 'p0q1r2s3t4u6'
branch_labels = None
depends_on = None


# Menu items and their new aliases to add
# Format: (menu_item_name, [aliases_to_add])
ALIASES_TO_ADD = [
    # Deli Classics
    ("All-Natural Smoked Turkey Sandwich", ["turkey sandwich", "smoked turkey sandwich"]),
    ("Black Forest Ham Sandwich", ["ham sandwich", "black forest ham sandwich"]),
    ("Chicken Cutlet Sandwich", ["chicken cutlet sandwich", "chicken sandwich"]),
    ("Homemade Roast Turkey Sandwich", ["roast turkey sandwich"]),
    ("Hot Corned Beef Sandwich", ["corned beef sandwich", "hot corned beef sandwich"]),
    ("Kosher Beef Salami Sandwich", ["salami sandwich", "beef salami sandwich"]),
    ("Top Round Roast Beef Sandwich", ["roast beef sandwich"]),

    # Smoked Fish
    ("Baked Kippered Salmon Sandwich", ["kippered salmon sandwich", "kippered sandwich"]),
    ("Everything Seeded Salmon Sandwich", ["everything salmon sandwich", "seeded salmon sandwich"]),
    ("Pastrami Salmon Sandwich", ["pastrami salmon sandwich"]),
    ("Scottish Salmon Sandwich", ["scottish salmon sandwich"]),
    ("Wild Coho Salmon Sandwich", ["coho salmon sandwich", "coho sandwich"]),
    ("Wild Pacific Salmon Sandwich", ["pacific salmon sandwich"]),
]


def upgrade() -> None:
    conn = op.get_bind()

    for menu_item_name, new_aliases in ALIASES_TO_ADD:
        # Get current aliases
        result = conn.execute(
            text("SELECT id, aliases FROM menu_items WHERE name = :name"),
            {"name": menu_item_name}
        )
        row = result.fetchone()

        if not row:
            print(f"Warning: '{menu_item_name}' not found, skipping")
            continue

        item_id = row[0]
        current_aliases = row[1] or ""

        # Parse existing aliases
        existing = set()
        if current_aliases:
            existing = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}

        # Add only aliases that don't already exist
        aliases_to_add = [a for a in new_aliases if a.lower() not in existing]

        if not aliases_to_add:
            print(f"All aliases for '{menu_item_name}' already exist")
            continue

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

        print(f"Added aliases to '{menu_item_name}': {aliases_to_add}")


def downgrade() -> None:
    conn = op.get_bind()

    for menu_item_name, aliases_to_remove in ALIASES_TO_ADD:
        # Get current aliases
        result = conn.execute(
            text("SELECT id, aliases FROM menu_items WHERE name = :name"),
            {"name": menu_item_name}
        )
        row = result.fetchone()

        if not row:
            continue

        item_id = row[0]
        current_aliases = row[1] or ""

        if not current_aliases:
            continue

        # Remove the added aliases
        remove_set = {a.lower() for a in aliases_to_remove}
        remaining = [
            a.strip() for a in current_aliases.split(",")
            if a.strip() and a.strip().lower() not in remove_set
        ]

        updated_aliases = ", ".join(remaining) if remaining else None

        conn.execute(
            text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": updated_aliases, "id": item_id}
        )

        print(f"Removed aliases from '{menu_item_name}'")
