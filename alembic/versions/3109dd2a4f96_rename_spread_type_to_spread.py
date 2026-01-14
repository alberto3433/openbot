"""rename_spread_type_to_spread

Revision ID: 3109dd2a4f96
Revises: k8m9n0p1q2r3
Create Date: 2026-01-13 20:58:01.264867

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3109dd2a4f96'
down_revision: Union[str, Sequence[str], None] = 'k8m9n0p1q2r3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename spread_type to spread in item_type_attributes."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'spread_type')
        .values(slug='spread')
    )


def downgrade() -> None:
    """Rename spread back to spread_type in item_type_attributes."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'spread')
        .values(slug='spread_type')
    )
