"""Add foreign keys to unrecognized_item_suggestions

Replaces string columns with proper foreign keys:
- suggested_category_slug (VARCHAR) → suggested_item_type_id (FK to item_types)
- suggested_menu_items (JSON) → junction table with FK to menu_items

Revision ID: unrecognized_02
Revises: unrecognized_01
Create Date: 2026-01-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_02'
down_revision: Union[str, Sequence[str], None] = 'unrecognized_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add new FK column (nullable initially for data migration)
    op.add_column(
        'unrecognized_item_suggestions',
        sa.Column('suggested_item_type_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_unrecognized_suggestions_item_type',
        'unrecognized_item_suggestions',
        'item_types',
        ['suggested_item_type_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index(
        'ix_unrecognized_suggestions_item_type_id',
        'unrecognized_item_suggestions',
        ['suggested_item_type_id']
    )

    # Step 2: Create junction table for suggested menu items
    op.create_table(
        'unrecognized_suggestion_menu_items',
        sa.Column('suggestion_id', sa.Integer(), nullable=False),
        sa.Column('menu_item_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['suggestion_id'], ['unrecognized_item_suggestions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['menu_item_id'], ['menu_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('suggestion_id', 'menu_item_id'),
    )
    op.create_index(
        'ix_unrecognized_suggestion_menu_items_suggestion',
        'unrecognized_suggestion_menu_items',
        ['suggestion_id']
    )
    op.create_index(
        'ix_unrecognized_suggestion_menu_items_menu_item',
        'unrecognized_suggestion_menu_items',
        ['menu_item_id']
    )

    # Step 3: Migrate data - populate suggested_item_type_id from slug
    op.execute("""
        UPDATE unrecognized_item_suggestions u
        SET suggested_item_type_id = it.id
        FROM item_types it
        WHERE u.suggested_category_slug = it.slug
          AND u.suggested_category_slug IS NOT NULL
    """)

    # Step 4: Migrate data - populate junction table from JSON
    op.execute("""
        INSERT INTO unrecognized_suggestion_menu_items (suggestion_id, menu_item_id)
        SELECT DISTINCT u.id, mi.id
        FROM unrecognized_item_suggestions u,
             json_array_elements_text(u.suggested_menu_items) AS item_name
        JOIN menu_items mi ON mi.name = item_name
        WHERE u.suggested_menu_items IS NOT NULL
          AND u.suggested_menu_items::text != 'null'
          AND json_array_length(u.suggested_menu_items) > 0
    """)

    # Step 5: Drop old columns and indexes
    op.drop_index('ix_unrecognized_suggestions_category', table_name='unrecognized_item_suggestions')
    op.drop_column('unrecognized_item_suggestions', 'suggested_category_slug')
    op.drop_column('unrecognized_item_suggestions', 'suggested_menu_items')


def downgrade() -> None:
    # Re-add old columns
    op.add_column(
        'unrecognized_item_suggestions',
        sa.Column('suggested_category_slug', sa.String(50), nullable=True)
    )
    op.add_column(
        'unrecognized_item_suggestions',
        sa.Column('suggested_menu_items', sa.JSON(), nullable=True)
    )
    op.create_index(
        'ix_unrecognized_suggestions_category',
        'unrecognized_item_suggestions',
        ['suggested_category_slug']
    )

    # Migrate data back - populate slug from FK
    op.execute("""
        UPDATE unrecognized_item_suggestions u
        SET suggested_category_slug = it.slug
        FROM item_types it
        WHERE u.suggested_item_type_id = it.id
    """)

    # Migrate data back - populate JSON from junction table
    op.execute("""
        UPDATE unrecognized_item_suggestions u
        SET suggested_menu_items = (
            SELECT json_agg(mi.name)
            FROM unrecognized_suggestion_menu_items j
            JOIN menu_items mi ON j.menu_item_id = mi.id
            WHERE j.suggestion_id = u.id
        )
        WHERE EXISTS (
            SELECT 1 FROM unrecognized_suggestion_menu_items j
            WHERE j.suggestion_id = u.id
        )
    """)

    # Drop new structures
    op.drop_table('unrecognized_suggestion_menu_items')
    op.drop_index('ix_unrecognized_suggestions_item_type_id', table_name='unrecognized_item_suggestions')
    op.drop_constraint('fk_unrecognized_suggestions_item_type', 'unrecognized_item_suggestions', type_='foreignkey')
    op.drop_column('unrecognized_item_suggestions', 'suggested_item_type_id')
