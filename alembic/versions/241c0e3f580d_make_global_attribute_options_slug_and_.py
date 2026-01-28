"""Make global_attribute_options slug and display_name nullable for ingredient-linked options

Revision ID: 241c0e3f580d
Revises: restrict_shared_fks_001
Create Date: 2026-01-28 14:01:19.176110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '241c0e3f580d'
down_revision: Union[str, Sequence[str], None] = 'restrict_shared_fks_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make slug/display_name nullable and NULL out ingredient-linked rows."""
    # 1. Make columns nullable
    op.alter_column('global_attribute_options', 'slug',
               existing_type=sa.VARCHAR(length=100),
               nullable=True)
    op.alter_column('global_attribute_options', 'display_name',
               existing_type=sa.VARCHAR(length=100),
               nullable=True)

    # 2. NULL out slug/display_name for ingredient-linked options (data migration)
    op.execute("""
        UPDATE global_attribute_options
        SET slug = NULL, display_name = NULL
        WHERE ingredient_id IS NOT NULL
    """)


def downgrade() -> None:
    """Restore slug/display_name from linked ingredients, then make NOT NULL."""
    # 1. Populate slug/display_name from linked ingredients before making NOT NULL
    op.execute("""
        UPDATE global_attribute_options gao
        SET slug = i.slug, display_name = i.name
        FROM ingredients i
        WHERE gao.ingredient_id = i.id
          AND gao.slug IS NULL
    """)

    # 2. Make columns NOT NULL again
    op.alter_column('global_attribute_options', 'display_name',
               existing_type=sa.VARCHAR(length=100),
               nullable=False)
    op.alter_column('global_attribute_options', 'slug',
               existing_type=sa.VARCHAR(length=100),
               nullable=False)
