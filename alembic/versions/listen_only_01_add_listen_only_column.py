"""Add listen_only column to item_type_global_attributes

Revision ID: listen_only_01
Revises: fix_egg_display
Create Date: 2026-02-02

Adds a `listen_only` boolean column that when True means:
- Attribute is NOT asked as a dedicated question
- Attribute is NOT included in the catchall ("Anything else?")
- Attribute IS still recognized if customer mentions it

Sets listen_only=True for: style, decaf
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'listen_only_01'
down_revision: Union[str, Sequence[str], None] = 'fix_egg_display'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Global attributes that should be listen_only
LISTEN_ONLY_ATTRS = ['style', 'decaf']


def upgrade() -> None:
    """Add listen_only column and set defaults."""
    # Add the column with default False
    op.add_column(
        'item_type_global_attributes',
        sa.Column('listen_only', sa.Boolean(), nullable=False, server_default='false')
    )

    # Set listen_only=True for style and decaf attributes
    conn = op.get_bind()
    for attr_slug in LISTEN_ONLY_ATTRS:
        result = conn.execute(sa.text("""
            UPDATE item_type_global_attributes
            SET listen_only = TRUE
            FROM global_attributes
            WHERE item_type_global_attributes.global_attribute_id = global_attributes.id
              AND global_attributes.slug = :slug
        """), {'slug': attr_slug})
        print(f"Set listen_only=True for '{attr_slug}' attribute: {result.rowcount} rows updated")


def downgrade() -> None:
    """Remove listen_only column."""
    op.drop_column('item_type_global_attributes', 'listen_only')
