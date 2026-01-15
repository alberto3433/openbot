"""add_code_field_name_to_ingredient_categories

Revision ID: ea1b14f8078d
Revises: d8876ca1d8a0
Create Date: 2026-01-14 15:53:04.403871

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea1b14f8078d'
down_revision: Union[str, Sequence[str], None] = 'd8876ca1d8a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add code_field_name and is_multi_select columns to ingredient_categories.

    These columns enable data-driven modifier field configuration, replacing
    the hardcoded INGREDIENT_GROUP_TO_FIELD mapping in menu_data_cache.py.

    - code_field_name: The Python property name on MenuItemTask (e.g., "toppings")
      If NULL, defaults to the category slug (e.g., "milk" -> "milk")
    - is_multi_select: True if this category supports multiple selections
      If NULL, defaults to False (single selection)
    """
    # Add columns
    op.add_column('ingredient_categories',
        sa.Column('code_field_name', sa.String(50), nullable=True))
    op.add_column('ingredient_categories',
        sa.Column('is_multi_select', sa.Boolean(), nullable=True, server_default='false'))

    # Populate values based on the hardcoded INGREDIENT_GROUP_TO_FIELD mapping:
    # - spread: field_name="spread", is_list=False (matches slug, so NULL is fine)
    # - protein: field_name="extra_protein", is_list=False
    # - topping: field_name="toppings", is_list=True
    # - cheese: field_name="toppings", is_list=True (cheeses stored in toppings)
    # - milk: field_name="milk", is_list=False (matches slug, so NULL is fine)
    # - sweetener: field_name="sweeteners", is_list=True
    # - syrup: field_name="flavor_syrups", is_list=True

    ingredient_categories = sa.table(
        'ingredient_categories',
        sa.column('slug', sa.String),
        sa.column('code_field_name', sa.String),
        sa.column('is_multi_select', sa.Boolean),
    )

    # protein -> extra_protein (single select)
    op.execute(
        ingredient_categories.update()
        .where(ingredient_categories.c.slug == 'protein')
        .values(code_field_name='extra_protein', is_multi_select=False)
    )

    # topping -> toppings (multi select)
    op.execute(
        ingredient_categories.update()
        .where(ingredient_categories.c.slug == 'topping')
        .values(code_field_name='toppings', is_multi_select=True)
    )

    # cheese -> toppings (multi select, stored with toppings)
    op.execute(
        ingredient_categories.update()
        .where(ingredient_categories.c.slug == 'cheese')
        .values(code_field_name='toppings', is_multi_select=True)
    )

    # sweetener -> sweeteners (multi select)
    op.execute(
        ingredient_categories.update()
        .where(ingredient_categories.c.slug == 'sweetener')
        .values(code_field_name='sweeteners', is_multi_select=True)
    )

    # syrup -> flavor_syrups (multi select)
    op.execute(
        ingredient_categories.update()
        .where(ingredient_categories.c.slug == 'syrup')
        .values(code_field_name='flavor_syrups', is_multi_select=True)
    )

    # Categories that match their slug don't need code_field_name set:
    # - spread (NULL -> uses "spread")
    # - milk (NULL -> uses "milk")
    # - sauce, bread, etc. (NULL -> uses slug)


def downgrade() -> None:
    """Remove code_field_name and is_multi_select columns from ingredient_categories."""
    op.drop_column('ingredient_categories', 'is_multi_select')
    op.drop_column('ingredient_categories', 'code_field_name')
