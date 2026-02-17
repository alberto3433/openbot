"""Change ingredients.subcategory from slug FK to integer ID FK

Replace the string-based FK (ingredients.subcategory -> ingredient_subcategories.slug)
with an integer-based FK (ingredients.subcategory_id -> ingredient_subcategories.id).

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add subcategory_id integer column (nullable initially)
    op.add_column('ingredients', sa.Column('subcategory_id', sa.Integer(), nullable=True))

    # 2. Populate subcategory_id from the slug-based join
    conn.execute(sa.text("""
        UPDATE ingredients i
        SET subcategory_id = isub.id
        FROM ingredient_subcategories isub
        WHERE i.subcategory = isub.slug
    """))

    # 3. Drop the old slug-based FK constraint
    op.drop_constraint(
        'fk_ingredients_subcategory_subcategories',
        'ingredients',
        type_='foreignkey',
    )

    # 4. Drop the old subcategory string column and its index
    op.drop_index('ix_ingredients_subcategory', table_name='ingredients')
    op.drop_column('ingredients', 'subcategory')

    # 5. Set NOT NULL on subcategory_id
    op.alter_column('ingredients', 'subcategory_id', nullable=False)

    # 6. Add FK constraint and index on subcategory_id
    op.create_foreign_key(
        'fk_ingredients_subcategory_id',
        'ingredients', 'ingredient_subcategories',
        ['subcategory_id'], ['id'],
    )
    op.create_index('ix_ingredients_subcategory_id', 'ingredients', ['subcategory_id'])


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Re-add the subcategory string column
    op.add_column('ingredients', sa.Column('subcategory', sa.String(50), nullable=True))
    op.create_index('ix_ingredients_subcategory', 'ingredients', ['subcategory'])

    # 2. Populate from the integer FK join
    conn.execute(sa.text("""
        UPDATE ingredients i
        SET subcategory = isub.slug
        FROM ingredient_subcategories isub
        WHERE i.subcategory_id = isub.id
    """))

    # 3. Set NOT NULL and re-create slug-based FK
    op.alter_column('ingredients', 'subcategory', nullable=False)
    op.create_foreign_key(
        'fk_ingredients_subcategory_subcategories',
        'ingredients', 'ingredient_subcategories',
        ['subcategory'], ['slug'],
    )

    # 4. Drop subcategory_id column
    op.drop_constraint('fk_ingredients_subcategory_id', 'ingredients', type_='foreignkey')
    op.drop_index('ix_ingredients_subcategory_id', table_name='ingredients')
    op.drop_column('ingredients', 'subcategory_id')
