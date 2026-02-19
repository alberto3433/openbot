"""Promote Flagel and Bialy to own item types

Revision ID: flagel_bialy_01
Revises: 94fb05fcc38f
Create Date: 2026-02-18

Flagel and Bialy were previously bagel-type menu items with bread pre-filled
via menu_item_ingredients. But the bread question was still being asked.

This migration promotes them to their own item types (like Flatz), cloning
bagel attributes but setting ask_in_conversation=False on the bread attribute.
The bread value is auto-populated by populate_default_ingredients() from the
existing menu_item_ingredients link, so the system skips straight to "toasted?".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = 'flagel_bialy_01'
down_revision: Union[str, Sequence[str], None] = '94fb05fcc38f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# bread global_attribute_id = 3 (from seed migration s7t8u9v0w1x2)
BREAD_GLOBAL_ATTRIBUTE_ID = 3


def _create_item_type(session: Session, slug: str, display_name: str,
                      display_group_id: int, bagel_type_id: int) -> int:
    """Create a new item type and clone bagel attributes with bread ask disabled."""

    # Check if already exists (idempotent)
    existing = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = :slug"),
        {"slug": slug}
    ).fetchone()
    if existing:
        print(f"'{slug}' item type already exists (id={existing[0]})")
        return existing[0]

    # Create item type
    session.execute(
        sa.text("""
            INSERT INTO item_types (slug, display_name, menu_display_group_id, has_side_choice)
            VALUES (:slug, :display_name, :display_group_id, false)
        """),
        {"slug": slug, "display_name": display_name, "display_group_id": display_group_id}
    )
    new_type_id = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = :slug"),
        {"slug": slug}
    ).fetchone()[0]
    print(f"Created '{slug}' item type (id={new_type_id})")

    # Clone item_type_global_attributes from bagel
    bagel_attrs = session.execute(
        sa.text("""
            SELECT global_attribute_id, display_order, is_required, allow_none,
                   ask_in_conversation, listen_only, option_subcategory_filter,
                   min_selections, max_selections
            FROM item_type_global_attributes
            WHERE item_type_id = :bagel_type_id
            ORDER BY display_order
        """),
        {"bagel_type_id": bagel_type_id}
    ).fetchall()

    for attr in bagel_attrs:
        global_attr_id = attr[0]
        ask_in_conv = attr[4]

        # For bread attribute: set ask_in_conversation=False
        # (bread is auto-filled from menu_item_ingredients defaults)
        if global_attr_id == BREAD_GLOBAL_ATTRIBUTE_ID:
            ask_in_conv = False

        session.execute(
            sa.text("""
                INSERT INTO item_type_global_attributes
                    (item_type_id, global_attribute_id, display_order, is_required,
                     allow_none, ask_in_conversation, listen_only,
                     option_subcategory_filter, min_selections, max_selections)
                VALUES (:item_type_id, :global_attribute_id, :display_order, :is_required,
                        :allow_none, :ask_in_conversation, :listen_only,
                        :option_subcategory_filter, :min_selections, :max_selections)
            """),
            {
                "item_type_id": new_type_id,
                "global_attribute_id": global_attr_id,
                "display_order": attr[1],
                "is_required": attr[2],
                "allow_none": attr[3],
                "ask_in_conversation": ask_in_conv,
                "listen_only": attr[5],
                "option_subcategory_filter": attr[6],
                "min_selections": attr[7],
                "max_selections": attr[8],
            }
        )
    print(f"  Cloned {len(bagel_attrs)} global attributes from bagel "
          f"(bread ask_in_conversation=False)")

    return new_type_id


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    # Look up bagel item_type
    bagel_type = session.execute(
        sa.text("SELECT id, menu_display_group_id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()
    if not bagel_type:
        print("WARNING: 'bagel' item type not found, skipping migration")
        return
    bagel_type_id = bagel_type[0]
    breads_display_group_id = bagel_type[1]

    # ---------------------------------------------------------------
    # 1. FLAGEL
    # ---------------------------------------------------------------
    flagel_type_id = _create_item_type(
        session, 'flagel', 'Flagel', breads_display_group_id, bagel_type_id
    )

    # Update Flagel menu item to use new item type
    flagel_item = session.execute(
        sa.text("SELECT id, item_type_id FROM menu_items WHERE name = 'Flagel'")
    ).fetchone()
    if flagel_item:
        if flagel_item[1] != flagel_type_id:
            session.execute(
                sa.text("UPDATE menu_items SET item_type_id = :type_id WHERE id = :id"),
                {"type_id": flagel_type_id, "id": flagel_item[0]}
            )
            print(f"  Updated Flagel menu item to item_type_id={flagel_type_id}")
        else:
            print(f"  Flagel menu item already has item_type_id={flagel_type_id}")
    else:
        print("  WARNING: 'Flagel' menu item not found")

    # Add item_type_alias for plural
    existing_alias = session.execute(
        sa.text("SELECT id FROM item_type_aliases WHERE alias = 'flagels'")
    ).fetchone()
    if not existing_alias:
        session.execute(
            sa.text("""
                INSERT INTO item_type_aliases (item_type_id, alias)
                VALUES (:item_type_id, 'flagels')
            """),
            {"item_type_id": flagel_type_id}
        )
        print("  Added item_type_alias: 'flagels'")

    # ---------------------------------------------------------------
    # 2. BIALY
    # ---------------------------------------------------------------
    bialy_type_id = _create_item_type(
        session, 'bialy', 'Bialy', breads_display_group_id, bagel_type_id
    )

    # Update Bialy menu item to use new item type
    bialy_item = session.execute(
        sa.text("SELECT id, item_type_id FROM menu_items WHERE name = 'Bialy'")
    ).fetchone()
    if bialy_item:
        if bialy_item[1] != bialy_type_id:
            session.execute(
                sa.text("UPDATE menu_items SET item_type_id = :type_id WHERE id = :id"),
                {"type_id": bialy_type_id, "id": bialy_item[0]}
            )
            print(f"  Updated Bialy menu item to item_type_id={bialy_type_id}")
        else:
            print(f"  Bialy menu item already has item_type_id={bialy_type_id}")
    else:
        print("  WARNING: 'Bialy' menu item not found")

    # Add item_type_alias for plural
    existing_alias = session.execute(
        sa.text("SELECT id FROM item_type_aliases WHERE alias = 'bialys'")
    ).fetchone()
    if not existing_alias:
        session.execute(
            sa.text("""
                INSERT INTO item_type_aliases (item_type_id, alias)
                VALUES (:item_type_id, 'bialys')
            """),
            {"item_type_id": bialy_type_id}
        )
        print("  Added item_type_alias: 'bialys'")

    session.commit()
    print("\nMigration complete: Flagel and Bialy promoted to own item types")


def downgrade() -> None:
    """Revert Flagel and Bialy back to bagel item type."""
    bind = op.get_bind()
    session = Session(bind=bind)

    bagel_type = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()
    if not bagel_type:
        print("WARNING: 'bagel' item type not found, skipping downgrade")
        return
    bagel_type_id = bagel_type[0]

    for slug, name in [('flagel', 'Flagel'), ('bialy', 'Bialy')]:
        item_type = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = :slug"),
            {"slug": slug}
        ).fetchone()
        if not item_type:
            print(f"'{slug}' item type not found, skipping")
            continue
        type_id = item_type[0]

        # Update menu item back to bagel type
        session.execute(
            sa.text("UPDATE menu_items SET item_type_id = :bagel_id WHERE item_type_id = :type_id"),
            {"bagel_id": bagel_type_id, "type_id": type_id}
        )
        print(f"  Reverted {name} menu item to bagel item type")

        # Delete item_type_aliases
        session.execute(
            sa.text("DELETE FROM item_type_aliases WHERE item_type_id = :id"),
            {"id": type_id}
        )

        # Delete item_type_global_attributes
        session.execute(
            sa.text("DELETE FROM item_type_global_attributes WHERE item_type_id = :id"),
            {"id": type_id}
        )

        # Delete item_type
        session.execute(
            sa.text("DELETE FROM item_types WHERE id = :id"),
            {"id": type_id}
        )
        print(f"  Deleted '{slug}' item type")

    session.commit()
    print("\nDowngrade complete: Flagel and Bialy reverted to bagel item type")
