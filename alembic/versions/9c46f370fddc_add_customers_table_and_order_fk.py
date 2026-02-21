"""add_customers_table_and_order_fk

Revision ID: 9c46f370fddc
Revises: z5a6b7c8d9e0
Create Date: 2026-02-20 20:06:01.242788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c46f370fddc'
down_revision: Union[str, Sequence[str], None] = 'z5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create customers table and add customer_id FK to orders."""
    op.create_table('customers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customers_email'), 'customers', ['email'], unique=False)
    op.create_index(op.f('ix_customers_id'), 'customers', ['id'], unique=False)
    op.create_index(op.f('ix_customers_phone'), 'customers', ['phone'], unique=False)
    op.create_index(op.f('ix_customers_stripe_customer_id'), 'customers', ['stripe_customer_id'], unique=False)

    op.add_column('orders', sa.Column('customer_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_orders_customer_id'), 'orders', ['customer_id'], unique=False)
    op.create_foreign_key('fk_orders_customer_id', 'orders', 'customers', ['customer_id'], ['id'])


def downgrade() -> None:
    """Drop customer_id FK from orders and drop customers table."""
    op.drop_constraint('fk_orders_customer_id', 'orders', type_='foreignkey')
    op.drop_index(op.f('ix_orders_customer_id'), table_name='orders')
    op.drop_column('orders', 'customer_id')

    op.drop_index(op.f('ix_customers_stripe_customer_id'), table_name='customers')
    op.drop_index(op.f('ix_customers_phone'), table_name='customers')
    op.drop_index(op.f('ix_customers_id'), table_name='customers')
    op.drop_index(op.f('ix_customers_email'), table_name='customers')
    op.drop_table('customers')
