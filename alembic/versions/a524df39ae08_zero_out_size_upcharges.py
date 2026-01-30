"""Zero out size upcharges on global attribute options

Since MenuItemSizePrice handles per-item size pricing, the price_modifier
values on global attribute "size" options are unused. This migration sets
them to 0 to eliminate confusion.

Revision ID: a524df39ae08
Revises: fix_lox_cc_mm_01
Create Date: 2026-01-30 13:29:53.456970

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a524df39ae08'
down_revision: Union[str, Sequence[str], None] = 'fix_lox_cc_mm_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set all size upcharges to 0 since MenuItemSizePrice handles pricing."""
    op.execute("""
        UPDATE global_attribute_options
        SET price_modifier = 0
        WHERE global_attribute_id = (SELECT id FROM global_attributes WHERE slug = 'size')
    """)


def downgrade() -> None:
    """No downgrade needed - these values were unused anyway."""
    pass
