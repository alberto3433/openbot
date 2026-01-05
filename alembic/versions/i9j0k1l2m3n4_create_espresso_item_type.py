"""Create espresso item type.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-01-05 14:00:00.000000

This migration:
1. Creates a new 'espresso' item type for espresso drinks
   - Espresso has no size options (always a single shot base)
   - Espresso is always hot (no iced option)
   - Double/triple are modifiers with upcharges
   - Other modifiers (milk, syrup, sugar) still apply

2. Updates the 'coffee' virtual type to expand to include 'espresso'
   so espresso shows up when users ask "what coffee drinks do you have?"

3. Updates the Espresso menu item to use the new 'espresso' item type
"""

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # 1. Create the espresso item type
        session.execute(
            sa.text("""
                INSERT INTO item_types (slug, display_name, is_configurable, skip_config, is_virtual)
                VALUES ('espresso', 'Espresso', TRUE, FALSE, FALSE)
            """)
        )
        print("Created 'espresso' item type")

        # 2. Update the 'coffee' virtual type to expand to include 'espresso'
        # Current expands_to is ['sized_beverage'], we want ['sized_beverage', 'espresso']
        session.execute(
            sa.text("""
                UPDATE item_types
                SET expands_to = :new_expands_to
                WHERE slug = 'coffee'
            """),
            {"new_expands_to": json.dumps(["sized_beverage", "espresso"])}
        )
        print("Updated 'coffee' virtual type to include 'espresso'")

        # 3. Get the new espresso item type ID
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'espresso'")
        ).fetchone()
        espresso_type_id = result[0]
        print(f"Espresso item type ID: {espresso_type_id}")

        # 4. Update the Espresso menu item to use the new item type
        # Also remove "double espresso" and "triple espresso" from aliases
        # since those will be handled as modifiers
        session.execute(
            sa.text("""
                UPDATE menu_items
                SET item_type_id = :espresso_type_id,
                    aliases = 'espresso, esspresso, expreso, expresso'
                WHERE LOWER(name) = 'espresso'
            """),
            {"espresso_type_id": espresso_type_id}
        )
        print("Updated Espresso menu item to use 'espresso' item type")

        session.commit()
        print("Migration completed successfully")

    except Exception as e:
        session.rollback()
        print(f"Migration failed: {e}")
        raise


def downgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    try:
        # 1. Get the sized_beverage item type ID
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
        ).fetchone()
        sized_beverage_type_id = result[0]

        # 2. Restore Espresso menu item to sized_beverage type
        session.execute(
            sa.text("""
                UPDATE menu_items
                SET item_type_id = :sized_beverage_type_id,
                    aliases = 'double espresso, espresso, esspresso, expreso, expresso, triple espresso'
                WHERE LOWER(name) = 'espresso'
            """),
            {"sized_beverage_type_id": sized_beverage_type_id}
        )

        # 3. Restore coffee virtual type to only expand to sized_beverage
        session.execute(
            sa.text("""
                UPDATE item_types
                SET expands_to = :old_expands_to
                WHERE slug = 'coffee'
            """),
            {"old_expands_to": json.dumps(["sized_beverage"])}
        )

        # 4. Delete the espresso item type
        session.execute(
            sa.text("DELETE FROM item_types WHERE slug = 'espresso'")
        )

        session.commit()

    except Exception as e:
        session.rollback()
        raise
