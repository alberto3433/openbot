"""add toast POS integration

Revision ID: toast_01
Revises: notifications_01
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "toast_01"
down_revision: Union[str, Sequence[str], None] = "notifications_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create toast_guid_map table (if_not_exists handles pre-existing table)
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT to_regclass('public.toast_guid_map')"))
    table_exists = result.scalar() is not None

    if not table_exists:
        op.create_table(
            "toast_guid_map",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("local_id", sa.Integer(), nullable=False),
            sa.Column("toast_guid", sa.String(), nullable=False),
            sa.Column("toast_name", sa.String(), nullable=True),
            sa.Column("store_id", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("entity_type", "local_id", "store_id", name="uq_toast_guid_map"),
        )
        op.create_index(op.f("ix_toast_guid_map_id"), "toast_guid_map", ["id"])
        op.create_index(op.f("ix_toast_guid_map_entity_type"), "toast_guid_map", ["entity_type"])
        op.create_index(op.f("ix_toast_guid_map_store_id"), "toast_guid_map", ["store_id"])

    # Add Toast columns to orders table
    op.add_column("orders", sa.Column("toast_order_guid", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("toast_order_status", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("toast_submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_orders_toast_order_guid"), "orders", ["toast_order_guid"])


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_toast_order_guid"), table_name="orders")
    op.drop_column("orders", "toast_submitted_at")
    op.drop_column("orders", "toast_order_status")
    op.drop_column("orders", "toast_order_guid")

    op.drop_index(op.f("ix_toast_guid_map_store_id"), table_name="toast_guid_map")
    op.drop_index(op.f("ix_toast_guid_map_entity_type"), table_name="toast_guid_map")
    op.drop_index(op.f("ix_toast_guid_map_id"), table_name="toast_guid_map")
    op.drop_table("toast_guid_map")
