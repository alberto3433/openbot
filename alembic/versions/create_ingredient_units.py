"""Create ingredient_units table and migrate ingredient.unit

Revision ID: create_ingredient_units
Revises: drop_extra_metadata_column
Create Date: 2026-01-23

This migration:
1. Creates the ingredient_units table with canonical unit values
2. Adds unit_id FK to ingredients table
3. Migrates existing unit string values to FK references (with consolidation)
4. Drops the old unit string column

Unit consolidation:
- 'serving' consolidates: each, piece, unit, portion, serving
- 'ounce' consolidates: oz
- packet, pump, shot, slice: unchanged
- NULL defaults to 'serving'
"""
from alembic import op
import sqlalchemy as sa


revision = 'create_ingredient_units'
down_revision = 'drop_extra_metadata_column'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create ingredient_units table
    op.create_table(
        'ingredient_units',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(50), unique=True, nullable=False),
    )
    op.create_index('ix_ingredient_units_id', 'ingredient_units', ['id'])

    # 2. Populate with canonical units
    op.execute("""
        INSERT INTO ingredient_units (name) VALUES
        ('serving'), ('ounce'), ('packet'), ('pump'), ('shot'), ('slice')
    """)

    # 3. Add unit_id column (nullable initially)
    op.add_column('ingredients', sa.Column('unit_id', sa.Integer(), nullable=True))

    # 4. Populate unit_id based on existing unit values (with consolidation)
    op.execute("""
        UPDATE ingredients SET unit_id = (
            SELECT id FROM ingredient_units WHERE name = CASE
                WHEN ingredients.unit IN ('each', 'piece', 'unit', 'portion', 'serving') THEN 'serving'
                WHEN ingredients.unit = 'oz' THEN 'ounce'
                ELSE ingredients.unit
            END
        )
    """)

    # 5. Handle NULLs - default to 'serving'
    op.execute("""
        UPDATE ingredients SET unit_id = (SELECT id FROM ingredient_units WHERE name = 'serving')
        WHERE unit_id IS NULL
    """)

    # 6. Make unit_id NOT NULL and add FK constraint
    op.alter_column('ingredients', 'unit_id', nullable=False)
    op.create_foreign_key('fk_ingredients_unit_id', 'ingredients', 'ingredient_units', ['unit_id'], ['id'])

    # 7. Drop old unit column
    op.drop_column('ingredients', 'unit')


def downgrade():
    # 1. Add back unit string column
    op.add_column('ingredients', sa.Column('unit', sa.String(), nullable=True))

    # 2. Populate from relationship
    op.execute("""
        UPDATE ingredients SET unit = (
            SELECT name FROM ingredient_units WHERE id = ingredients.unit_id
        )
    """)

    # 3. Make NOT NULL
    op.alter_column('ingredients', 'unit', nullable=False)

    # 4. Drop FK and unit_id column
    op.drop_constraint('fk_ingredients_unit_id', 'ingredients', type_='foreignkey')
    op.drop_column('ingredients', 'unit_id')

    # 5. Drop ingredient_units table
    op.drop_index('ix_ingredient_units_id', 'ingredient_units')
    op.drop_table('ingredient_units')
