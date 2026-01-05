"""Add side item aliases to menu_items.

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2025-01-04 21:00:00.000000

This migration ensures side items exist in the database with proper names and aliases.
This replaces the hardcoded SIDE_ITEM_MAP in constants.py.

The pattern is: alias -> menu_items.name (canonical form)
For example: "sausage" -> "Side of Sausage"
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "z0a1b2c3d4e5"
down_revision: Union[str, None] = "y9z0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Side items to ensure exist with their aliases
# Format: (canonical_name, category, base_price, aliases_csv)
SIDE_ITEMS = [
    ("Side of Sausage", "side", 4.50, "sausage, espositos sausage, esposito's sausage"),
    ("Side of Bacon", "side", 4.50, "bacon, side bacon, applewood bacon, applewood smoked bacon"),
    ("Side of Turkey Bacon", "side", 4.50, "turkey bacon, side turkey bacon"),
    ("Side of Ham", "side", 4.50, "ham, side ham"),
    ("Side of Chicken Sausage", "side", 4.85, "chicken sausage, applewood chicken sausage"),
    ("Side of Breakfast Latke", "side", 5.95, "latke, latkes, breakfast latke, potato latke"),
    ("Hard Boiled Egg (2)", "side", 3.95, "hard boiled egg, hard boiled eggs, hardboiled egg, hardboiled eggs, eggs, two eggs"),
]


def upgrade() -> None:
    """Ensure side items exist and have aliases."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Get the side item_type id
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'side'")
        )
        row = result.fetchone()
        side_type_id = row[0] if row else None

        menu_items = sa.table(
            'menu_items',
            sa.column('id', sa.Integer),
            sa.column('name', sa.String),
            sa.column('category', sa.String),
            sa.column('base_price', sa.Float),
            sa.column('item_type_id', sa.Integer),
            sa.column('aliases', sa.String),
            sa.column('is_signature', sa.Boolean),
            sa.column('available_qty', sa.Integer),
        )

        for name, category, base_price, aliases in SIDE_ITEMS:
            # Check if item already exists
            result = session.execute(
                sa.text("SELECT id FROM menu_items WHERE LOWER(name) = LOWER(:name)"),
                {"name": name}
            )
            existing = result.fetchone()

            if existing:
                # Update aliases on existing item
                session.execute(
                    menu_items.update()
                    .where(menu_items.c.id == existing[0])
                    .values(aliases=aliases)
                )
                print(f"  Updated aliases for: {name}")
            else:
                # Insert new item
                session.execute(
                    menu_items.insert().values(
                        name=name,
                        category=category,
                        base_price=base_price,
                        item_type_id=side_type_id,
                        aliases=aliases,
                        is_signature=False,
                        available_qty=100,
                    )
                )
                print(f"  Created: {name}")

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def downgrade() -> None:
    """Remove side item aliases (but keep items)."""
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # Just clear the aliases, don't delete items
        for name, _, _, _ in SIDE_ITEMS:
            session.execute(
                sa.text("UPDATE menu_items SET aliases = NULL WHERE LOWER(name) = LOWER(:name)"),
                {"name": name}
            )

        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()
