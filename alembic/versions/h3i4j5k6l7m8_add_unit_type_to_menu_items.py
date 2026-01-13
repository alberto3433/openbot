"""Add unit_type to menu_items

This migration adds a unit_type column to distinguish how items are sold:
- 'each' (default): sold individually (bagels, sandwiches, drinks)
- 'by_weight': sold by weight (cream cheese by the lb, smoked fish)
- 'dozen': sold by the dozen (bagel packages)

This enables data-driven detection of by-weight items instead of
relying on naming conventions like "(1/4 lb)" in item names.

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-01-13
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "h3i4j5k6l7m8"
down_revision = "g2h3i4j5k6l7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add unit_type column with default 'each'
    op.add_column(
        "menu_items",
        sa.Column(
            "unit_type",
            sa.String(20),
            nullable=False,
            server_default="each",
        ),
    )

    # Mark by-weight items (items with weight in name)
    op.execute("""
        UPDATE menu_items
        SET unit_type = 'by_weight'
        WHERE name LIKE '%(1/4 lb)%'
           OR name LIKE '%(1/2 lb)%'
           OR name LIKE '%(1 lb)%'
    """)

    # Mark dozen items (bagel packages, etc.)
    op.execute("""
        UPDATE menu_items
        SET unit_type = 'dozen'
        WHERE name LIKE '%Dozen%'
    """)


def downgrade() -> None:
    op.drop_column("menu_items", "unit_type")
