"""Add property_name column to global_attributes

This column stores the Python property name for attributes where it differs
from the slug (e.g., slug="milk_sweetener_syrup" but property_name="milk").

Revision ID: add_property_name_to_global_attrs
Revises: add_lox_nova_aliases
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_gattr_property_name'
down_revision: Union[str, Sequence[str], None] = 'add_lox_nova_aliases'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add property_name column and set initial values."""
    # Add the column
    op.add_column(
        'global_attributes',
        sa.Column('property_name', sa.String(50), nullable=True)
    )

    # Set property_name for milk_sweetener_syrup -> "milk"
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE global_attributes
        SET property_name = 'milk'
        WHERE slug = 'milk_sweetener_syrup'
    """))


def downgrade() -> None:
    """Remove property_name column."""
    op.drop_column('global_attributes', 'property_name')
