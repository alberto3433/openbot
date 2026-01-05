"""Add remaining menu item aliases (omelettes and other missing items).

Revision ID: c3d4e5f6g7h9
Revises: b2c3d4e5f6g8
Create Date: 2025-01-04 23:30:00.000000

This migration adds aliases for items that were not covered by the previous
MENU_ITEM_CANONICAL_NAMES migration, including:
- Omelette short forms (cheese omelette, veggie omelette, etc.)
- Other missing short forms from NO_THE_PREFIX_ITEMS
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h9"
down_revision: Union[str, None] = "b2c3d4e5f6g8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Additional alias mappings
# Format: {canonical_name: [list of aliases to add]}
ADDITIONAL_ALIASES = {
    # Omelettes without aliases
    "Cheese Omelette": ["cheese omelette", "cheese omelet"],
    "Western Omelette": ["western omelette", "western omelet"],
    "Veggie Omelette": ["veggie omelette", "veggie omelet"],
    "Corned Beef Omelette": ["corned beef omelette", "corned beef omelet"],
    "Pastrami Omelette": ["pastrami omelette", "pastrami omelet"],
    "Salami Omelette": ["salami omelette", "salami omelet"],
    "Sausage Omelette": ["sausage omelette", "sausage omelet"],
    "Southwest Omelette": ["southwest omelette", "southwest omelet"],
    "Turkey Omelette": ["turkey omelette", "turkey omelet"],
    "Truffle Omelette": ["truffle omelette", "truffle omelet"],
    "Egg White Avocado Omelette": ["egg white avocado omelette", "egg white avocado omelet", "avocado omelette", "avocado omelet"],
    # Other missing items
    "Hummus Sandwich": ["hummus"],
    "Turkey Club": ["turkey club"],
    "Hot Pastrami Sandwich": ["pastrami sandwich"],
    # Additional tropicana alias
    "Tropicana Orange Juice 46 oz": ["tropicana orange juice"],
}


def upgrade() -> None:
    """Add remaining aliases to menu items."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        for canonical_name, new_aliases in ADDITIONAL_ALIASES.items():
            # Get current item and its aliases
            result = session.execute(
                sa.text("SELECT id, aliases FROM menu_items WHERE LOWER(name) = LOWER(:name)"),
                {"name": canonical_name}
            )
            row = result.fetchone()

            if not row:
                print(f"  WARNING: Menu item not found: {canonical_name}")
                continue

            item_id, existing_aliases = row

            # Parse existing aliases into a set
            existing_set = set()
            if existing_aliases:
                existing_set = {a.strip().lower() for a in existing_aliases.split(",")}

            # Add new aliases (avoiding duplicates)
            new_aliases_lower = {a.lower() for a in new_aliases}
            combined_aliases = existing_set | new_aliases_lower

            # Sort and join
            combined_csv = ", ".join(sorted(combined_aliases))

            # Update if changed
            if combined_csv != existing_aliases:
                session.execute(
                    sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
                    {"aliases": combined_csv, "id": item_id}
                )
                added = new_aliases_lower - existing_set
                if added:
                    print(f"  {canonical_name}: added {added}")

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """This migration cannot be easily reversed as it merges aliases."""
    pass
