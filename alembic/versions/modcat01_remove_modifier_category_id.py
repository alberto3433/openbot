"""Remove modifier_category_id column from global_attribute_options.

The modifier_category is now derived at runtime from ingredient.category
via the Ingredient.modifier_category relationship.

Revision ID: modcat01
Revises: weight_alias_01
Create Date: 2025-02-08

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'modcat01'
down_revision = 'weight_alias_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add missing ModifierCategory entries so all ingredient categories have a mapping
    # Existing entries: milks, spreads, sweeteners, syrups
    # Missing: breads, cheeses, condiments, eggs, meats, teas, toppings
    op.execute("""
        INSERT INTO modifier_categories (slug, display_name, ingredient_category, loads_from_ingredients)
        VALUES
            ('breads', 'Breads', 'bread', true),
            ('cheeses', 'Cheeses', 'cheese', true),
            ('condiments', 'Condiments', 'condiment', true),
            ('eggs', 'Eggs', 'egg', true),
            ('meats', 'Meats', 'meat', true),
            ('teas', 'Teas', 'tea', true),
            ('toppings', 'Toppings', 'topping', true)
        ON CONFLICT (slug) DO NOTHING;
    """)

    # Step 2: Drop the foreign key constraint first
    op.drop_constraint(
        'fk_global_attribute_options_modifier_category',
        'global_attribute_options',
        type_='foreignkey'
    )

    # Step 3: Drop the index on modifier_category_id
    op.drop_index(
        'ix_global_attribute_options_modifier_category_id',
        table_name='global_attribute_options'
    )

    # Step 4: Drop the column
    op.drop_column('global_attribute_options', 'modifier_category_id')


def downgrade() -> None:
    # Add the column back
    op.add_column(
        'global_attribute_options',
        sa.Column('modifier_category_id', sa.Integer(), nullable=True)
    )

    # Recreate the index
    op.create_index(
        'ix_global_attribute_options_modifier_category_id',
        'global_attribute_options',
        ['modifier_category_id'],
        unique=False
    )

    # Recreate the foreign key constraint
    op.create_foreign_key(
        'fk_global_attribute_options_modifier_category',
        'global_attribute_options',
        'modifier_categories',
        ['modifier_category_id'],
        ['id'],
        ondelete='SET NULL'
    )
