"""fix_bagel_configurable

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-01-04

Sets the bagel item_type to is_configurable=True so that its attribute definitions
(spread, protein, cheese, topping, bagel_type) are loaded by _build_item_types_data.

This fixes the issue where spread prices were showing $0.00 because the bagel
item_type attributes weren't being included in the menu_index.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o9p0q1r2s3t4'
down_revision: Union[str, Sequence[str], None] = 'n8o9p0q1r2s3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Set bagel item_type to is_configurable=True."""
    op.execute("""
        UPDATE item_types
        SET is_configurable = TRUE
        WHERE slug = 'bagel'
    """)


def downgrade() -> None:
    """Revert bagel item_type to is_configurable=False."""
    op.execute("""
        UPDATE item_types
        SET is_configurable = FALSE
        WHERE slug = 'bagel'
    """)
