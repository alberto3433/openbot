"""Fix size attribute to use attribute_options for iced upcharge

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-01-08 15:00:00.000000

The 'size' attribute for sized_beverage was set to loads_from_ingredients=True,
which causes it to load options from item_type_ingredients table. However, the
iced_price_modifier values are stored in attribute_options table.

This migration sets loads_from_ingredients=False for the 'size' attribute on
both sized_beverage and espresso item types, so they use attribute_options
which has the correct iced_price_modifier values.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i3j4k5l6m7n8'
down_revision: Union[str, Sequence[str], None] = 'h2i3j4k5l6m7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set loads_from_ingredients=False for size attribute to use attribute_options."""
    conn = op.get_bind()

    # Get item type IDs for sized_beverage and espresso
    result = conn.execute(sa.text("""
        SELECT id, slug FROM item_types
        WHERE slug IN ('sized_beverage', 'espresso')
    """))
    item_type_map = {row[1]: row[0] for row in result}

    for slug, item_type_id in item_type_map.items():
        # Update size attribute to NOT use loads_from_ingredients
        # This way it will use attribute_options which has iced_price_modifier
        result = conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = FALSE,
                ingredient_group = NULL
            WHERE item_type_id = :item_type_id
            AND slug = 'size'
        """), {'item_type_id': item_type_id})

        print(f"Updated {slug}.size: loads_from_ingredients=False")


def downgrade() -> None:
    """Revert size attribute to use loads_from_ingredients."""
    conn = op.get_bind()

    # Get item type IDs
    result = conn.execute(sa.text("""
        SELECT id, slug FROM item_types
        WHERE slug IN ('sized_beverage', 'espresso')
    """))
    item_type_map = {row[1]: row[0] for row in result}

    for slug, item_type_id in item_type_map.items():
        # Revert to using loads_from_ingredients
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = TRUE,
                ingredient_group = 'size'
            WHERE item_type_id = :item_type_id
            AND slug = 'size'
        """), {'item_type_id': item_type_id})

        print(f"Reverted {slug}.size: loads_from_ingredients=True")
