"""Add Square POS integration columns

Revision ID: z5a6b7c8d9e0
Revises: z4b5c6d7e8f9
Create Date: 2026-02-20

Adds Square POS columns to orders and stores tables for the Square
Orders API integration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "z5a6b7c8d9e0"
down_revision = "z4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Square POS columns on orders
    op.add_column("orders", sa.Column("square_order_id", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("square_order_status", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("square_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_orders_square_order_id", "orders", ["square_order_id"])

    # Square location ID on stores
    op.add_column("stores", sa.Column("square_location_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "square_location_id")
    op.drop_index("ix_orders_square_order_id", table_name="orders")
    op.drop_column("orders", "square_submitted_at")
    op.drop_column("orders", "square_order_status")
    op.drop_column("orders", "square_order_id")
