"""Add ingredient_subcategories table and FK

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ingredient_subcategories table
    op.create_table(
        'ingredient_subcategories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('slug', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column(
            'category_slug', sa.String(50),
            sa.ForeignKey('ingredient_categories.slug'), nullable=False, index=True
        ),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )

    # 2. Populate from existing distinct subcategory values in ingredients
    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO ingredient_subcategories (slug, display_name, category_slug, display_order)
        SELECT DISTINCT
            i.subcategory,
            INITCAP(REPLACE(i.subcategory, '_', ' ')),
            i.category,
            0
        FROM ingredients i
        WHERE i.subcategory IS NOT NULL
        ORDER BY i.subcategory
    """))

    # 3. Add FK constraint on ingredients.subcategory -> ingredient_subcategories.slug
    op.create_foreign_key(
        'fk_ingredients_subcategory_subcategories',
        'ingredients', 'ingredient_subcategories',
        ['subcategory'], ['slug'],
    )


def downgrade() -> None:
    # Drop FK constraint
    op.drop_constraint(
        'fk_ingredients_subcategory_subcategories',
        'ingredients',
        type_='foreignkey',
    )
    # Drop table
    op.drop_table('ingredient_subcategories')
