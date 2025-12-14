"""add_store_id_to_session_analytics

Revision ID: g9b0c3d4e5f6
Revises: f8a9b2c3d4e5
Create Date: 2025-12-14 12:30:00.000000

"""
from typing import Sequence, Union
import random

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g9b0c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f8a9b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default store IDs matching the frontend admin_stores.html
DEFAULT_STORE_IDS = [
    "store_eb_001",  # East Brunswick
    "store_nb_002",  # New Brunswick
    "store_pr_003",  # Princeton
]


def upgrade() -> None:
    """Add store_id column to session_analytics table and randomly assign existing records."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('session_analytics')]

    # Add the store_id column if it doesn't exist
    if 'store_id' not in columns:
        op.add_column('session_analytics', sa.Column('store_id', sa.String(), nullable=True))
        op.create_index('ix_session_analytics_store_id', 'session_analytics', ['store_id'])

    # Randomly assign existing sessions to stores
    session_table = sa.table('session_analytics',
        sa.column('id', sa.Integer),
        sa.column('store_id', sa.String)
    )

    # Get all sessions without a store_id
    result = conn.execute(
        sa.select(session_table.c.id).where(session_table.c.store_id == None)
    )
    session_ids = [row[0] for row in result]

    # Randomly assign each session to a store
    for session_id in session_ids:
        store_id = random.choice(DEFAULT_STORE_IDS)
        conn.execute(
            session_table.update()
            .where(session_table.c.id == session_id)
            .values(store_id=store_id)
        )


def downgrade() -> None:
    """Remove store_id column from session_analytics table."""
    op.drop_index('ix_session_analytics_store_id', 'session_analytics')
    op.drop_column('session_analytics', 'store_id')
