"""rename_shots_to_extra_shots

Revision ID: 8b0eaf295c0d
Revises: 3109dd2a4f96
Create Date: 2026-01-13 21:08:26.966328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b0eaf295c0d'
down_revision: Union[str, Sequence[str], None] = '3109dd2a4f96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename shots to extra_shots in item_type_attributes."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'shots')
        .values(slug='extra_shots')
    )


def downgrade() -> None:
    """Rename extra_shots back to shots in item_type_attributes."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'extra_shots')
        .values(slug='shots')
    )
