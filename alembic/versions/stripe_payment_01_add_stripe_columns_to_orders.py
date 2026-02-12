"""add stripe payment columns to orders

Revision ID: stripe_payment_01
Revises: dietary_flags_01
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'stripe_payment_01'
down_revision: Union[str, Sequence[str], None] = 'dietary_flags_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Stripe payment tracking columns to orders table."""
    op.add_column('orders', sa.Column('stripe_checkout_session_id', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('stripe_payment_intent_id', sa.String(), nullable=True))
    op.add_column('orders', sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_orders_stripe_checkout_session_id', 'orders', ['stripe_checkout_session_id'])


def downgrade() -> None:
    """Remove Stripe payment tracking columns from orders table."""
    op.drop_index('ix_orders_stripe_checkout_session_id', table_name='orders')
    op.drop_column('orders', 'paid_at')
    op.drop_column('orders', 'stripe_payment_intent_id')
    op.drop_column('orders', 'stripe_checkout_session_id')
