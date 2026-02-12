"""add fulfillment columns and order_status_history table

Revision ID: fulfillment_01
Revises: stripe_payment_01
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fulfillment_01'
down_revision: Union[str, Sequence[str], None] = 'stripe_payment_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add fulfillment tracking columns and order_status_history table."""
    # New columns on orders
    op.add_column('orders', sa.Column('estimated_ready_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('ready_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('orders', sa.Column('cancellation_reason', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('staff_notes', sa.Text(), nullable=True))
    op.add_column('orders', sa.Column('updated_at', sa.DateTime(timezone=True),
                                       server_default=sa.func.now(), nullable=True))

    # New table: order_status_history (may already exist from prior manual creation)
    conn = op.get_bind()
    table_exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'order_status_history')")
    ).scalar()
    if not table_exists:
        op.create_table(
            'order_status_history',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=False, index=True),
            sa.Column('from_status', sa.String(), nullable=True),
            sa.Column('to_status', sa.String(), nullable=False),
            sa.Column('changed_by', sa.String(), nullable=True),
            sa.Column('note', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    """Remove fulfillment columns and order_status_history table."""
    op.drop_table('order_status_history')
    op.drop_column('orders', 'updated_at')
    op.drop_column('orders', 'staff_notes')
    op.drop_column('orders', 'cancellation_reason')
    op.drop_column('orders', 'cancelled_at')
    op.drop_column('orders', 'completed_at')
    op.drop_column('orders', 'ready_at')
    op.drop_column('orders', 'estimated_ready_at')
