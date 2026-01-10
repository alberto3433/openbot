"""spread_sandwich_data_driven

Revision ID: q1r2s3t4u5v7
Revises: l7m8n9o0p1q2
Create Date: 2026-01-09 12:00:00.000000

This migration:
1. Removes 'spread' attribute from spread_sandwich (redundant - spread is in menu item name)
2. Makes 'toasted' attribute required for spread_sandwich
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q1r2s3t4u5v7'
down_revision: Union[str, Sequence[str], None] = 'l7m8n9o0p1q2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# IDs
SPREAD_SANDWICH_TYPE_ID = 13
SPREAD_ATTR_ID = 43
TOASTED_ATTR_ID = 20


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Delete ingredient links for 'spread' attribute
    conn.execute(sa.text("""
        DELETE FROM item_type_ingredients
        WHERE item_type_id = :type_id
        AND ingredient_group = 'spread'
    """), {'type_id': SPREAD_SANDWICH_TYPE_ID})

    # 2. Delete 'spread' attribute from spread_sandwich
    conn.execute(sa.text("""
        DELETE FROM item_type_attributes
        WHERE id = :attr_id
    """), {'attr_id': SPREAD_ATTR_ID})

    # 3. Make 'toasted' attribute required
    conn.execute(sa.text("""
        UPDATE item_type_attributes
        SET is_required = TRUE
        WHERE id = :attr_id
    """), {'attr_id': TOASTED_ATTR_ID})


def downgrade() -> None:
    conn = op.get_bind()

    # Make 'toasted' optional again
    conn.execute(sa.text("""
        UPDATE item_type_attributes
        SET is_required = FALSE
        WHERE id = :attr_id
    """), {'attr_id': TOASTED_ATTR_ID})

    # Note: Recreating the spread attribute and its ingredient links
    # would require more complex logic - this is a partial downgrade
