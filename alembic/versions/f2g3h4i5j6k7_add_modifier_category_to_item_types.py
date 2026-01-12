"""Add modifier_category column to item_types table.

Revision ID: f2g3h4i5j6k7
Revises: e1f2g3h4i5j6
Create Date: 2026-01-12

This migration adds a modifier_category column to item_types to indicate
whether the item type uses "food" style modifiers (proteins, cheeses, toppings)
or "beverage" style modifiers (milk, sweetener, syrup).

This replaces the hardcoded MODIFIER_EXTRACTION_TYPE constant in menu_item_config_handler.py.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2g3h4i5j6k7"
down_revision: Union[str, None] = "e1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mapping of item type slugs to their modifier category
# This replaces the hardcoded MODIFIER_EXTRACTION_TYPE in menu_item_config_handler.py
MODIFIER_CATEGORIES = [
    # Food items use bagel-style modifiers (proteins, cheeses, toppings, spreads)
    ("deli_sandwich", "food"),
    ("egg_sandwich", "food"),
    ("fish_sandwich", "food"),
    ("spread_sandwich", "food"),
    ("bagel", "food"),
    ("omelette", "food"),
    ("salad_sandwich", "food"),
    # Beverage items use coffee-style modifiers (milk, sweetener, syrup)
    ("espresso", "beverage"),
    ("sized_beverage", "beverage"),
]


def upgrade() -> None:
    # Add the new column (nullable to allow item types that don't need modifiers)
    op.add_column("item_types", sa.Column("modifier_category", sa.String(20), nullable=True))

    # Populate the values for known item types
    conn = op.get_bind()
    for slug, category in MODIFIER_CATEGORIES:
        result = conn.execute(
            sa.text("UPDATE item_types SET modifier_category = :category WHERE slug = :slug"),
            {"category": category, "slug": slug}
        )
        if result.rowcount > 0:
            print(f"Set modifier_category for '{slug}' to '{category}'")
        else:
            print(f"Item type '{slug}' not found, skipping")


def downgrade() -> None:
    op.drop_column("item_types", "modifier_category")
