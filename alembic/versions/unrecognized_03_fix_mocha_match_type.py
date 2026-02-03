"""Fix mocha match_type from exact to contains

Allows "iced mocha", "mocha latte", etc. to match the mocha curated suggestion.

Revision ID: unrecognized_03
Revises: earl_grey_01
Create Date: 2026-02-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'unrecognized_03'
down_revision: Union[str, Sequence[str], None] = 'earl_grey_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE unrecognized_item_suggestions
        SET match_type = 'contains'
        WHERE input_pattern = 'mocha'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE unrecognized_item_suggestions
        SET match_type = 'exact'
        WHERE input_pattern = 'mocha'
    """)
