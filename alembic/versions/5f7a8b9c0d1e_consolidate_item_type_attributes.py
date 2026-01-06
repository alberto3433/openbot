"""consolidate_item_type_attributes

Phase 1 of menu configuration schema redesign.
Creates consolidated item_type_attributes table and menu item value tables.
Migrates data from item_type_field and attribute_definitions.
Keeps old tables intact for backward compatibility.

Revision ID: 5f7a8b9c0d1e
Revises: 4dbbff62106d
Create Date: 2026-01-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f7a8b9c0d1e'
down_revision: Union[str, Sequence[str], None] = '4dbbff62106d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Phase 1: Create new consolidated tables and migrate data.

    New tables:
    - item_type_attributes: Consolidates item_type_field + attribute_definitions
    - menu_item_attribute_values: Stores per-menu-item config (replaces default_config JSON)
    - menu_item_attribute_selections: Join table for multi-select values

    Also adds item_type_attribute_id FK to attribute_options for transition period.
    """

    # =========================================================================
    # 1. Create item_type_attributes table (consolidated)
    # =========================================================================
    op.create_table(
        'item_type_attributes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('item_type_id', sa.Integer(), nullable=False),

        # Identity
        sa.Column('slug', sa.String(50), nullable=False),
        sa.Column('display_name', sa.String(100), nullable=True),

        # Type and validation (from attribute_definitions)
        sa.Column('input_type', sa.String(20), nullable=False, server_default='single_select'),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allow_none', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('min_selections', sa.Integer(), nullable=True),
        sa.Column('max_selections', sa.Integer(), nullable=True),

        # Conversational flow (from item_type_field)
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ask_in_conversation', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('question_text', sa.Text(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),

        sa.ForeignKeyConstraint(['item_type_id'], ['item_types.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('item_type_id', 'slug', name='uq_item_type_attributes_type_slug')
    )
    op.create_index('idx_item_type_attributes_type', 'item_type_attributes', ['item_type_id'])

    # =========================================================================
    # 2. Create menu_item_attribute_values table
    # =========================================================================
    op.create_table(
        'menu_item_attribute_values',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('attribute_id', sa.Integer(), nullable=False),

        # For single_select: store the selected option
        sa.Column('option_id', sa.Integer(), nullable=True),

        # For boolean type
        sa.Column('value_boolean', sa.Boolean(), nullable=True),

        # For text type (rarely needed)
        sa.Column('value_text', sa.Text(), nullable=True),

        # Whether to still ask user even if there's a default value
        # TRUE = ask (e.g., "which bagel type?"), FALSE = use value as-is
        sa.Column('still_ask', sa.Boolean(), nullable=False, server_default='false'),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),

        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attribute_id'], ['item_type_attributes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['option_id'], ['attribute_options.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('menu_item_id', 'attribute_id', name='uq_menu_item_attribute_values')
    )
    op.create_index('idx_menu_item_attr_values_item', 'menu_item_attribute_values', ['menu_item_id'])
    op.create_index('idx_menu_item_attr_values_attr', 'menu_item_attribute_values', ['attribute_id'])

    # =========================================================================
    # 3. Create menu_item_attribute_selections table (join table for multi-select)
    # =========================================================================
    op.create_table(
        'menu_item_attribute_selections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.Column('attribute_id', sa.Integer(), nullable=False),
        sa.Column('option_id', sa.Integer(), nullable=False),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),

        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['attribute_id'], ['item_type_attributes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['option_id'], ['attribute_options.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('menu_item_id', 'attribute_id', 'option_id', name='uq_menu_item_attr_selection')
    )
    op.create_index('idx_menu_item_attr_sel_item', 'menu_item_attribute_selections', ['menu_item_id'])

    # =========================================================================
    # 4. Add item_type_attribute_id to attribute_options (for transition)
    # =========================================================================
    op.add_column(
        'attribute_options',
        sa.Column('item_type_attribute_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_attr_options_item_type_attr',
        'attribute_options',
        'item_type_attributes',
        ['item_type_attribute_id'],
        ['id'],
        ondelete='CASCADE'
    )

    # =========================================================================
    # 5. Migrate data from item_type_field into item_type_attributes
    # =========================================================================
    op.execute("""
        INSERT INTO item_type_attributes (
            item_type_id, slug, display_name, input_type, is_required, allow_none,
            display_order, ask_in_conversation, question_text, created_at, updated_at
        )
        SELECT
            item_type_id,
            field_name,
            INITCAP(REPLACE(field_name, '_', ' ')),
            CASE
                WHEN field_name IN ('extras', 'toppings') THEN 'multi_select'
                WHEN field_name IN ('toasted') THEN 'boolean'
                ELSE 'single_select'
            END,
            required,
            NOT required,  -- allow_none = opposite of required
            display_order,
            ask,
            question_text,
            created_at,
            updated_at
        FROM item_type_field
    """)

    # =========================================================================
    # 6. Migrate data from attribute_definitions into item_type_attributes
    #    (merge with existing if slug matches, otherwise insert)
    # =========================================================================
    # First, update existing rows that came from item_type_field with attribute_definitions data
    op.execute("""
        UPDATE item_type_attributes ita
        SET
            input_type = ad.input_type,
            is_required = ad.is_required,
            allow_none = ad.allow_none,
            min_selections = ad.min_selections,
            max_selections = ad.max_selections,
            display_name = COALESCE(ad.display_name, ita.display_name)
        FROM attribute_definitions ad
        WHERE ita.item_type_id = ad.item_type_id
          AND ita.slug = ad.slug
    """)

    # Then insert attribute_definitions that don't have a matching item_type_field
    op.execute("""
        INSERT INTO item_type_attributes (
            item_type_id, slug, display_name, input_type, is_required, allow_none,
            min_selections, max_selections, display_order, ask_in_conversation
        )
        SELECT
            ad.item_type_id,
            ad.slug,
            ad.display_name,
            ad.input_type,
            ad.is_required,
            ad.allow_none,
            ad.min_selections,
            ad.max_selections,
            ad.display_order,
            true  -- default to asking
        FROM attribute_definitions ad
        WHERE NOT EXISTS (
            SELECT 1 FROM item_type_attributes ita
            WHERE ita.item_type_id = ad.item_type_id AND ita.slug = ad.slug
        )
    """)

    # =========================================================================
    # 7. Update attribute_options to point to new item_type_attributes
    # =========================================================================
    op.execute("""
        UPDATE attribute_options ao
        SET item_type_attribute_id = ita.id
        FROM attribute_definitions ad
        JOIN item_type_attributes ita ON ita.item_type_id = ad.item_type_id AND ita.slug = ad.slug
        WHERE ao.attribute_definition_id = ad.id
    """)


def downgrade() -> None:
    """Remove new tables and FK column."""

    # Remove FK from attribute_options
    op.drop_constraint('fk_attr_options_item_type_attr', 'attribute_options', type_='foreignkey')
    op.drop_column('attribute_options', 'item_type_attribute_id')

    # Drop new tables
    op.drop_index('idx_menu_item_attr_sel_item', table_name='menu_item_attribute_selections')
    op.drop_table('menu_item_attribute_selections')

    op.drop_index('idx_menu_item_attr_values_attr', table_name='menu_item_attribute_values')
    op.drop_index('idx_menu_item_attr_values_item', table_name='menu_item_attribute_values')
    op.drop_table('menu_item_attribute_values')

    op.drop_index('idx_item_type_attributes_type', table_name='item_type_attributes')
    op.drop_table('item_type_attributes')
