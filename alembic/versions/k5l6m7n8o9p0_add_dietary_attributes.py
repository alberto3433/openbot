"""add_dietary_attributes

Revision ID: k5l6m7n8o9p0
Revises: 3f6de55b8abc
Create Date: 2026-01-02

Adds dietary and allergen attribute columns to Ingredient and MenuItem tables.

For Ingredients (source of truth):
- is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher: Boolean NOT NULL DEFAULT FALSE
- contains_eggs, contains_fish, contains_sesame, contains_nuts: Boolean NOT NULL DEFAULT FALSE

For MenuItems (computed/cached from ingredients):
- Same columns but nullable (NULL = not computed yet)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k5l6m7n8o9p0'
down_revision: Union[str, Sequence[str], None] = '3f6de55b8abc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Define the dietary attribute columns
DIETARY_COLUMNS = [
    'is_vegan',
    'is_vegetarian',
    'is_gluten_free',
    'is_dairy_free',
    'is_kosher',
    'contains_eggs',
    'contains_fish',
    'contains_sesame',
    'contains_nuts',
]


def upgrade() -> None:
    """Add dietary attribute columns to ingredients and menu_items tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Get existing columns for ingredients table
    ingredient_columns = [col['name'] for col in inspector.get_columns('ingredients')]

    # Add columns to ingredients table (NOT NULL with default FALSE)
    for col_name in DIETARY_COLUMNS:
        if col_name not in ingredient_columns:
            op.add_column(
                'ingredients',
                sa.Column(col_name, sa.Boolean(), nullable=False, server_default='0')
            )

    # Get existing columns for menu_items table
    menu_item_columns = [col['name'] for col in inspector.get_columns('menu_items')]

    # Add columns to menu_items table (NULLABLE - NULL means not computed yet)
    for col_name in DIETARY_COLUMNS:
        if col_name not in menu_item_columns:
            op.add_column(
                'menu_items',
                sa.Column(col_name, sa.Boolean(), nullable=True)
            )


def downgrade() -> None:
    """Remove dietary attribute columns from ingredients and menu_items tables."""
    # Remove from menu_items
    for col_name in DIETARY_COLUMNS:
        op.drop_column('menu_items', col_name)

    # Remove from ingredients
    for col_name in DIETARY_COLUMNS:
        op.drop_column('ingredients', col_name)
