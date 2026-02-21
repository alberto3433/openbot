"""Add payment_provider to company table

Revision ID: z6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-02-20

Adds a payment_provider column to the company table to toggle between
Stripe and Square for online payment processing.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "z6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company",
        sa.Column("payment_provider", sa.String(), nullable=False, server_default="stripe"),
    )


def downgrade() -> None:
    op.drop_column("company", "payment_provider")
