"""add_store_id_to_orders

Revision ID: f8a9b2c3d4e5
Revises: c041faf84a65
Create Date: 2025-12-14 12:00:00.000000

"""
from typing import Sequence, Union
import random

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a9b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'c041faf84a65'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default store IDs matching the frontend admin_stores.html
DEFAULT_STORE_IDS = [
    "store_eb_001",  # East Brunswick
    "store_nb_002",  # New Brunswick
    "store_pr_003",  # Princeton
]


def upgrade() -> None:
    """Add store_id column to orders table and randomly assign existing orders."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('orders')]

    # Add the store_id column if it doesn't exist
    if 'store_id' not in columns:
        op.add_column('orders', sa.Column('store_id', sa.String(), nullable=True))
        op.create_index('ix_orders_store_id', 'orders', ['store_id'])

    # Randomly assign existing orders to stores
    # Use raw SQL for data migration
    orders_table = sa.table('orders',
        sa.column('id', sa.Integer),
        sa.column('store_id', sa.String)
    )

    # Get all orders without a store_id
    result = conn.execute(
        sa.select(orders_table.c.id).where(orders_table.c.store_id == None)
    )
    order_ids = [row[0] for row in result]

    # Randomly assign each order to a store
    for order_id in order_ids:
        store_id = random.choice(DEFAULT_STORE_IDS)
        conn.execute(
            orders_table.update()
            .where(orders_table.c.id == order_id)
            .values(store_id=store_id)
        )


def downgrade() -> None:
    """Remove store_id column from orders table."""
    op.drop_index('ix_orders_store_id', 'orders')
    op.drop_column('orders', 'store_id')
