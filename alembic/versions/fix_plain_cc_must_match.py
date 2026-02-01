"""Add must_match constraint to Plain Cream Cheese

When a user orders "everything bagel with bacon egg and cheese", the word
"cheese" was incorrectly matching "Plain Cream Cheese" (a spread) instead of
prompting for the cheese attribute (American, Swiss, etc.).

This migration adds must_match constraints so that "Plain Cream Cheese" only
matches when the input contains "cream cheese" or "plain cc", preventing
the word "cheese" alone from matching.

Revision ID: fix_plain_cc_mm
Revises: unrecognized_02
Create Date: 2026-02-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_plain_cc_mm'
down_revision = 'unrecognized_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Find the Plain Cream Cheese ingredient ID
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE name = 'Plain Cream Cheese'")
    )
    row = result.fetchone()
    if not row:
        print("Warning: Plain Cream Cheese ingredient not found")
        return

    ingredient_id = row[0]

    # Add must_match entries for Plain Cream Cheese
    # These patterns require "cream cheese" or "plain cc" to be in the input
    patterns = ['cream cheese', 'plain cc']

    for pattern in patterns:
        conn.execute(
            sa.text("""
                INSERT INTO ingredient_must_match (ingredient_id, must_match)
                SELECT :ing_id, :pattern
                WHERE NOT EXISTS (
                    SELECT 1 FROM ingredient_must_match
                    WHERE ingredient_id = :ing_id AND must_match = :pattern
                )
            """),
            {"ing_id": ingredient_id, "pattern": pattern}
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Find the Plain Cream Cheese ingredient ID
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE name = 'Plain Cream Cheese'")
    )
    row = result.fetchone()
    if not row:
        return

    ingredient_id = row[0]

    # Remove the must_match entries we added
    patterns = ['cream cheese', 'plain cc']

    for pattern in patterns:
        conn.execute(
            sa.text("""
                DELETE FROM ingredient_must_match
                WHERE ingredient_id = :ing_id AND must_match = :pattern
            """),
            {"ing_id": ingredient_id, "pattern": pattern}
        )
