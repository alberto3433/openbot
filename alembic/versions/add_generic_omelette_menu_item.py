"""Add generic Omelette menu item

Revision ID: add_generic_omelette
Revises: listen_only_01
Create Date: 2026-02-03

Adds a generic "Omelette" menu item that catches requests like "cheese omelette"
instead of forcing disambiguation between signature omelettes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'add_generic_omelette'
down_revision: Union[str, Sequence[str], None] = 'listen_only_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add generic Omelette menu item with base price $8.25."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get omelette item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()
    if not result:
        print("WARNING: 'omelette' item type not found, skipping")
        return
    omelette_type_id = result[0]

    # Check if generic Omelette already exists
    result = session.execute(
        sa.text("""
            SELECT id FROM menu_items
            WHERE name = 'Omelette' AND item_type_id = :item_type_id
        """),
        {"item_type_id": omelette_type_id}
    ).fetchone()
    if result:
        print("Generic 'Omelette' menu item already exists, skipping")
        return

    # Insert the generic Omelette menu item
    # required_match_phrases is NULL so it catches all generic omelette requests
    # available_qty = -1 means unlimited availability
    session.execute(
        sa.text("""
            INSERT INTO menu_items (name, item_type_id, is_signature, unit_type, available_qty)
            VALUES ('Omelette', :item_type_id, false, 'each', -1)
        """),
        {"item_type_id": omelette_type_id}
    )

    # Get the ID of the item we just created
    result = session.execute(
        sa.text("""
            SELECT id FROM menu_items
            WHERE name = 'Omelette' AND item_type_id = :item_type_id
        """),
        {"item_type_id": omelette_type_id}
    ).fetchone()
    menu_item_id = result[0]

    # Add pricing (size_id=6 is "each" for single items)
    session.execute(
        sa.text("""
            INSERT INTO menu_item_size_prices (menu_item_id, size_id, price)
            VALUES (:menu_item_id, 6, 8.25)
        """),
        {"menu_item_id": menu_item_id}
    )

    session.commit()
    print(f"Created generic 'Omelette' menu item (id={menu_item_id}) with base price $8.25")


def downgrade() -> None:
    """Remove generic Omelette menu item."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get omelette item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()
    if not result:
        return
    omelette_type_id = result[0]

    # Get the menu item ID
    result = session.execute(
        sa.text("""
            SELECT id FROM menu_items
            WHERE name = 'Omelette' AND item_type_id = :item_type_id
        """),
        {"item_type_id": omelette_type_id}
    ).fetchone()
    if not result:
        return
    menu_item_id = result[0]

    # Delete pricing first (foreign key constraint)
    session.execute(
        sa.text("DELETE FROM menu_item_size_prices WHERE menu_item_id = :menu_item_id"),
        {"menu_item_id": menu_item_id}
    )

    # Delete the menu item
    session.execute(
        sa.text("DELETE FROM menu_items WHERE id = :menu_item_id"),
        {"menu_item_id": menu_item_id}
    )

    session.commit()
    print("Removed generic 'Omelette' menu item")
