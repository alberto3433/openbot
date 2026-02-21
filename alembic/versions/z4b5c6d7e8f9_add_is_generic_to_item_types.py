"""Add is_generic column to item_types

Revision ID: z4b5c6d7e8f9
Revises: unrecognized_ingredient_02
Create Date: 2026-02-20

Adds a boolean is_generic column to item_types table.
Generic item types are deprioritized in trigger matching.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "z4b5c6d7e8f9"
down_revision = "unrecognized_ingredient_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "item_types",
        sa.Column("is_generic", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Mark broad catch-all item types as generic
    op.execute(
        "UPDATE item_types SET is_generic = true "
        "WHERE slug IN ('side', 'snack', 'beverage', 'menu_item')"
    )


def downgrade() -> None:
    op.drop_column("item_types", "is_generic")
