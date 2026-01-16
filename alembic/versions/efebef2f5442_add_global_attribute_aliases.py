"""Add global_attribute_aliases table and cream cheese alias

Revision ID: efebef2f5442
Revises: cleanup_02
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'efebef2f5442'
down_revision: Union[str, Sequence[str], None] = 'cleanup_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create global_attribute_aliases table and add cream cheese alias."""
    # Create table if it doesn't exist
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables "
        "WHERE table_name = 'global_attribute_aliases')"
    ))
    table_exists = result.scalar()

    if not table_exists:
        op.create_table(
            'global_attribute_aliases',
            sa.Column('id', sa.Integer(), primary_key=True, index=True),
            sa.Column('global_attribute_id', sa.Integer(), sa.ForeignKey('global_attributes.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('alias', sa.String(100), nullable=False, unique=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        )

    # Add "cream cheese" alias for spread_type
    conn.execute(sa.text("""
        INSERT INTO global_attribute_aliases (global_attribute_id, alias)
        SELECT id, 'cream cheese'
        FROM global_attributes
        WHERE slug = 'spread_type'
        ON CONFLICT (alias) DO NOTHING
    """))


def downgrade() -> None:
    """Remove cream cheese alias and drop table."""
    conn = op.get_bind()

    # Remove the alias
    conn.execute(sa.text(
        "DELETE FROM global_attribute_aliases WHERE alias = 'cream cheese'"
    ))

    # Don't drop the table - other aliases might exist
