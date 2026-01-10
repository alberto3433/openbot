"""Rename drink_modifier to milk_sweetener_syrup

Revision ID: mss_rename_001
Revises: b3c4d5e6f7g8
Create Date: 2025-01-09

This migration renames the drink_modifier attribute to milk_sweetener_syrup
for a more natural question flow ("What kind of milk, sweetener, or syrup?").

Changes:
1. item_type_attributes: slug 'drink_modifier' -> 'milk_sweetener_syrup'
2. item_type_attributes: display_name 'Drink Modifier' -> 'Milk, Sweetener, or Syrup'
3. item_type_attributes: ingredient_group 'drink_modifier' -> 'milk_sweetener_syrup'
4. item_type_ingredients: ingredient_group 'drink_modifier' -> 'milk_sweetener_syrup'
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'mss_rename_001'
down_revision = 'b3c4d5e6f7g8'
branch_labels = None
depends_on = None


def upgrade():
    # Update item_type_attributes table
    # Change slug from 'drink_modifier' to 'milk_sweetener_syrup'
    # Change display_name from 'Drink Modifier' to 'Milk, Sweetener, or Syrup'
    # Change ingredient_group from 'drink_modifier' to 'milk_sweetener_syrup'
    op.execute("""
        UPDATE item_type_attributes
        SET slug = 'milk_sweetener_syrup',
            display_name = 'Milk, Sweetener, or Syrup',
            ingredient_group = 'milk_sweetener_syrup'
        WHERE slug = 'drink_modifier'
    """)

    # Update item_type_ingredients table
    # Change ingredient_group from 'drink_modifier' to 'milk_sweetener_syrup'
    op.execute("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'milk_sweetener_syrup'
        WHERE ingredient_group = 'drink_modifier'
    """)


def downgrade():
    # Revert item_type_attributes table
    op.execute("""
        UPDATE item_type_attributes
        SET slug = 'drink_modifier',
            display_name = 'Drink Modifier',
            ingredient_group = 'drink_modifier'
        WHERE slug = 'milk_sweetener_syrup'
    """)

    # Revert item_type_ingredients table
    op.execute("""
        UPDATE item_type_ingredients
        SET ingredient_group = 'drink_modifier'
        WHERE ingredient_group = 'milk_sweetener_syrup'
    """)
