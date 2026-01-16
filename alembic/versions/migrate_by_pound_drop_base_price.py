"""migrate_by_pound_items_drop_base_price

Revision ID: migrate_by_pound_drop_base_price
Revises: drop_modifier_category
Create Date: 2026-01-15

This migration documents and captures the following changes:

1. Cheese by the Pound, Cold Cuts by the Pound, Salad by the Pound items:
   - Renamed items to remove "(1/4 lb)" suffix
   - Changed size_category_id from 3 (Quantity) to 2 (Weight)
   - Set size prices: 1/4 lb price from original 1/4 lb item, 1 lb price from 1 lb item
   - Deleted the redundant "(1 lb)" menu items

2. Fish by the Pound items:
   - Same transformation as above

3. Schema change:
   - Dropped base_price column from menu_items table (now using menu_item_size_prices)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'migrate_by_pound_drop_base_price'
down_revision: Union[str, Sequence[str], None] = 'drop_modifier_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Size IDs
WEIGHT_CATEGORY_ID = 2
QUANTITY_CATEGORY_ID = 3
QUARTER_LB_SIZE_ID = 3
ONE_LB_SIZE_ID = 5
EACH_SIZE_ID = 6


def upgrade() -> None:
    """
    The data migration for by-the-pound items was already applied directly.
    This migration drops the deprecated base_price column.
    """
    conn = op.get_bind()
    inspector = inspect(conn)

    # Verify the data migration was successful by checking a sample item
    result = conn.execute(sa.text("""
        SELECT COUNT(*) as cnt FROM menu_items
        WHERE item_type_id IN (31, 32, 33)  -- Cheese, Cold Cuts, Fish by the Pound
        AND name LIKE '%(1/4 lb)%'
    """)).scalar()

    if result > 0:
        raise RuntimeError(
            f"Data migration incomplete: {result} items still have '(1/4 lb)' in name. "
            "Run the data migration script before applying this schema migration."
        )

    # Drop the deprecated base_price column
    existing_columns = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'base_price' in existing_columns:
        op.drop_column('menu_items', 'base_price')


def downgrade() -> None:
    """
    Restore base_price column. Note: The original by-the-pound item structure
    with separate (1/4 lb) and (1 lb) items cannot be automatically restored.
    """
    # Re-add base_price column
    op.add_column('menu_items', sa.Column('base_price', sa.Float(), nullable=True))

    # Populate base_price from the smallest size price for each item
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE menu_items m
        SET base_price = (
            SELECT MIN(p.price)
            FROM menu_item_size_prices p
            WHERE p.menu_item_id = m.id
        )
    """))
