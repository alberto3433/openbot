"""add_matcha_and_coffee_aliases

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-01-04

Adds 'Seasonal Matcha Latte' as a new menu item and populates aliases for
sized_beverage (coffee/tea) items to support database-driven lookup.

This replaces the hardcoded COFFEE_BEVERAGE_TYPES constant in constants.py
with database-driven lookups via the aliases column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'p0q1r2s3t4u5'
down_revision: Union[str, Sequence[str], None] = 'o9p0q1r2s3t4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Coffee/tea aliases mapping: item name -> comma-separated aliases
# These enable matching simplified keywords like "chai" to "Chai Tea"
COFFEE_ALIASES = {
    # Tea drinks - "tea" keyword
    "Hot Tea": "tea",
    "Iced Tea": "tea",
    "Green Tea": "tea, green tea",
    "Earl Grey Tea": "tea, earl grey",
    "English Breakfast Tea": "tea, english breakfast",
    "Chamomile Tea": "tea, chamomile",
    "Peppermint Tea": "tea, peppermint",

    # Chai drinks - "chai" keyword
    "Chai Tea": "chai",
    "Iced Chai Tea": "chai, iced chai",

    # Coffee - additional aliases
    "Coffee": "drip, drip coffee, regular coffee",

    # Hot Chocolate - additional aliases
    "Hot Chocolate": "hot cocoa, cocoa",

    # Espresso drinks - ensure "espresso" keyword works
    "Espresso": "espresso",
    "Double Espresso": "espresso, double espresso",

    # Cold brew
    "Cold Brew": "cold brew, coldbrew",

    # Cafe au Lait
    "Cafe au Lait": "cafe au lait, au lait",

    # Iced versions
    "Iced Cappuccino": "iced cappuccino",
}


def upgrade() -> None:
    """Add Seasonal Matcha Latte menu item and populate coffee/tea aliases."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # First, get the sized_beverage item_type_id
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
        )
        row = result.fetchone()
        if not row:
            raise RuntimeError("sized_beverage item_type not found")
        sized_beverage_id = row[0]

        # Add Seasonal Matcha Latte menu item
        # Check if it already exists
        result = session.execute(
            sa.text("SELECT id FROM menu_items WHERE name = 'Seasonal Matcha Latte'")
        )
        if not result.fetchone():
            session.execute(
                sa.text("""
                    INSERT INTO menu_items (
                        name, category, is_signature, base_price,
                        available_qty, item_type_id, aliases
                    ) VALUES (
                        'Seasonal Matcha Latte', 'beverage', FALSE, 6.50,
                        100, :item_type_id, 'matcha, matcha latte'
                    )
                """),
                {"item_type_id": sized_beverage_id}
            )

        # Update coffee/tea items with aliases
        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('aliases', sa.String),
        )

        for item_name, aliases in COFFEE_ALIASES.items():
            session.execute(
                menu_items.update()
                .where(menu_items.c.name == item_name)
                .values(aliases=aliases)
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove Seasonal Matcha Latte and clear coffee/tea aliases."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Remove Seasonal Matcha Latte
        session.execute(
            sa.text("DELETE FROM menu_items WHERE name = 'Seasonal Matcha Latte'")
        )

        # Clear aliases for coffee/tea items
        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('aliases', sa.String),
        )

        for item_name in COFFEE_ALIASES.keys():
            session.execute(
                menu_items.update()
                .where(menu_items.c.name == item_name)
                .values(aliases=None)
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
