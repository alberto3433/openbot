"""Move Plain Cream Cheese Sandwich to spread_sandwich item type

Revision ID: plain_cc_01
Revises: unrecognized_03
Create Date: 2026-02-04

Fixes issue where "plain please" matches cheese_sandwich because "Plain Cream
Cheese Sandwich" is incorrectly in the cheese_sandwich item type. All other
cream cheese sandwiches are in spread_sandwich, so this moves it to be consistent.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'plain_cc_01'
down_revision: Union[str, Sequence[str], None] = 'unrecognized_03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Move Plain Cream Cheese Sandwich to spread_sandwich item type."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get spread_sandwich item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'spread_sandwich'")
    ).fetchone()
    if not result:
        print("WARNING: 'spread_sandwich' item type not found, skipping")
        return
    spread_sandwich_id = result[0]

    # Update the menu item
    result = session.execute(
        sa.text("""
            UPDATE menu_items
            SET item_type_id = :spread_sandwich_id
            WHERE name = 'Plain Cream Cheese Sandwich'
            RETURNING id, item_type_id
        """),
        {"spread_sandwich_id": spread_sandwich_id}
    ).fetchone()

    if result:
        print(f"Moved 'Plain Cream Cheese Sandwich' (id={result[0]}) to spread_sandwich (type_id={result[1]})")
    else:
        print("WARNING: 'Plain Cream Cheese Sandwich' not found in menu_items")

    session.commit()


def downgrade() -> None:
    """Move Plain Cream Cheese Sandwich back to cheese_sandwich item type."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get cheese_sandwich item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'cheese_sandwich'")
    ).fetchone()
    if not result:
        print("WARNING: 'cheese_sandwich' item type not found, skipping")
        return
    cheese_sandwich_id = result[0]

    # Update the menu item
    session.execute(
        sa.text("""
            UPDATE menu_items
            SET item_type_id = :cheese_sandwich_id
            WHERE name = 'Plain Cream Cheese Sandwich'
        """),
        {"cheese_sandwich_id": cheese_sandwich_id}
    )

    session.commit()
    print("Moved 'Plain Cream Cheese Sandwich' back to cheese_sandwich")
