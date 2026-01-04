"""Add base spreads to ingredients table.

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2025-01-04 12:00:00.000000

This migration adds base spread ingredients (cream cheese, butter, etc.)
to the ingredients table with category='spread'. These replace the hardcoded
SPREADS constant in constants.py.

Aliases are used for common abbreviations and synonyms.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic
revision = "r2s3t4u5v6w7"
down_revision = "q1r2s3t4u5v6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add base spread ingredients with aliases."""
    # Get connection for raw SQL
    conn = op.get_bind()

    # Base spreads with their aliases
    # Format: (name, aliases)
    spreads = [
        ("Cream Cheese", "cc, plain cc, regular cc"),
        ("Butter", None),
        ("Peanut Butter", "pb"),
        ("Jelly", None),
        ("Jam", None),
        ("Nutella", None),
        ("Hummus", None),
        ("Avocado", "avo"),
    ]

    for name, aliases in spreads:
        # Check if ingredient already exists
        result = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE LOWER(name) = LOWER(:name)"),
            {"name": name}
        )
        existing = result.fetchone()

        if existing:
            # Update existing ingredient to have spread category and aliases
            conn.execute(
                sa.text("""
                    UPDATE ingredients
                    SET category = 'spread', aliases = :aliases
                    WHERE id = :id
                """),
                {"id": existing[0], "aliases": aliases}
            )
        else:
            # Insert new ingredient
            conn.execute(
                sa.text("""
                    INSERT INTO ingredients (name, category, unit, track_inventory, is_available, aliases)
                    VALUES (:name, 'spread', 'serving', FALSE, TRUE, :aliases)
                """),
                {"name": name, "aliases": aliases}
            )


def downgrade() -> None:
    """Remove base spread ingredients."""
    conn = op.get_bind()

    # Delete the spread ingredients we added
    spread_names = [
        "Cream Cheese", "Butter", "Peanut Butter", "Jelly",
        "Jam", "Nutella", "Hummus", "Avocado"
    ]

    for name in spread_names:
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE LOWER(name) = LOWER(:name) AND category = 'spread'"),
            {"name": name}
        )
