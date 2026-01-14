"""rename_bagel_type_to_bread

Revision ID: 148706983bdb
Revises: 2f53229e3dbe
Create Date: 2026-01-13 21:38:02.257891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '148706983bdb'
down_revision: Union[str, Sequence[str], None] = '2f53229e3dbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename bagel_type to bread in item_type_attributes for consistency."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'bagel_type')
        .values(slug='bread')
    )


def downgrade() -> None:
    """Rename bread back to bagel_type in item_type_attributes."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'bread')
        .values(slug='bagel_type')
    )
