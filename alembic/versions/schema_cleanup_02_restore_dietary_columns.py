"""Restore dietary and allergen columns to menu_items.

These columns were removed in schema_cleanup_01 with the intent to compute
dietary properties from ingredients. However, some menu items (e.g., Bagel Chips)
have no ingredients defined. This migration restores the columns as a fallback.

Data flow:
- Items WITH ingredients: Dietary values computed at runtime from ingredients
- Items WITHOUT ingredients: Use stored column values as fallback

Revision ID: schema_cleanup_02
Revises: schema_cleanup_01
Create Date: 2025-02-08
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'schema_cleanup_02'
down_revision = 'schema_cleanup_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Restore dietary attribute columns
    op.add_column('menu_items', sa.Column('is_vegan', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_vegetarian', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_gluten_free', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_dairy_free', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('is_kosher', sa.Boolean(), nullable=True))

    # Restore allergen attribute columns
    op.add_column('menu_items', sa.Column('contains_eggs', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_fish', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_sesame', sa.Boolean(), nullable=True))
    op.add_column('menu_items', sa.Column('contains_nuts', sa.Boolean(), nullable=True))


def downgrade() -> None:
    # Remove dietary and allergen columns
    op.drop_column('menu_items', 'contains_nuts')
    op.drop_column('menu_items', 'contains_sesame')
    op.drop_column('menu_items', 'contains_fish')
    op.drop_column('menu_items', 'contains_eggs')
    op.drop_column('menu_items', 'is_kosher')
    op.drop_column('menu_items', 'is_dairy_free')
    op.drop_column('menu_items', 'is_gluten_free')
    op.drop_column('menu_items', 'is_vegetarian')
    op.drop_column('menu_items', 'is_vegan')
