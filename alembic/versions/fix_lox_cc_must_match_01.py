"""Fix Lox Cream Cheese must_match constraint

Previously, Lox Cream Cheese had must_match='lox', which incorrectly matched
inputs like "lox and cream cheese" (meaning lox + cream cheese separately).

This migration changes the must_match to require "lox cream" or "lox cc" so that
"lox and cream cheese" correctly matches Plain Cream Cheese instead.

Revision ID: fix_lox_cc_mm_01
Revises: 241c0e3f580d
Create Date: 2025-01-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_lox_cc_mm_01'
down_revision = '241c0e3f580d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get connection for raw SQL
    conn = op.get_bind()

    # Find the Lox Cream Cheese ingredient ID
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE name = 'Lox Cream Cheese'")
    )
    row = result.fetchone()
    if not row:
        print("Warning: Lox Cream Cheese ingredient not found")
        return

    ingredient_id = row[0]

    # Update existing must_match from 'lox' to 'lox cream'
    conn.execute(
        sa.text("""
            UPDATE ingredient_must_match
            SET must_match = 'lox cream'
            WHERE ingredient_id = :ing_id AND must_match = 'lox'
        """),
        {"ing_id": ingredient_id}
    )

    # Add 'lox cc' as alternative must_match (if not already present)
    conn.execute(
        sa.text("""
            INSERT INTO ingredient_must_match (ingredient_id, must_match)
            SELECT :ing_id, 'lox cc'
            WHERE NOT EXISTS (
                SELECT 1 FROM ingredient_must_match
                WHERE ingredient_id = :ing_id AND must_match = 'lox cc'
            )
        """),
        {"ing_id": ingredient_id}
    )


def downgrade() -> None:
    # Get connection for raw SQL
    conn = op.get_bind()

    # Find the Lox Cream Cheese ingredient ID
    result = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE name = 'Lox Cream Cheese'")
    )
    row = result.fetchone()
    if not row:
        return

    ingredient_id = row[0]

    # Revert: change 'lox cream' back to 'lox'
    conn.execute(
        sa.text("""
            UPDATE ingredient_must_match
            SET must_match = 'lox'
            WHERE ingredient_id = :ing_id AND must_match = 'lox cream'
        """),
        {"ing_id": ingredient_id}
    )

    # Remove 'lox cc' entry
    conn.execute(
        sa.text("""
            DELETE FROM ingredient_must_match
            WHERE ingredient_id = :ing_id AND must_match = 'lox cc'
        """),
        {"ing_id": ingredient_id}
    )
