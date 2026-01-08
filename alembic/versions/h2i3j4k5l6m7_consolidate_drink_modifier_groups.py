"""Consolidate drink modifier groups and add ingredient slug

Revision ID: h2i3j4k5l6m7
Revises: 96e172af6a59
Create Date: 2026-01-08 13:00:00.000000

This migration:
1. Adds slug column to ingredients table (source of truth for identifier)
2. Consolidates milk/sweetener/syrup groups into 'drink_modifier' group
3. Sets loads_from_ingredients=True on drink_modifier attributes
4. Removes redundant attribute_options rows for drink_modifier

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h2i3j4k5l6m7'
down_revision: Union[str, Sequence[str], None] = '96e172af6a59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # Step 1: Add slug column to ingredients table (if not exists)
    # Check if column already exists (idempotent)
    result = conn.execute(sa.text("PRAGMA table_info(ingredients)"))
    columns = [row[1] for row in result]
    if 'slug' not in columns:
        op.add_column('ingredients', sa.Column('slug', sa.String(100), nullable=True))

    # Step 2: Populate slug from name (lowercase, spaces to underscores)
    conn.execute(sa.text("""
        UPDATE ingredients
        SET slug = LOWER(REPLACE(REPLACE(REPLACE(name, ' ', '_'), '''', ''), '-', '_'))
    """))

    # Make slug not nullable and unique after population
    # Use batch_alter_table for SQLite compatibility
    # Check if index exists first
    result = conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_ingredients_slug'"))
    index_exists = result.fetchone() is not None

    if not index_exists:
        with op.batch_alter_table('ingredients') as batch_op:
            batch_op.alter_column('slug', nullable=False)
            batch_op.create_unique_constraint('uq_ingredients_slug', ['slug'])
            batch_op.create_index('ix_ingredients_slug', ['slug'])

    # Step 3: Get item type IDs for espresso and sized_beverage
    result = conn.execute(sa.text("""
        SELECT id, slug FROM item_types
        WHERE slug IN ('espresso', 'sized_beverage')
    """))
    item_type_map = {row[1]: row[0] for row in result}

    espresso_id = item_type_map.get('espresso')
    sized_beverage_id = item_type_map.get('sized_beverage')

    # Step 4: Consolidate ingredient groups from milk/sweetener/syrup to drink_modifier
    if espresso_id:
        conn.execute(sa.text("""
            UPDATE item_type_ingredients
            SET ingredient_group = 'drink_modifier'
            WHERE item_type_id = :item_type_id
            AND ingredient_group IN ('milk', 'sweetener', 'syrup')
        """), {'item_type_id': espresso_id})

    if sized_beverage_id:
        conn.execute(sa.text("""
            UPDATE item_type_ingredients
            SET ingredient_group = 'drink_modifier'
            WHERE item_type_id = :item_type_id
            AND ingredient_group IN ('milk', 'sweetener', 'syrup')
        """), {'item_type_id': sized_beverage_id})

    # Step 5: Update ItemTypeAttribute to use loads_from_ingredients
    if espresso_id:
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = TRUE,
                ingredient_group = 'drink_modifier'
            WHERE item_type_id = :item_type_id
            AND slug = 'drink_modifier'
        """), {'item_type_id': espresso_id})

    if sized_beverage_id:
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = TRUE,
                ingredient_group = 'drink_modifier'
            WHERE item_type_id = :item_type_id
            AND slug = 'drink_modifier'
        """), {'item_type_id': sized_beverage_id})

    # Step 6: Get drink_modifier attribute IDs
    attr_ids = []
    if espresso_id:
        result = conn.execute(sa.text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'drink_modifier'
        """), {'item_type_id': espresso_id})
        row = result.fetchone()
        if row:
            attr_ids.append(row[0])

    if sized_beverage_id:
        result = conn.execute(sa.text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'drink_modifier'
        """), {'item_type_id': sized_beverage_id})
        row = result.fetchone()
        if row:
            attr_ids.append(row[0])

    # Step 7: Delete redundant attribute_options for drink_modifier
    # (now that options come from item_type_ingredients via loads_from_ingredients)
    if attr_ids:
        for attr_id in attr_ids:
            conn.execute(sa.text("""
                DELETE FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
            """), {'attr_id': attr_id})


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # Get item type IDs
    result = conn.execute(sa.text("""
        SELECT id, slug FROM item_types
        WHERE slug IN ('espresso', 'sized_beverage')
    """))
    item_type_map = {row[1]: row[0] for row in result}

    espresso_id = item_type_map.get('espresso')
    sized_beverage_id = item_type_map.get('sized_beverage')

    # Revert ItemTypeAttribute settings
    if espresso_id:
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = FALSE,
                ingredient_group = NULL
            WHERE item_type_id = :item_type_id
            AND slug = 'drink_modifier'
        """), {'item_type_id': espresso_id})

    if sized_beverage_id:
        conn.execute(sa.text("""
            UPDATE item_type_attributes
            SET loads_from_ingredients = FALSE,
                ingredient_group = NULL
            WHERE item_type_id = :item_type_id
            AND slug = 'drink_modifier'
        """), {'item_type_id': sized_beverage_id})

    # Note: Cannot automatically restore deleted attribute_options or
    # split drink_modifier back to milk/sweetener/syrup without original data

    # Remove slug column from ingredients using batch_alter_table for SQLite
    with op.batch_alter_table('ingredients') as batch_op:
        batch_op.drop_index('ix_ingredients_slug')
        batch_op.drop_constraint('uq_ingredients_slug', type_='unique')
        batch_op.drop_column('slug')
