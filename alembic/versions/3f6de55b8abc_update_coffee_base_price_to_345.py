"""update_coffee_base_price_to_345

Revision ID: 3f6de55b8abc
Revises: 2b9737e29757
Create Date: 2026-01-01 18:13:55.440235

Updates the base price for coffee to $3.45.
With the size upcharge system:
- Small coffee: $3.45 (base price)
- Large coffee: $4.35 (base $3.45 + $0.90 size upcharge)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '3f6de55b8abc'
down_revision: Union[str, Sequence[str], None] = '2b9737e29757'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Old price (for downgrade)
OLD_COFFEE_PRICE = 3.25
# New price
NEW_COFFEE_PRICE = 3.45


def upgrade() -> None:
    """Update coffee base price to $3.45."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Update menu items that are coffee (by name or item_type)
    # This handles items named "Coffee" or similar
    session.execute(
        sa.text("""
            UPDATE menu_items
            SET base_price = :new_price
            WHERE LOWER(name) = 'coffee'
        """),
        {"new_price": NEW_COFFEE_PRICE}
    )

    session.commit()


def downgrade() -> None:
    """Revert coffee base price to original."""
    bind = op.get_bind()
    session = Session(bind=bind)

    session.execute(
        sa.text("""
            UPDATE menu_items
            SET base_price = :old_price
            WHERE LOWER(name) = 'coffee'
        """),
        {"old_price": OLD_COFFEE_PRICE}
    )

    session.commit()
