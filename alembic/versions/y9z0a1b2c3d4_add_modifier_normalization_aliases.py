"""Add modifier normalization aliases to ingredients.

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2025-01-04 20:00:00.000000

This migration adds aliases to ingredients that were previously handled by
the hardcoded MODIFIER_NORMALIZATIONS dictionary in constants.py.

After this migration, normalization is done via database lookups instead of
the hardcoded dictionary, which can then be removed.

The pattern is: alias -> Ingredient.name (canonical form)
For example: "veggie" -> "Vegetable Cream Cheese"
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "y9z0a1b2c3d4"
down_revision: Union[str, None] = "x8y9z0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Aliases to add/update for existing ingredients
# Format: (ingredient_name, aliases_to_add)
# These correspond to MODIFIER_NORMALIZATIONS entries
ALIAS_UPDATES = [
    # Base cream cheese (spread category) - add "plain cream cheese" alias
    ("Cream Cheese", "plain cream cheese, plain cc"),

    # Cream cheese varieties (cheese category) - add short form aliases
    ("Scallion Cream Cheese", "scallion, scallion cc"),
    ("Vegetable Cream Cheese", "veggie, veggie cream cheese, veggie cc, vegetable"),
    ("Strawberry Cream Cheese", "strawberry, strawberry cc"),
    ("Blueberry Cream Cheese", "blueberry, blueberry cc"),
    ("Olive Cream Cheese", "olive, olive cc"),
    ("Honey Walnut Cream Cheese", "honey walnut, honey walnut cc"),
    ("Tofu Cream Cheese", "tofu, tofu cc"),
    ("Jalapeño Cream Cheese", "jalapeno, jalapeno cream cheese, jalapeno cc"),

    # Additional protein aliases (in case any were missed)
    ("Nova Scotia Salmon", "nova scotia salmon"),  # Add the full name as alias too
]


def upgrade() -> None:
    conn = op.get_bind()

    for name, new_aliases in ALIAS_UPDATES:
        # Get current aliases for this ingredient
        result = conn.execute(
            sa.text("SELECT id, aliases FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        row = result.fetchone()

        if row:
            ing_id = row[0]
            current_aliases = row[1] or ""

            # Merge aliases (avoid duplicates, case-insensitive)
            existing = set(a.strip().lower() for a in current_aliases.split(",") if a.strip())
            new = set(a.strip().lower() for a in new_aliases.split(",") if a.strip())
            merged = existing | new

            # Sort for consistency
            merged_str = ", ".join(sorted(merged))

            conn.execute(
                sa.text("UPDATE ingredients SET aliases = :aliases WHERE id = :id"),
                {"aliases": merged_str, "id": ing_id}
            )
            print(f"Updated aliases for {name}: {merged_str}")
        else:
            print(f"Warning: Ingredient '{name}' not found in database")


def downgrade() -> None:
    # We don't remove aliases on downgrade as it's hard to track
    # what was added vs what was original
    pass
