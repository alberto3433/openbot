"""Add offer_question_text to global_attributes

Revision ID: 7592c8c48a6c
Revises: 1922a6249144
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7592c8c48a6c'
down_revision: Union[str, Sequence[str], None] = '1922a6249144'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('global_attributes',
        sa.Column('offer_question_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('global_attributes', 'offer_question_text')
