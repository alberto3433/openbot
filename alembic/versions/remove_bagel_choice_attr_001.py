"""Remove legacy bagel_choice attribute from omelette item type

Revision ID: remove_bagel_choice_attr_001
Revises: add_suffixed_aliases_001
Create Date: 2026-01-19

The bagel_choice attribute was used in the OLD architecture where a bagel
ordered as a side of an omelette was stored as an attribute on the parent
omelette (e.g., omelette.attribute_values.bagel_choice = "everything").

With the NEW child item model, bagels ordered as sides are separate MenuItemTask
items linked via side_of_item_id, using the standard "bread" attribute
(e.g., child_bagel.attribute_values.bread = "everything").

The handler code (handle_bagel_choice_for_side) was already dead code and
has been removed. This migration removes the database artifact.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'remove_bagel_choice_attr_001'
down_revision: Union[str, Sequence[str], None] = 'add_suffixed_aliases_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove bagel_choice attribute and its ingredient links from omelette."""
    conn = op.get_bind()

    # Get omelette item type ID
    omelette = conn.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if not omelette:
        print("No omelette item type found, skipping")
        return

    omelette_id = omelette[0]

    # 1. Delete item_type_ingredients links for bagel_choice ingredient_group
    result = conn.execute(
        sa.text("""
            DELETE FROM item_type_ingredients
            WHERE item_type_id = :item_type_id
            AND ingredient_group = 'bagel_choice'
        """),
        {"item_type_id": omelette_id}
    )
    print(f"Deleted {result.rowcount} item_type_ingredients links for bagel_choice")

    # 2. Delete the bagel_choice attribute from item_type_attributes
    result = conn.execute(
        sa.text("""
            DELETE FROM item_type_attributes
            WHERE item_type_id = :item_type_id
            AND slug = 'bagel_choice'
        """),
        {"item_type_id": omelette_id}
    )
    print(f"Deleted {result.rowcount} item_type_attributes row for bagel_choice")


def downgrade() -> None:
    """Re-add bagel_choice attribute to omelette (for rollback)."""
    conn = op.get_bind()

    # Get omelette item type ID
    omelette = conn.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if not omelette:
        print("No omelette item type found, skipping")
        return

    omelette_id = omelette[0]

    # 1. Re-add the bagel_choice attribute
    # Using display_order=20 to place it after other attributes
    conn.execute(
        sa.text("""
            INSERT INTO item_type_attributes (
                item_type_id, slug, display_name, input_type, is_required,
                ask_in_conversation, display_order, loads_from_ingredients
            ) VALUES (
                :item_type_id, 'bagel_choice', 'Bagel Choice', 'single_select',
                false, true, 20, true
            )
        """),
        {"item_type_id": omelette_id}
    )

    # 2. Re-add ingredient links for bagel breads
    # Get all bread ingredients (category='bread')
    breads = conn.execute(
        sa.text("SELECT id FROM ingredients WHERE category = 'bread'")
    ).fetchall()

    for bread in breads:
        conn.execute(
            sa.text("""
                INSERT INTO item_type_ingredients (
                    item_type_id, ingredient_id, ingredient_group, price_modifier, is_available
                ) VALUES (
                    :item_type_id, :ingredient_id, 'bagel_choice', 0.0, true
                )
            """),
            {"item_type_id": omelette_id, "ingredient_id": bread[0]}
        )

    print("Re-added bagel_choice attribute and ingredient links")
