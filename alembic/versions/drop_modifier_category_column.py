"""drop_modifier_category_column

Revision ID: drop_modifier_category
Revises: 7368b4dd7127
Create Date: 2026-01-15 17:11:44

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'drop_modifier_category'
down_revision: Union[str, Sequence[str], None] = '7368b4dd7127'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the deprecated modifier_category column from item_types."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if column exists before dropping
    existing_columns = [col['name'] for col in inspector.get_columns('item_types')]
    if 'modifier_category' in existing_columns:
        op.drop_column('item_types', 'modifier_category')


def downgrade() -> None:
    """Re-add the modifier_category column."""
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_columns = [col['name'] for col in inspector.get_columns('item_types')]
    if 'modifier_category' not in existing_columns:
        op.add_column('item_types', sa.Column('modifier_category', sa.String(20), nullable=True))

        # Restore values from item_type_categories
        conn.execute(sa.text("""
            UPDATE item_types
            SET modifier_category = (
                SELECT slug FROM item_type_categories WHERE id = item_types.item_type_category_id
            )
            WHERE item_type_category_id IS NOT NULL
        """))
