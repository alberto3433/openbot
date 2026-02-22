"""Add customer identity columns

Add last_seen_at and preferred_store_id to customers table.
Add customer_id FK to chat_sessions table.

Revision ID: d2e3f4g5h6i7
Revises: c1d2e3f4g5h6
Create Date: 2026-02-22
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d2e3f4g5h6i7"
down_revision = "c1d2e3f4g5h6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns to customers table
    op.add_column("customers", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("customers", sa.Column("preferred_store_id", sa.String(), nullable=True))

    # Add customer_id FK to chat_sessions
    op.add_column("chat_sessions", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_chat_sessions_customer_id",
        "chat_sessions",
        "customers",
        ["customer_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_sessions_customer_id", "chat_sessions", type_="foreignkey")
    op.drop_column("chat_sessions", "customer_id")
    op.drop_column("customers", "preferred_store_id")
    op.drop_column("customers", "last_seen_at")
