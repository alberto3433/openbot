"""Add Flatz, Bialy, and Flagel menu items

Revision ID: 94fb05fcc38f
Revises: f0a1b2c3d4e5
Create Date: 2026-02-17

Adds orderable menu items so customers can say "give me a flatz/bialy/flagel":
- Flatz: new item_type (like bagel but with flatz bread options)
- Bialy & Flagel: bagel-type items with bread pre-filled via menu_item_ingredients
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


# revision identifiers, used by Alembic.
revision: str = '94fb05fcc38f'
down_revision: Union[str, Sequence[str], None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BAGEL_PRICE = 2.50
EACH_SIZE_ID = 6


def upgrade() -> None:
    bind = op.get_bind()
    session = Session(bind=bind)

    # ---------------------------------------------------------------
    # Look up bagel item_type (source for cloning)
    # ---------------------------------------------------------------
    bagel_type = session.execute(
        sa.text("SELECT id, menu_display_group_id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()
    if not bagel_type:
        print("WARNING: 'bagel' item type not found, skipping migration")
        return
    bagel_type_id = bagel_type[0]
    breads_display_group_id = bagel_type[1]  # menu_display_group_id = 1 (Breads)

    # ---------------------------------------------------------------
    # 1. FLATZ — new item_type + menu item
    # ---------------------------------------------------------------

    # 1a. Create 'flatz' item_type (same config as bagel)
    existing = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'flatz'")
    ).fetchone()
    if existing:
        flatz_type_id = existing[0]
        print(f"'flatz' item type already exists (id={flatz_type_id})")
    else:
        session.execute(
            sa.text("""
                INSERT INTO item_types (slug, display_name, menu_display_group_id, has_side_choice)
                VALUES ('flatz', 'Flatz', :display_group_id, false)
            """),
            {"display_group_id": breads_display_group_id}
        )
        flatz_type_id = session.execute(
            sa.text("SELECT id FROM item_types WHERE slug = 'flatz'")
        ).fetchone()[0]
        print(f"Created 'flatz' item type (id={flatz_type_id})")

    # 1b. Clone item_type_global_attributes from bagel → flatz
    existing_attrs = session.execute(
        sa.text("""
            SELECT COUNT(*) FROM item_type_global_attributes
            WHERE item_type_id = :flatz_type_id
        """),
        {"flatz_type_id": flatz_type_id}
    ).fetchone()[0]

    if existing_attrs > 0:
        print(f"Flatz already has {existing_attrs} global attributes, skipping clone")
    else:
        # Get all bagel attributes
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
            # Override bread attribute's subcategory filter: 'bagel' → 'flatz'
            subcategory_filter = attr[6]
            if subcategory_filter == 'bagel':
                subcategory_filter = 'flatz'

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
                    "item_type_id": flatz_type_id,
                    "global_attribute_id": attr[0],
                    "display_order": attr[1],
                    "is_required": attr[2],
                    "allow_none": attr[3],
                    "ask_in_conversation": attr[4],
                    "listen_only": attr[5],
                    "option_subcategory_filter": subcategory_filter,
                    "min_selections": attr[7],
                    "max_selections": attr[8],
                }
            )
        print(f"Cloned {len(bagel_attrs)} global attributes from bagel to flatz")

    # 1c. Create generic "Flatz" menu item
    flatz_item = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Flatz'")
    ).fetchone()
    if flatz_item:
        flatz_item_id = flatz_item[0]
        print(f"'Flatz' menu item already exists (id={flatz_item_id})")
    else:
        session.execute(
            sa.text("""
                INSERT INTO menu_items
                    (name, item_type_id, is_signature, unit_type, available_qty,
                     is_vegan, is_vegetarian, is_dairy_free, is_kosher)
                VALUES ('Flatz', :item_type_id, false, 'each', 999,
                        true, true, true, true)
            """),
            {"item_type_id": flatz_type_id}
        )
        flatz_item_id = session.execute(
            sa.text("SELECT id FROM menu_items WHERE name = 'Flatz'")
        ).fetchone()[0]
        print(f"Created 'Flatz' menu item (id={flatz_item_id})")

        # Add pricing
        session.execute(
            sa.text("""
                INSERT INTO menu_item_size_prices (menu_item_id, size_id, price)
                VALUES (:menu_item_id, :size_id, :price)
            """),
            {"menu_item_id": flatz_item_id, "size_id": EACH_SIZE_ID, "price": BAGEL_PRICE}
        )
        print(f"  Added pricing: ${BAGEL_PRICE}")

    # 1d. Add item_type_aliases for flatz
    existing_alias = session.execute(
        sa.text("SELECT id FROM item_type_aliases WHERE alias = 'flatzes'")
    ).fetchone()
    if not existing_alias:
        session.execute(
            sa.text("""
                INSERT INTO item_type_aliases (item_type_id, alias)
                VALUES (:item_type_id, 'flatzes')
            """),
            {"item_type_id": flatz_type_id}
        )
        print("  Added item_type_alias: 'flatzes'")

    # ---------------------------------------------------------------
    # 2. BIALY — bagel-type menu item with bread pre-filled
    # ---------------------------------------------------------------
    bialy_item = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Bialy'")
    ).fetchone()
    if bialy_item:
        bialy_item_id = bialy_item[0]
        print(f"'Bialy' menu item already exists (id={bialy_item_id})")
    else:
        session.execute(
            sa.text("""
                INSERT INTO menu_items
                    (name, item_type_id, is_signature, unit_type, available_qty,
                     is_vegan, is_vegetarian, is_dairy_free, is_kosher)
                VALUES ('Bialy', :item_type_id, false, 'each', 999,
                        true, true, true, true)
            """),
            {"item_type_id": bagel_type_id}
        )
        bialy_item_id = session.execute(
            sa.text("SELECT id FROM menu_items WHERE name = 'Bialy'")
        ).fetchone()[0]
        print(f"Created 'Bialy' menu item (id={bialy_item_id})")

        # Add pricing
        session.execute(
            sa.text("""
                INSERT INTO menu_item_size_prices (menu_item_id, size_id, price)
                VALUES (:menu_item_id, :size_id, :price)
            """),
            {"menu_item_id": bialy_item_id, "size_id": EACH_SIZE_ID, "price": BAGEL_PRICE}
        )
        print(f"  Added pricing: ${BAGEL_PRICE}")

        # Link to Bialy bread ingredient for bread pre-fill
        bialy_ingredient = session.execute(
            sa.text("""
                SELECT id FROM ingredients WHERE slug = 'bialy' AND category = 'bread'
            """)
        ).fetchone()
        if bialy_ingredient:
            session.execute(
                sa.text("""
                    INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity)
                    VALUES (:menu_item_id, :ingredient_id, 1)
                """),
                {"menu_item_id": bialy_item_id, "ingredient_id": bialy_ingredient[0]}
            )
            print(f"  Linked to Bialy bread ingredient (id={bialy_ingredient[0]})")
        else:
            print("  WARNING: 'bialy' bread ingredient not found, bread pre-fill won't work")

    # Add menu_item_aliases for Bialy
    existing_alias = session.execute(
        sa.text("SELECT id FROM menu_item_aliases WHERE alias = 'bialys'")
    ).fetchone()
    if not existing_alias:
        session.execute(
            sa.text("""
                INSERT INTO menu_item_aliases (menu_item_id, alias)
                VALUES (:menu_item_id, 'bialys')
            """),
            {"menu_item_id": bialy_item_id}
        )
        print("  Added menu_item_alias: 'bialys'")

    # ---------------------------------------------------------------
    # 3. FLAGEL — bagel-type menu item with bread pre-filled
    # ---------------------------------------------------------------
    flagel_item = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Flagel'")
    ).fetchone()
    if flagel_item:
        flagel_item_id = flagel_item[0]
        print(f"'Flagel' menu item already exists (id={flagel_item_id})")
    else:
        session.execute(
            sa.text("""
                INSERT INTO menu_items
                    (name, item_type_id, is_signature, unit_type, available_qty,
                     is_vegan, is_vegetarian, is_dairy_free, is_kosher)
                VALUES ('Flagel', :item_type_id, false, 'each', 999,
                        true, true, true, true)
            """),
            {"item_type_id": bagel_type_id}
        )
        flagel_item_id = session.execute(
            sa.text("SELECT id FROM menu_items WHERE name = 'Flagel'")
        ).fetchone()[0]
        print(f"Created 'Flagel' menu item (id={flagel_item_id})")

        # Add pricing
        session.execute(
            sa.text("""
                INSERT INTO menu_item_size_prices (menu_item_id, size_id, price)
                VALUES (:menu_item_id, :size_id, :price)
            """),
            {"menu_item_id": flagel_item_id, "size_id": EACH_SIZE_ID, "price": BAGEL_PRICE}
        )
        print(f"  Added pricing: ${BAGEL_PRICE}")

        # Link to Flagel bread ingredient for bread pre-fill
        flagel_ingredient = session.execute(
            sa.text("""
                SELECT id FROM ingredients WHERE slug = 'flagel' AND category = 'bread'
            """)
        ).fetchone()
        if flagel_ingredient:
            session.execute(
                sa.text("""
                    INSERT INTO menu_item_ingredients (menu_item_id, ingredient_id, quantity)
                    VALUES (:menu_item_id, :ingredient_id, 1)
                """),
                {"menu_item_id": flagel_item_id, "ingredient_id": flagel_ingredient[0]}
            )
            print(f"  Linked to Flagel bread ingredient (id={flagel_ingredient[0]})")
        else:
            print("  WARNING: 'flagel' bread ingredient not found, bread pre-fill won't work")

    # Add menu_item_aliases for Flagel
    existing_alias = session.execute(
        sa.text("SELECT id FROM menu_item_aliases WHERE alias = 'flagels'")
    ).fetchone()
    if not existing_alias:
        session.execute(
            sa.text("""
                INSERT INTO menu_item_aliases (menu_item_id, alias)
                VALUES (:menu_item_id, 'flagels')
            """),
            {"menu_item_id": flagel_item_id}
        )
        print("  Added menu_item_alias: 'flagels'")

    session.commit()
    print("\nMigration complete: Flatz, Bialy, and Flagel menu items added")


def downgrade() -> None:
    """Remove Flatz, Bialy, and Flagel menu items and flatz item_type."""
    bind = op.get_bind()
    session = Session(bind=bind)

    # --- Remove Flagel ---
    flagel = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Flagel'")
    ).fetchone()
    if flagel:
        flagel_id = flagel[0]
        session.execute(
            sa.text("DELETE FROM menu_item_aliases WHERE menu_item_id = :id"),
            {"id": flagel_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_item_ingredients WHERE menu_item_id = :id"),
            {"id": flagel_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_item_size_prices WHERE menu_item_id = :id"),
            {"id": flagel_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_items WHERE id = :id"), {"id": flagel_id}
        )

    # --- Remove Bialy ---
    bialy = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Bialy'")
    ).fetchone()
    if bialy:
        bialy_id = bialy[0]
        session.execute(
            sa.text("DELETE FROM menu_item_aliases WHERE menu_item_id = :id"),
            {"id": bialy_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_item_ingredients WHERE menu_item_id = :id"),
            {"id": bialy_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_item_size_prices WHERE menu_item_id = :id"),
            {"id": bialy_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_items WHERE id = :id"), {"id": bialy_id}
        )

    # --- Remove Flatz menu item ---
    flatz_item = session.execute(
        sa.text("SELECT id FROM menu_items WHERE name = 'Flatz'")
    ).fetchone()
    if flatz_item:
        flatz_item_id = flatz_item[0]
        session.execute(
            sa.text("DELETE FROM menu_item_aliases WHERE menu_item_id = :id"),
            {"id": flatz_item_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_item_size_prices WHERE menu_item_id = :id"),
            {"id": flatz_item_id}
        )
        session.execute(
            sa.text("DELETE FROM menu_items WHERE id = :id"), {"id": flatz_item_id}
        )

    # --- Remove Flatz item_type ---
    flatz_type = session.execute(
        sa.text("SELECT id FROM item_types WHERE slug = 'flatz'")
    ).fetchone()
    if flatz_type:
        flatz_type_id = flatz_type[0]
        session.execute(
            sa.text("DELETE FROM item_type_aliases WHERE item_type_id = :id"),
            {"id": flatz_type_id}
        )
        session.execute(
            sa.text("DELETE FROM item_type_global_attributes WHERE item_type_id = :id"),
            {"id": flatz_type_id}
        )
        session.execute(
            sa.text("DELETE FROM item_types WHERE id = :id"), {"id": flatz_type_id}
        )

    session.commit()
    print("Downgrade complete: Removed Flatz, Bialy, and Flagel menu items")
