"""add preparation_option_id to menu_item_ingredients

Revision ID: be2d3239236a
Revises: fix_plain_cc_mm
Create Date: 2026-02-01 11:44:00.057821

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be2d3239236a'
down_revision: Union[str, Sequence[str], None] = 'fix_plain_cc_mm'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add preparation_option_id column to menu_item_ingredients
    # This allows specifying how an ingredient is prepared (e.g., "fried" for eggs)
    op.add_column(
        'menu_item_ingredients',
        sa.Column('preparation_option_id', sa.Integer(), nullable=True)
    )
    op.create_index(
        op.f('ix_menu_item_ingredients_preparation_option_id'),
        'menu_item_ingredients',
        ['preparation_option_id'],
        unique=False
    )
    op.create_foreign_key(
        'fk_menu_item_ingredients_preparation_option',
        'menu_item_ingredients',
        'global_attribute_options',
        ['preparation_option_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_menu_item_ingredients_preparation_option',
        'menu_item_ingredients',
        type_='foreignkey'
    )
    op.drop_index(
        op.f('ix_menu_item_ingredients_preparation_option_id'),
        table_name='menu_item_ingredients'
    )
    op.drop_column('menu_item_ingredients', 'preparation_option_id')
