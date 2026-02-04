"""Add question_text_followup column to item_type_global_attributes.

For multi-select attributes, allows different question text when the item
already has selections (e.g., "Any other cheese?" instead of "Any cheese?").

Revision ID: followup_01
Revises: attr_inq_01
Create Date: 2026-02-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "followup_01"
down_revision: Union[str, Sequence[str], None] = "attr_inq_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add question_text_followup column."""
    op.add_column(
        "item_type_global_attributes",
        sa.Column("question_text_followup", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove question_text_followup column."""
    op.drop_column("item_type_global_attributes", "question_text_followup")
