"""Convert stores.hours from Text to JSONB

Revision ID: z7c8d9e0f1g2
Revises: z6b7c8d9e0f1
Create Date: 2026-02-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "z7c8d9e0f1g2"
down_revision = "bbfaef8ac08d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Null out existing text values before type change
    op.execute("UPDATE stores SET hours = NULL WHERE hours IS NOT NULL")
    # Change column type from Text to JSONB
    op.alter_column(
        "stores",
        "hours",
        existing_type=sa.Text(),
        type_=JSONB,
        existing_nullable=True,
        postgresql_using="hours::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "stores",
        "hours",
        existing_type=JSONB,
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="hours::text",
    )
