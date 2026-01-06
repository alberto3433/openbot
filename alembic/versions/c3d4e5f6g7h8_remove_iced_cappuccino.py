"""Remove Iced Cappuccino menu item.

Users can order an iced cappuccino by ordering a cappuccino and specifying "iced".
Having a separate menu item causes confusion and duplicate matching.

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-01-05

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete the Iced Cappuccino menu item
    op.execute("""
        DELETE FROM menu_items
        WHERE LOWER(name) = 'iced cappuccino'
    """)


def downgrade() -> None:
    # Re-create the Iced Cappuccino menu item if needed
    op.execute("""
        INSERT INTO menu_items (name, category, is_signature, base_price, available_qty)
        VALUES ('Iced Cappuccino', 'coffee', false, 5.50, 0)
    """)
