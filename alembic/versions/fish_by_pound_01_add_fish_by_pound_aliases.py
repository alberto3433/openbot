"""Add aliases for fish by-the-pound item type.

Revision ID: fish_by_pound_01
Revises: split_protein01
Create Date: 2026-02-04 12:00:00.000000

This migration adds aliases to the `fish` item type so that phrases like
"fish by the pound" and "smoked fish" are recognized as category queries.

When a user says "fish by the pound", the system should list available
fish items (Nova Scotia Salmon, Sable, Whitefish, etc.) rather than
falling back to LLM parsing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "fish_by_pound_01"
down_revision: Union[str, None] = "split_protein01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Aliases to add for the fish item type
# These help recognize "fish by the pound" as a category query
FISH_ALIASES = [
    "fish by the pound",
    "smoked fish",
    "smoked fish by the pound",
    "by the pound fish",
]


def upgrade() -> None:
    """Add aliases for the fish item type."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get the fish item type id
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'fish'")
    )
    row = result.fetchone()
    if not row:
        print("Warning: 'fish' item type not found, skipping alias creation")
        return

    fish_type_id = row[0]

    # Get existing aliases to avoid duplicates
    existing = session.execute(
        sa.text("SELECT alias FROM item_type_aliases WHERE item_type_id = :id"),
        {"id": fish_type_id}
    )
    existing_aliases = {r[0].lower() for r in existing}

    # Add new aliases
    for alias in FISH_ALIASES:
        if alias.lower() not in existing_aliases:
            session.execute(
                sa.text("""
                    INSERT INTO item_type_aliases (item_type_id, alias)
                    VALUES (:type_id, :alias)
                """),
                {"type_id": fish_type_id, "alias": alias}
            )
            print(f"Added alias '{alias}' for fish item type")

    session.commit()


def downgrade() -> None:
    """Remove the fish by-the-pound aliases."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get the fish item type id
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'fish'")
    )
    row = result.fetchone()
    if not row:
        return

    fish_type_id = row[0]

    # Remove the aliases we added
    for alias in FISH_ALIASES:
        session.execute(
            sa.text("""
                DELETE FROM item_type_aliases
                WHERE item_type_id = :type_id AND alias = :alias
            """),
            {"type_id": fish_type_id, "alias": alias}
        )

    session.commit()
