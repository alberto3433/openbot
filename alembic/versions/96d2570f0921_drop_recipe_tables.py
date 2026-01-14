"""drop_recipe_tables

Revision ID: 96d2570f0921
Revises: a2c4c83b1a12
Create Date: 2026-01-13 21:58:30.132398

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96d2570f0921'
down_revision: Union[str, Sequence[str], None] = 'a2c4c83b1a12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop unused Recipe tables and menu_items.recipe_id column."""
    # Drop foreign key constraint from menu_items first (if exists)
    # The constraint might not exist or have a different name depending on the DB state
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # Check if recipe_id column exists before trying to drop it
    columns = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'recipe_id' in columns:
        # Get actual foreign key constraint names
        fks = inspector.get_foreign_keys('menu_items')
        recipe_fk_name = None
        for fk in fks:
            if 'recipe_id' in fk.get('constrained_columns', []):
                recipe_fk_name = fk.get('name')
                break

        with op.batch_alter_table('menu_items') as batch_op:
            if recipe_fk_name:
                batch_op.drop_constraint(recipe_fk_name, type_='foreignkey')
            batch_op.drop_column('recipe_id')

    # Drop child tables first (foreign key dependencies) - use IF EXISTS pattern
    tables_to_drop = ['recipe_choice_items', 'recipe_choice_groups', 'recipe_ingredients', 'recipes']
    existing_tables = inspector.get_table_names()
    for table in tables_to_drop:
        if table in existing_tables:
            op.drop_table(table)


def downgrade() -> None:
    """Recreate Recipe tables (not recommended - these were unused)."""
    # Recreate recipes table
    op.create_table(
        'recipes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Recreate recipe_ingredients table
    op.create_table(
        'recipe_ingredients',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Float(), nullable=True),
        sa.Column('unit_override', sa.String(length=20), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Recreate recipe_choice_groups table
    op.create_table(
        'recipe_choice_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipe_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('min_choices', sa.Integer(), nullable=True),
        sa.Column('max_choices', sa.Integer(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['recipe_id'], ['recipes.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Recreate recipe_choice_items table
    op.create_table(
        'recipe_choice_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('choice_group_id', sa.Integer(), nullable=False),
        sa.Column('ingredient_id', sa.Integer(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('extra_price', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.ForeignKeyConstraint(['choice_group_id'], ['recipe_choice_groups.id']),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Add recipe_id column back to menu_items
    with op.batch_alter_table('menu_items') as batch_op:
        batch_op.add_column(sa.Column('recipe_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_menu_items_recipe_id',
            'recipes',
            ['recipe_id'],
            ['id']
        )
