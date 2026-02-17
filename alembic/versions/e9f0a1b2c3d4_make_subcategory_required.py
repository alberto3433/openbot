"""Make ingredient subcategory required (NOT NULL)

Disambiguate duplicate 'other' subcategory slugs, ensure every distinct
ingredients.subcategory value has a matching row in ingredient_subcategories,
create FK constraint, then set NOT NULL.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Disambiguate 'other' subcategory slug shared across bread and spread
    conn.execute(sa.text(
        "UPDATE ingredients SET subcategory = 'other_bread' "
        "WHERE subcategory = 'other' AND category = 'bread'"
    ))
    conn.execute(sa.text(
        "UPDATE ingredients SET subcategory = 'other_spread' "
        "WHERE subcategory = 'other' AND category = 'spread'"
    ))

    # 2. Insert subcategory rows for every distinct ingredient subcategory value
    #    that doesn't already have a matching row
    conn.execute(sa.text("""
        INSERT INTO ingredient_subcategories (slug, display_name, category_slug, display_order)
        SELECT DISTINCT
            i.subcategory,
            INITCAP(REPLACE(i.subcategory, '_', ' ')),
            i.category,
            0
        FROM ingredients i
        WHERE i.subcategory IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM ingredient_subcategories isub
              WHERE isub.slug = i.subcategory
          )
    """))

    # 3. Insert catch-all subcategories for categories with no ingredients
    #    (ensures every category has at least one subcategory)
    conn.execute(sa.text("""
        INSERT INTO ingredient_subcategories (slug, display_name, category_slug, display_order)
        SELECT ic.slug, ic.display_name, ic.slug, 0
        FROM ingredient_categories ic
        WHERE NOT EXISTS (
            SELECT 1 FROM ingredient_subcategories isub
            WHERE isub.category_slug = ic.slug
        )
    """))

    # 4. Assign subcategory to any ingredients that still have NULL
    conn.execute(sa.text("""
        UPDATE ingredients i SET subcategory = (
            SELECT isub.slug FROM ingredient_subcategories isub
            WHERE isub.category_slug = i.category
            ORDER BY isub.display_order, isub.slug LIMIT 1
        ) WHERE i.subcategory IS NULL
    """))

    # 5. Create FK constraint
    op.create_foreign_key(
        'fk_ingredients_subcategory_subcategories',
        'ingredients', 'ingredient_subcategories',
        ['subcategory'], ['slug'],
    )

    # 6. Make subcategory NOT NULL
    op.alter_column('ingredients', 'subcategory', nullable=False)


def downgrade() -> None:
    op.drop_constraint(
        'fk_ingredients_subcategory_subcategories',
        'ingredients',
        type_='foreignkey',
    )
    op.alter_column('ingredients', 'subcategory', nullable=True)
