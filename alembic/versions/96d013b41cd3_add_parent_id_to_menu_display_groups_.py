"""Add parent_id to menu_display_groups for hierarchy

Revision ID: 96d013b41cd3
Revises: fk_ingr_cat_001
Create Date: 2026-02-15 15:19:20.092361

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96d013b41cd3'
down_revision: Union[str, Sequence[str], None] = 'fk_ingr_cat_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add parent_id column for display group hierarchy."""
    op.add_column('menu_display_groups', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_menu_display_groups_parent_id'), 'menu_display_groups', ['parent_id'], unique=False)
    op.create_foreign_key(
        'fk_menu_display_groups_parent_id',
        'menu_display_groups', 'menu_display_groups',
        ['parent_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Remove parent_id column."""
    op.drop_constraint('fk_menu_display_groups_parent_id', 'menu_display_groups', type_='foreignkey')
    op.drop_index(op.f('ix_menu_display_groups_parent_id'), table_name='menu_display_groups')
    op.drop_column('menu_display_groups', 'parent_id')
