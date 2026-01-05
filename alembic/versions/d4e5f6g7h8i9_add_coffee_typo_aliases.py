"""add_coffee_typo_aliases

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h9
Create Date: 2025-01-05

Adds common typo variations as aliases for coffee items, allowing the
database-driven lookup to handle misspellings like "expresso", "cappucino", etc.

This replaces the hardcoded COFFEE_TYPO_MAP constant in constants.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6g7h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Coffee typo aliases to add (will be appended to existing aliases)
# Format: item name -> list of typo aliases to add
COFFEE_TYPO_ALIASES = {
    "Cappuccino": ["cappuccino", "capuccino", "cappucino", "cappuccinno", "capuchino", "appuccino"],
    "Espresso": ["expresso", "expreso", "esspresso"],  # Note: "espresso" already exists
    "Latte": ["latte", "late", "lattee"],
    "Americano": ["americano", "amercano"],
    "Macchiato": ["macchiato", "machiato", "machato"],
}


def upgrade() -> None:
    """Add typo aliases to coffee items."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('aliases', sa.String),
        )

        for item_name, typo_aliases in COFFEE_TYPO_ALIASES.items():
            # Get current aliases for this item
            result = session.execute(
                sa.select(menu_items.c.aliases).where(menu_items.c.name == item_name)
            )
            row = result.fetchone()

            if row:
                current_aliases = row[0]
                # Parse existing aliases into a set
                existing = set()
                if current_aliases:
                    existing = {a.strip().lower() for a in current_aliases.split(',') if a.strip()}

                # Add new typo aliases
                for alias in typo_aliases:
                    existing.add(alias.lower())

                # Build new aliases string
                new_aliases = ', '.join(sorted(existing))

                session.execute(
                    menu_items.update()
                    .where(menu_items.c.name == item_name)
                    .values(aliases=new_aliases)
                )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove typo aliases from coffee items (restore to base aliases only)."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Restore original aliases (before typos were added)
        ORIGINAL_ALIASES = {
            "Cappuccino": None,
            "Espresso": "espresso",
            "Latte": None,
            "Americano": None,
            "Macchiato": None,
        }

        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('aliases', sa.String),
        )

        for item_name, original in ORIGINAL_ALIASES.items():
            session.execute(
                menu_items.update()
                .where(menu_items.c.name == item_name)
                .values(aliases=original)
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
