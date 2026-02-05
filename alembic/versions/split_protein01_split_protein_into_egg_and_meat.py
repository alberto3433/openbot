"""Split protein category into egg and meat.

Revision ID: split_protein01
Revises: 58e00bead79b
Create Date: 2026-02-04 12:00:00.000000

This migration splits the "protein" ingredient category into:
- "egg": Egg, Egg White, Scrambled Eggs, Egg Salad
- "meat": Everything else (bacon, sausage, ham, turkey, fish/salmon, etc.)

This fixes an issue where ordering "The Classic Omelette" incorrectly set the
`meat` attribute to 'egg' because the fallback mapping mapped "protein" -> "meat".

After this migration, the direct slug match works:
- "meat" category -> "meat" attribute (correct)
- "egg" category -> no matching attribute (skipped, which is correct since eggs
  are the BASE of egg dishes, handled by egg_style/egg_quantity attributes)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "split_protein01"
down_revision: Union[str, None] = "58e00bead79b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Egg-related ingredients to move to "egg" category
EGG_INGREDIENTS = [
    "Egg",
    "Egg White",
    "Scrambled Eggs",
    "Egg Salad",
]


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Add "egg" category
    conn.execute(
        sa.text("""
            INSERT INTO ingredient_categories (slug, display_name, modifier_type, display_order)
            VALUES ('egg', 'Eggs', 'food', 0)
            ON CONFLICT (slug) DO NOTHING
        """)
    )
    print("Created ingredient category: egg")

    # Step 2: Add "meat" category
    conn.execute(
        sa.text("""
            INSERT INTO ingredient_categories (slug, display_name, modifier_type, display_order)
            VALUES ('meat', 'Meats', 'food', 1)
            ON CONFLICT (slug) DO NOTHING
        """)
    )
    print("Created ingredient category: meat")

    # Step 3: Update egg ingredients to "egg" category
    for egg_name in EGG_INGREDIENTS:
        result = conn.execute(
            sa.text("""
                UPDATE ingredients
                SET category = 'egg'
                WHERE category = 'protein' AND name = :name
            """),
            {"name": egg_name}
        )
        if result.rowcount > 0:
            print(f"  Moved '{egg_name}' to 'egg' category")

    # Step 4: Update remaining protein ingredients to "meat" category
    result = conn.execute(
        sa.text("""
            UPDATE ingredients
            SET category = 'meat'
            WHERE category = 'protein'
        """)
    )
    print(f"Moved {result.rowcount} remaining ingredients from 'protein' to 'meat' category")

    # Step 5: Delete the old "protein" category (it should no longer have any ingredients)
    conn.execute(
        sa.text("""
            DELETE FROM ingredient_categories
            WHERE slug = 'protein'
        """)
    )
    print("Deleted old 'protein' ingredient category")

    # Verify the result
    egg_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM ingredients WHERE category = 'egg'")
    ).scalar()
    meat_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM ingredients WHERE category = 'meat'")
    ).scalar()
    protein_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM ingredients WHERE category = 'protein'")
    ).scalar()
    print(f"Result: egg={egg_count}, meat={meat_count}, protein={protein_count}")


def downgrade() -> None:
    conn = op.get_bind()

    # Re-add the "protein" category
    conn.execute(
        sa.text("""
            INSERT INTO ingredient_categories (slug, display_name, modifier_type, display_order)
            VALUES ('protein', 'Protein', 'food', 1)
            ON CONFLICT (slug) DO NOTHING
        """)
    )

    # Move all "egg" and "meat" ingredients back to "protein"
    conn.execute(
        sa.text("""
            UPDATE ingredients
            SET category = 'protein'
            WHERE category IN ('egg', 'meat')
        """)
    )

    # Delete the new categories
    conn.execute(
        sa.text("""
            DELETE FROM ingredient_categories
            WHERE slug IN ('egg', 'meat')
        """)
    )
    print("Reverted: merged egg and meat back into protein category")
