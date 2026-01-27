"""Add quantity_unit to ingredient_categories

Revision ID: add_quantity_unit_001
Revises: add_is_name_forming_001
Create Date: 2026-01-27

Adds quantity_unit column to ingredient_categories table.
This enables proper display of quantities like "2 pumps of Vanilla Syrup"
or "2 packets of Sugar" instead of "2 Vanilla Syrups" or "2 Sugars".

Categories with null quantity_unit use qualifiers (extra/light) instead
of numeric quantities.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_quantity_unit_001'
down_revision: Union[str, Sequence[str], None] = 'add_is_name_forming_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mapping of category slug to quantity unit
# null means qualifiers only (extra/light), not numeric quantities
QUANTITY_UNITS = {
    "syrup": "pump",
    "sweetener": "packet",
    "protein": "piece",
    # These use qualifiers (extra/light) not numeric quantities:
    # milk, spread, cheese, topping, bread, condiment -> null
}


def upgrade() -> None:
    """Add quantity_unit column and populate for syrup, sweetener, protein."""
    # Add the column (nullable, no default)
    op.add_column(
        'ingredient_categories',
        sa.Column('quantity_unit', sa.String(50), nullable=True)
    )

    # Populate quantity_unit for specific categories
    for slug, unit in QUANTITY_UNITS.items():
        op.execute(f"""
            UPDATE ingredient_categories
            SET quantity_unit = '{unit}'
            WHERE slug = '{slug}'
        """)


def downgrade() -> None:
    """Remove quantity_unit column."""
    op.drop_column('ingredient_categories', 'quantity_unit')
