"""Fix spread_sandwich data-driven flow.

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-01-09 14:00:00.000000

This migration:
1. Disables 'proteins' question for spread_sandwich (not relevant for cream cheese sandwiches)

Code fixes in this release:
- menu_item_config_handler.py: Mask 'cream cheese' patterns before matching 'extra_cheese' attribute
- taking_items_handler.py: Route spread_sandwich to data-driven flow (menu_item_config)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7g8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Attribute IDs for spread_sandwich
SPREAD_SANDWICH_PROTEINS_ATTR_ID = 71


def upgrade() -> None:
    conn = op.get_bind()

    # Disable proteins question for spread_sandwich (not relevant for cream cheese sandwiches)
    conn.execute(sa.text("""
        UPDATE item_type_attributes
        SET ask_in_conversation = FALSE
        WHERE id = :attr_id
    """), {'attr_id': SPREAD_SANDWICH_PROTEINS_ATTR_ID})


def downgrade() -> None:
    conn = op.get_bind()

    # Re-enable proteins question
    conn.execute(sa.text("""
        UPDATE item_type_attributes
        SET ask_in_conversation = TRUE
        WHERE id = :attr_id
    """), {'attr_id': SPREAD_SANDWICH_PROTEINS_ATTR_ID})
