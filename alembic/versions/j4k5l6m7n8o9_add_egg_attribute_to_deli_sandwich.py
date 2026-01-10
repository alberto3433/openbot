"""Add 'Add Egg' attribute to deli_sandwich item type

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-01-08 16:00:00.000000

This migration adds an "Add Egg" attribute to deli sandwiches with 6 egg options,
each with a $2.05 upcharge:
- Scrambled Egg
- Fried Egg (Sunny Side Up)
- Over Easy Egg
- Over Medium Egg
- Over Hard Egg
- Egg Whites (2)

The attribute is:
- Single select (pick one egg style)
- Optional (allow_none=True)
- Not asked in conversation (only if customer requests)
- NOT loaded from ingredients (uses attribute_options table)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j4k5l6m7n8o9'
down_revision: Union[str, Sequence[str], None] = 'i3j4k5l6m7n8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Egg options with their display names and slugs
EGG_OPTIONS = [
    ('scrambled_egg', 'Scrambled Egg', 1),
    ('fried_egg_sunny_side_up', 'Fried Egg (Sunny Side Up)', 2),
    ('over_easy_egg', 'Over Easy Egg', 3),
    ('over_medium_egg', 'Over Medium Egg', 4),
    ('over_hard_egg', 'Over Hard Egg', 5),
    ('egg_whites_2', 'Egg Whites (2)', 6),
]

EGG_UPCHARGE = 2.05


def upgrade() -> None:
    """Add Add Egg attribute and options to deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        print("Warning: deli_sandwich item type not found, skipping")
        return

    deli_sandwich_id = row[0]
    print(f"Found deli_sandwich item_type_id: {deli_sandwich_id}")

    # Get the max display_order for existing attributes
    result = conn.execute(sa.text("""
        SELECT COALESCE(MAX(display_order), 0) FROM item_type_attributes
        WHERE item_type_id = :item_type_id
    """), {'item_type_id': deli_sandwich_id})
    max_order = result.fetchone()[0]
    next_order = max_order + 1

    # Create the add_egg attribute
    conn.execute(sa.text("""
        INSERT INTO item_type_attributes (
            item_type_id, slug, display_name, input_type,
            is_required, allow_none, ask_in_conversation,
            loads_from_ingredients, display_order
        ) VALUES (
            :item_type_id, 'add_egg', 'Add Egg', 'single_select',
            FALSE, TRUE, FALSE,
            FALSE, :display_order
        )
    """), {'item_type_id': deli_sandwich_id, 'display_order': next_order})

    print(f"Created add_egg attribute with display_order={next_order}")

    # Get the newly created attribute ID
    result = conn.execute(sa.text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'add_egg'
    """), {'item_type_id': deli_sandwich_id})
    attr_row = result.fetchone()
    if not attr_row:
        print("Error: Could not find newly created add_egg attribute")
        return

    add_egg_attr_id = attr_row[0]
    print(f"add_egg attribute ID: {add_egg_attr_id}")

    # Create attribute options for each egg type
    for slug, display_name, display_order in EGG_OPTIONS:
        conn.execute(sa.text("""
            INSERT INTO attribute_options (
                item_type_attribute_id, slug, display_name,
                price_modifier, display_order, is_available, is_default
            ) VALUES (
                :attr_id, :slug, :display_name,
                :price, :display_order, TRUE, FALSE
            )
        """), {
            'attr_id': add_egg_attr_id,
            'slug': slug,
            'display_name': display_name,
            'price': EGG_UPCHARGE,
            'display_order': display_order,
        })
        print(f"  Added option: {display_name} (+${EGG_UPCHARGE})")

    print(f"Successfully added Add Egg attribute with {len(EGG_OPTIONS)} options")


def downgrade() -> None:
    """Remove Add Egg attribute and options from deli_sandwich."""
    conn = op.get_bind()

    # Get deli_sandwich item type ID
    result = conn.execute(sa.text(
        "SELECT id FROM item_types WHERE slug = 'deli_sandwich'"
    ))
    row = result.fetchone()
    if not row:
        return

    deli_sandwich_id = row[0]

    # Get the add_egg attribute ID
    result = conn.execute(sa.text("""
        SELECT id FROM item_type_attributes
        WHERE item_type_id = :item_type_id AND slug = 'add_egg'
    """), {'item_type_id': deli_sandwich_id})
    attr_row = result.fetchone()
    if not attr_row:
        return

    add_egg_attr_id = attr_row[0]

    # Delete attribute options first (foreign key constraint)
    conn.execute(sa.text("""
        DELETE FROM attribute_options
        WHERE item_type_attribute_id = :attr_id
    """), {'attr_id': add_egg_attr_id})

    # Delete the attribute
    conn.execute(sa.text("""
        DELETE FROM item_type_attributes
        WHERE id = :attr_id
    """), {'attr_id': add_egg_attr_id})

    print("Removed add_egg attribute and options from deli_sandwich")
