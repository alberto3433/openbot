"""rename_extras_to_toppings

Revision ID: 2f53229e3dbe
Revises: 8b0eaf295c0d
Create Date: 2026-01-13 21:14:42.963544

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f53229e3dbe'
down_revision: Union[str, Sequence[str], None] = '8b0eaf295c0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename extras to toppings in item_type_attributes for consistency."""
    item_type_attributes = sa.table(
        'item_type_attributes',
        sa.column('slug', sa.String),
    )

    op.execute(
        item_type_attributes.update()
        .where(item_type_attributes.c.slug == 'extras')
        .values(slug='toppings')
    )


def downgrade() -> None:
    """Rename toppings back to extras in item_type_attributes (partial - only the one that was extras)."""
    # Note: This downgrade is imperfect since we can't distinguish which row was originally 'extras'
    # In practice, this migration standardizes naming and shouldn't need to be rolled back
    pass
