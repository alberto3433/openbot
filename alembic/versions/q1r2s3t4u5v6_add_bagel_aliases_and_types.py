"""Add aliases column to ingredients and missing bagel types.

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2025-01-04

This migration:
1. Adds 'aliases' column to ingredients table for synonym matching
2. Adds missing bagel types (egg, multigrain, asiago, jalapeno, blueberry)
3. Populates aliases for existing bagel types (wheat, cinnamon, raisin, gluten-free)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q1r2s3t4u5v6'
down_revision = 'p0q1r2s3t4u5'
branch_labels = None
depends_on = None


# Missing bagel types to add (unit='each', base_price=2.2 matches existing bagels)
NEW_BAGEL_TYPES = [
    {"name": "Egg Bagel", "category": "bread", "unit": "each", "base_price": 2.2},
    {"name": "Multigrain Bagel", "category": "bread", "unit": "each", "base_price": 2.2},
    {"name": "Asiago Bagel", "category": "bread", "unit": "each", "base_price": 2.2},
    {"name": "Jalapeno Bagel", "category": "bread", "unit": "each", "base_price": 2.5},
    {"name": "Blueberry Bagel", "category": "bread", "unit": "each", "base_price": 2.5},
]

# Aliases for existing bagel types
# Maps ingredient name to comma-separated aliases
BAGEL_ALIASES = {
    "Whole Wheat Bagel": "wheat",
    "Cinnamon Raisin Bagel": "cinnamon, raisin",
    "Gluten Free Bagel": "gluten-free, gf",
    "Gluten Free Everything Bagel": "gluten-free everything, gf everything",
    "Bialy": "bialy bagel",  # Allow "bialy bagel" to match
}


def upgrade() -> None:
    # Add aliases column to ingredients table
    op.add_column('ingredients', sa.Column('aliases', sa.Text(), nullable=True))

    # Add missing bagel types
    conn = op.get_bind()

    for bagel in NEW_BAGEL_TYPES:
        # Check if already exists
        result = conn.execute(
            sa.text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": bagel["name"]}
        )
        if result.fetchone() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO ingredients (name, category, unit, base_price, is_available, track_inventory)
                    VALUES (:name, :category, :unit, :base_price, true, false)
                """),
                bagel
            )

    # Populate aliases for existing bagel types
    for name, aliases in BAGEL_ALIASES.items():
        conn.execute(
            sa.text("UPDATE ingredients SET aliases = :aliases WHERE name = :name"),
            {"name": name, "aliases": aliases}
        )


def downgrade() -> None:
    # Remove aliases column
    op.drop_column('ingredients', 'aliases')

    # Remove added bagel types
    conn = op.get_bind()
    for bagel in NEW_BAGEL_TYPES:
        conn.execute(
            sa.text("DELETE FROM ingredients WHERE name = :name"),
            {"name": bagel["name"]}
        )
