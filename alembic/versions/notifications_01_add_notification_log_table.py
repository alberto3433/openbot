"""add notification_log table

Revision ID: notifications_01
Revises: fulfillment_01
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'notifications_01'
down_revision: Union[str, Sequence[str], None] = 'fulfillment_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create notification_log table."""
    conn = op.get_bind()
    table_exists = conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'notification_log')")
    ).scalar()
    if not table_exists:
        op.create_table(
            'notification_log',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('order_id', sa.Integer(), sa.ForeignKey('orders.id'), nullable=True, index=True),
            sa.Column('notification_type', sa.String(), nullable=False),
            sa.Column('event', sa.String(), nullable=False),
            sa.Column('recipient', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='sent'),
            sa.Column('provider_message_id', sa.String(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    """Drop notification_log table."""
    op.drop_table('notification_log')
