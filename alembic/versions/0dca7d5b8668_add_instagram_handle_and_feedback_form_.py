"""Add instagram_handle and feedback_form_url to company

Revision ID: 0dca7d5b8668
Revises: 3374fb4828b2
Create Date: 2026-01-07 12:51:38.460003

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0dca7d5b8668'
down_revision: Union[str, Sequence[str], None] = '3374fb4828b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add instagram_handle and feedback_form_url columns to company table."""
    op.add_column('company', sa.Column('instagram_handle', sa.String(), nullable=True))
    op.add_column('company', sa.Column('feedback_form_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove instagram_handle and feedback_form_url columns from company table."""
    op.drop_column('company', 'feedback_form_url')
    op.drop_column('company', 'instagram_handle')
