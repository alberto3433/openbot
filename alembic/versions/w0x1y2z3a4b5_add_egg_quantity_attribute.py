"""Add egg quantity attribute to egg_sandwich and omelette item types

Revision ID: w0x1y2z3a4b5
Revises: v9w0x1y2z3a4
Create Date: 2026-01-07

This migration adds an "Egg Quantity" attribute to allow customers to order
additional eggs on egg sandwiches and omelettes.

Configuration:
- Egg Sandwich: Default 2 eggs, options up to 4 eggs
- Omelette: Default 3 eggs, options up to 6 eggs
- Extra egg price: $1.50 each (only charged for eggs above default)
- Optional field with pre-selected default
- Don't ask in conversation (assume default, customer can request more)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'w0x1y2z3a4b5'
down_revision = 'v9w0x1y2z3a4'
branch_labels = None
depends_on = None


# Egg quantity options for each item type
# Format: (slug, display_name, price_modifier, is_default, display_order)
EGG_SANDWICH_OPTIONS = [
    ('2_eggs', '2 eggs (standard)', 0.0, True, 0),
    ('3_eggs', '3 eggs', 1.50, False, 1),
    ('4_eggs', '4 eggs', 3.00, False, 2),
]

OMELETTE_OPTIONS = [
    ('3_eggs', '3 eggs (standard)', 0.0, True, 0),
    ('4_eggs', '4 eggs', 1.50, False, 1),
    ('5_eggs', '5 eggs', 3.00, False, 2),
    ('6_eggs', '6 eggs', 4.50, False, 3),
]


def upgrade() -> None:
    """Add egg_quantity attribute to egg_sandwich and omelette item types."""
    conn = op.get_bind()

    # Get item type IDs
    egg_sandwich_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'")
    ).fetchone()

    omelette_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if not egg_sandwich_type:
        print("WARNING: egg_sandwich item type not found - skipping")
    if not omelette_type:
        print("WARNING: omelette item type not found - skipping")

    # Get the highest display_order for each item type to add at end
    def get_max_display_order(item_type_id):
        result = conn.execute(
            text("""
                SELECT COALESCE(MAX(display_order), -1) + 1
                FROM item_type_attributes
                WHERE item_type_id = :item_type_id
            """),
            {"item_type_id": item_type_id}
        ).scalar()
        return result or 0

    # Create attribute and options for egg_sandwich
    if egg_sandwich_type:
        egg_sandwich_id = egg_sandwich_type[0]
        display_order = get_max_display_order(egg_sandwich_id)

        # Create the attribute
        conn.execute(
            text("""
                INSERT INTO item_type_attributes
                (item_type_id, slug, display_name, input_type, is_required,
                 allow_none, display_order, ask_in_conversation, question_text)
                VALUES
                (:item_type_id, 'egg_quantity', 'Egg Quantity', 'single_select',
                 false, false, :display_order, false, 'How many eggs would you like?')
            """),
            {"item_type_id": egg_sandwich_id, "display_order": display_order}
        )

        # Get the new attribute ID
        attr_id = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'egg_quantity'
            """),
            {"item_type_id": egg_sandwich_id}
        ).scalar()

        # Create options
        for slug, display_name, price_modifier, is_default, order in EGG_SANDWICH_OPTIONS:
            conn.execute(
                text("""
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier,
                     is_default, is_available, display_order)
                    VALUES
                    (:attr_id, :slug, :display_name, :price_modifier,
                     :is_default, true, :display_order)
                """),
                {
                    "attr_id": attr_id,
                    "slug": slug,
                    "display_name": display_name,
                    "price_modifier": price_modifier,
                    "is_default": is_default,
                    "display_order": order,
                }
            )

        print(f"Created egg_quantity attribute for egg_sandwich (id={attr_id})")

    # Create attribute and options for omelette
    if omelette_type:
        omelette_id = omelette_type[0]
        display_order = get_max_display_order(omelette_id)

        # Create the attribute
        conn.execute(
            text("""
                INSERT INTO item_type_attributes
                (item_type_id, slug, display_name, input_type, is_required,
                 allow_none, display_order, ask_in_conversation, question_text)
                VALUES
                (:item_type_id, 'egg_quantity', 'Egg Quantity', 'single_select',
                 false, false, :display_order, false, 'How many eggs would you like?')
            """),
            {"item_type_id": omelette_id, "display_order": display_order}
        )

        # Get the new attribute ID
        attr_id = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'egg_quantity'
            """),
            {"item_type_id": omelette_id}
        ).scalar()

        # Create options
        for slug, display_name, price_modifier, is_default, order in OMELETTE_OPTIONS:
            conn.execute(
                text("""
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier,
                     is_default, is_available, display_order)
                    VALUES
                    (:attr_id, :slug, :display_name, :price_modifier,
                     :is_default, true, :display_order)
                """),
                {
                    "attr_id": attr_id,
                    "slug": slug,
                    "display_name": display_name,
                    "price_modifier": price_modifier,
                    "is_default": is_default,
                    "display_order": order,
                }
            )

        print(f"Created egg_quantity attribute for omelette (id={attr_id})")


def downgrade() -> None:
    """Remove egg_quantity attribute from egg_sandwich and omelette item types."""
    conn = op.get_bind()

    # Get item type IDs
    egg_sandwich_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'")
    ).fetchone()

    omelette_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    item_type_ids = []
    if egg_sandwich_type:
        item_type_ids.append(egg_sandwich_type[0])
    if omelette_type:
        item_type_ids.append(omelette_type[0])

    if not item_type_ids:
        return

    # Get attribute IDs to delete
    for item_type_id in item_type_ids:
        attr_id = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'egg_quantity'
            """),
            {"item_type_id": item_type_id}
        ).scalar()

        if attr_id:
            # Delete options first (due to FK constraints)
            conn.execute(
                text("DELETE FROM attribute_options WHERE item_type_attribute_id = :attr_id"),
                {"attr_id": attr_id}
            )

            # Delete the attribute
            conn.execute(
                text("DELETE FROM item_type_attributes WHERE id = :attr_id"),
                {"attr_id": attr_id}
            )

            print(f"Removed egg_quantity attribute (id={attr_id})")
