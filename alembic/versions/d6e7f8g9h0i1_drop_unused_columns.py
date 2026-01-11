"""Drop unused columns from order_items and menu_items.

Revision ID: d6e7f8g9h0i1
Revises: b5c6d7e8f9g1
Create Date: 2026-01-11

This migration removes unused columns:
1. order_items.extra - JSON column that was never used (comment said "remove if unused")
2. menu_items.classifier - String column that was replaced by ItemType.name_filter
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d6e7f8g9h0i1"
down_revision: Union[str, None] = "b5c6d7e8f9g1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop unused columns."""
    # Drop order_items.extra column
    op.drop_column("order_items", "extra")

    # Drop menu_items.classifier column and its index
    op.drop_index("ix_menu_items_classifier", table_name="menu_items")
    op.drop_column("menu_items", "classifier")


def downgrade() -> None:
    """Restore dropped columns."""
    # Restore menu_items.classifier
    op.add_column(
        "menu_items",
        sa.Column("classifier", sa.String(), nullable=True)
    )
    op.create_index("ix_menu_items_classifier", "menu_items", ["classifier"])

    # Restore order_items.extra
    op.add_column(
        "order_items",
        sa.Column("extra", sa.JSON(), nullable=True, default=dict)
    )
