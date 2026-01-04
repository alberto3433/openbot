"""Add by_pound_categories table for display names.

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2025-01-04 15:00:00.000000

This migration creates a lookup table for by-the-pound category display names.
Maps category slugs (cheese, cold_cut, fish, salad, spread) to human-readable
names (cheeses, cold cuts, smoked fish, salads, spreads).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "v6w7x8y9z0a1"
down_revision: Union[str, None] = "u5v6w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Category slug to display name mapping
CATEGORY_NAMES = {
    "cheese": "cheeses",
    "cold_cut": "cold cuts",
    "fish": "smoked fish",
    "salad": "salads",
    "spread": "spreads",
}


def upgrade() -> None:
    # Create the by_pound_categories table
    op.create_table(
        "by_pound_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create index on slug for fast lookups
    op.create_index("ix_by_pound_categories_slug", "by_pound_categories", ["slug"])

    # Seed the category names
    conn = op.get_bind()
    for slug, display_name in CATEGORY_NAMES.items():
        conn.execute(
            sa.text("""
                INSERT INTO by_pound_categories (slug, display_name)
                VALUES (:slug, :display_name)
            """),
            {"slug": slug, "display_name": display_name}
        )


def downgrade() -> None:
    op.drop_index("ix_by_pound_categories_slug", table_name="by_pound_categories")
    op.drop_table("by_pound_categories")
