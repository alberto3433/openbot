"""Add ingredient subcategory and option_subcategory_filter

Revision ID: a5b6c7d8e9f0
Revises: 7592c8c48a6c
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6c7d8e9f0a1'
down_revision: Union[str, Sequence[str], None] = '7592c8c48a6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Bread subcategory groupings by slug
BAGEL_SLUGS = [
    'plain_bagel', 'everything_bagel', 'sesame_bagel', 'poppy_bagel',
    'onion_bagel', 'salt_bagel', 'garlic_bagel', 'pumpernickel_bagel',
    'whole_wheat_bagel', 'egg_bagel', 'rainbow_bagel', 'french_toast_bagel',
    'sun_dried_tomato_bagel', 'multigrain_bagel', 'cinnamon_raisin_bagel',
    'asiago_bagel', 'jalapeno_cheddar_bagel', 'jalapeno_bagel',
    'everything_wheat_bagel', 'whole_wheat_everything_bagel',
    'blueberry_bagel',
    'plain_sourdough_bagel', 'everything_sourdough_bagel',
    'sesame_sourdough_bagel',
    'gluten_free_sesame_bagel', 'gluten_free_everything_bagel',
    'gluten_free_cinnamon_raisin_bagel', 'gluten_free_bagel',
    'gf_plain_bagel',
]

FLATZ_SLUGS = [
    'wheat_flatz', 'whole_wheat_flatz', 'whole_wheat_everything_flatz',
    'everything_sourdough_bagel_flatz', 'plain_sourdough_bagel_flatz',
]

WRAP_SLUGS = [
    'wrap', 'whole_wheat_wrap', 'gluten_free_wrap',
]

SLICED_BREAD_SLUGS = [
    'white_bread', 'rye', 'whole_wheat_bread', 'artisan_bread',
]

ROLL_SLUGS = [
    'croissant', 'challah_roll',
]

OTHER_BREAD_SLUGS = [
    'flagel', 'bialy', 'no_bread',
]


def _update_subcategory(conn: sa.engine.Connection, slugs: list[str], subcategory: str) -> None:
    """Set subcategory for a list of ingredient slugs."""
    if not slugs:
        return
    placeholders = ', '.join(f':s{i}' for i in range(len(slugs)))
    params = {f's{i}': slug for i, slug in enumerate(slugs)}
    params['subcategory'] = subcategory
    conn.execute(
        sa.text(
            f"UPDATE ingredients SET subcategory = :subcategory "
            f"WHERE slug IN ({placeholders})"
        ),
        params,
    )


def upgrade() -> None:
    # 1. Add subcategory column to ingredients
    op.add_column('ingredients',
        sa.Column('subcategory', sa.String(50), nullable=True))
    op.create_index('ix_ingredients_subcategory', 'ingredients', ['subcategory'])

    # 2. Add option_subcategory_filter column to item_type_global_attributes
    op.add_column('item_type_global_attributes',
        sa.Column('option_subcategory_filter', sa.String(50), nullable=True))

    # 3. Populate bread subcategories
    conn = op.get_bind()
    _update_subcategory(conn, BAGEL_SLUGS, 'bagel')
    _update_subcategory(conn, FLATZ_SLUGS, 'flatz')
    _update_subcategory(conn, WRAP_SLUGS, 'wrap')
    _update_subcategory(conn, SLICED_BREAD_SLUGS, 'sliced_bread')
    _update_subcategory(conn, ROLL_SLUGS, 'roll')
    _update_subcategory(conn, OTHER_BREAD_SLUGS, 'other')

    # 4. Set filter on bagel item type's bread attribute link
    conn.execute(sa.text("""
        UPDATE item_type_global_attributes
        SET option_subcategory_filter = 'bagel'
        WHERE item_type_id = (SELECT id FROM item_types WHERE slug = 'bagel')
          AND global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'bread')
    """))


def downgrade() -> None:
    op.drop_column('item_type_global_attributes', 'option_subcategory_filter')
    op.drop_index('ix_ingredients_subcategory', table_name='ingredients')
    op.drop_column('ingredients', 'subcategory')
