"""Seed omelette side component slot

Revision ID: comp_slot_02
Revises: comp_slot_01
Create Date: 2026-02-01

This migration adds the "side" component slot to omelettes, allowing
customers to choose between a bagel (configurable) or fruit salad.
Both options are included in the omelette price (base price = $0),
but any upcharges (GF bagel, cream cheese) still apply.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'comp_slot_02'
down_revision: Union[str, Sequence[str], None] = 'comp_slot_01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add side slot to omelettes with bagel and fruit salad options."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get omelette item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()
    if not result:
        print("WARNING: 'omelette' item type not found, skipping seed")
        return
    omelette_type_id = result[0]

    # Get bagel item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()
    if not result:
        print("WARNING: 'bagel' item type not found, skipping seed")
        return
    bagel_type_id = result[0]

    # Get fruit salad menu item ID (it's a specific menu item, not a type)
    result = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name ILIKE '%fruit salad%' LIMIT 1")
    ).fetchone()
    fruit_salad_id = result[0] if result else None

    # Create the "side" slot for omelettes
    session.execute(
        sa.text("""
            INSERT INTO item_type_component_slots
            (parent_item_type_id, slot_name, display_name, prompt_text, is_required, min_quantity, max_quantity, display_order)
            VALUES
            (:parent_id, 'side', 'Side', 'Would you like a bagel or fruit salad with that?', true, 1, 1, 0)
        """),
        {"parent_id": omelette_type_id}
    )

    # Get the slot ID we just created
    result = session.execute(
        sa.text("""
            SELECT id FROM item_type_component_slots
            WHERE parent_item_type_id = :parent_id AND slot_name = 'side'
        """),
        {"parent_id": omelette_type_id}
    ).fetchone()
    slot_id = result[0]

    # Add bagel as an option (item type - fully configurable)
    session.execute(
        sa.text("""
            INSERT INTO component_slot_options
            (slot_id, allowed_item_type_id, price_rule, display_name, display_order)
            VALUES
            (:slot_id, :bagel_type_id, 'included', 'Bagel', 1)
        """),
        {"slot_id": slot_id, "bagel_type_id": bagel_type_id}
    )

    # Add fruit salad as an option (specific menu item if found, otherwise skip)
    if fruit_salad_id:
        session.execute(
            sa.text("""
                INSERT INTO component_slot_options
                (slot_id, allowed_menu_item_id, price_rule, display_name, display_order)
                VALUES
                (:slot_id, :fruit_salad_id, 'included', 'Fruit Salad', 2)
            """),
            {"slot_id": slot_id, "fruit_salad_id": fruit_salad_id}
        )
    else:
        # If no fruit salad menu item, create with item_type instead
        # First check if there's a fruit_salad item type
        result = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'fruit_salad'")
        ).fetchone()
        if result:
            fruit_salad_type_id = result[0]
            session.execute(
                sa.text("""
                    INSERT INTO component_slot_options
                    (slot_id, allowed_item_type_id, price_rule, display_name, display_order)
                    VALUES
                    (:slot_id, :fruit_salad_type_id, 'included', 'Fruit Salad', 2)
                """),
                {"slot_id": slot_id, "fruit_salad_type_id": fruit_salad_type_id}
            )
        else:
            print("WARNING: No fruit salad item type or menu item found")

    session.commit()
    print(f"Created 'side' slot for omelettes (slot_id={slot_id})")


def downgrade() -> None:
    """Remove omelette side slot."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # Get omelette item type ID
    result = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()
    if not result:
        return
    omelette_type_id = result[0]

    # Delete the slot (options will cascade delete)
    session.execute(
        sa.text("""
            DELETE FROM item_type_component_slots
            WHERE parent_item_type_id = :parent_id AND slot_name = 'side'
        """),
        {"parent_id": omelette_type_id}
    )
    session.commit()
