"""Merge sauce category into topping

This migration merges the 'sauce' ingredient category into 'topping' to simplify
the data model. Sauces (mayo, mustard, etc.) will now be categorized as toppings.

This enables a simpler, data-driven parsing loop without special combination logic.

Revision ID: merge_sauce_into_topping
Revises: add_gattr_property_name
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'merge_sauce_into_topping'
down_revision: Union[str, Sequence[str], None] = 'add_gattr_property_name'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge sauce ingredients into topping category."""
    conn = op.get_bind()

    # Step 1: Update all ingredients with category='sauce' to category='topping'
    conn.execute(
        sa.text("UPDATE ingredients SET category = 'topping' WHERE category = 'sauce'")
    )

    # Step 2: Delete the 'sauce' row from ingredient_categories
    conn.execute(
        sa.text("DELETE FROM ingredient_categories WHERE slug = 'sauce'")
    )


def downgrade() -> None:
    """Restore sauce category (partial - won't restore which ingredients were sauces)."""
    conn = op.get_bind()

    # Re-create the sauce category
    conn.execute(
        sa.text("""
            INSERT INTO ingredient_categories (slug, display_name, modifier_type, display_order, code_field_name, is_multi_select)
            VALUES ('sauce', 'Sauces', 'food', 5, 'sauces', true)
        """)
    )

    # Note: We cannot automatically restore which ingredients were originally sauces
    # A manual data fix would be needed for full rollback
