"""cleanup_deprecated_tables

Revision ID: c7d8e9f0g1h3
Revises: bfb0ad41f19e
Create Date: 2026-01-10

This migration removes deprecated tables and columns that have been replaced
by the new normalized attribute system:

1. Drops attribute_definition_id column from attribute_options table
2. Drops the attribute_definitions table
3. Drops default_config column from menu_items table

These structures have been replaced by:
- item_type_attributes (for attribute definitions)
- menu_item_attribute_values / menu_item_attribute_selections (for default configs)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0g1h3'
down_revision: Union[str, Sequence[str], None] = 'bfb0ad41f19e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove deprecated tables and columns."""
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        # PostgreSQL - use IF EXISTS syntax

        # 1. Drop the FK constraint and column from attribute_options
        # First check if constraint exists
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'attribute_options_attribute_definition_id_fkey'
                    AND table_name = 'attribute_options'
                ) THEN
                    ALTER TABLE attribute_options
                    DROP CONSTRAINT attribute_options_attribute_definition_id_fkey;
                END IF;
            END $$;
        """)

        # Drop unique constraint if exists
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'uix_attr_def_option_slug'
                    AND table_name = 'attribute_options'
                ) THEN
                    ALTER TABLE attribute_options
                    DROP CONSTRAINT uix_attr_def_option_slug;
                END IF;
            END $$;
        """)

        # Drop the column if it exists
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'attribute_options'
                    AND column_name = 'attribute_definition_id'
                ) THEN
                    ALTER TABLE attribute_options DROP COLUMN attribute_definition_id;
                END IF;
            END $$;
        """)

        # 2. Drop the attribute_definitions table
        op.execute("""
            DROP TABLE IF EXISTS attribute_definitions CASCADE;
        """)

        # 3. Drop default_config column from menu_items
        op.execute("""
            DO $$ BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'menu_items'
                    AND column_name = 'default_config'
                ) THEN
                    ALTER TABLE menu_items DROP COLUMN default_config;
                END IF;
            END $$;
        """)

    else:
        # SQLite - simpler approach (no IF EXISTS)
        # Note: SQLite doesn't support DROP COLUMN easily, would need table recreation
        # For SQLite, we just drop the table since the FK is nullable
        op.execute("DROP TABLE IF EXISTS attribute_definitions")


def downgrade() -> None:
    """Re-create deprecated structures (for rollback)."""
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. Re-create attribute_definitions table
    op.create_table(
        'attribute_definitions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('item_type_id', sa.Integer(), sa.ForeignKey('item_types.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('input_type', sa.String(), nullable=False, default='single_select'),
        sa.Column('is_required', sa.Boolean(), nullable=False, default=True),
        sa.Column('allow_none', sa.Boolean(), nullable=False, default=False),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, default=0),
        sa.UniqueConstraint('item_type_id', 'slug', name='uix_item_type_attr_def_slug'),
    )

    # 2. Re-add attribute_definition_id column to attribute_options
    op.add_column('attribute_options',
        sa.Column('attribute_definition_id', sa.Integer(),
                  sa.ForeignKey('attribute_definitions.id', ondelete='CASCADE'),
                  nullable=True, index=True)
    )

    # Re-add unique constraint
    op.create_unique_constraint(
        'uix_attr_def_option_slug',
        'attribute_options',
        ['attribute_definition_id', 'slug']
    )

    # 3. Re-add default_config column to menu_items
    op.add_column('menu_items',
        sa.Column('default_config', sa.JSON(), nullable=True)
    )
