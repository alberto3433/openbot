"""Consolidate Iced Chai Tea and Double Espresso into base items with modifiers.

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2025-01-05 14:00:00.000000

This migration:
1. Removes "Iced Chai Tea" menu item - use "Chai Tea" with "iced" modifier instead
2. Removes "Double Espresso" menu item - use "Espresso" with "double" modifier
3. Updates Chai Tea aliases to include "iced chai" for backwards compatibility
4. Updates Espresso aliases to include "double espresso" for backwards compatibility
5. Adds espresso shot modifier options (double: +$0.50, triple: +$1.00)

Pricing analysis:
- Chai Tea: $4.50, Iced Chai Tea: $5.00 -> difference is $0.50 (iced upcharge)
- Espresso: $3.50, Double Espresso: $4.00 -> difference is $0.50 (extra shot)
- Triple Espresso: $4.50 estimated (+$1.00 over single)

Sources:
- Zucker's Bagels SinglePlatform menu: http://places.singleplatform.com/the-zuckers-bagels-and-smoked-fish/menu
- MenuXP: https://www.menuxp.com/zuckers-bagels-menu
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6g7h8i9j0k1"
down_revision: Union[str, None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove redundant menu items and add modifiers."""
    conn = op.get_bind()

    # 1. Update Chai Tea aliases to include "iced chai" before deleting Iced Chai Tea
    result = conn.execute(
        sa.text("SELECT id, aliases FROM menu_items WHERE name = 'Chai Tea'")
    )
    row = result.fetchone()
    if row:
        chai_id = row[0]
        current_aliases = row[1] or ""
        # Add "iced chai" to aliases
        alias_set = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}
        alias_set.add("iced chai")
        alias_set.add("iced chai tea")
        new_aliases = ", ".join(sorted(alias_set))
        conn.execute(
            sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": new_aliases, "id": chai_id}
        )
        print(f"Updated Chai Tea aliases: {new_aliases}")

    # 2. Update Espresso aliases to include "double espresso" before deleting Double Espresso
    result = conn.execute(
        sa.text("SELECT id, aliases FROM menu_items WHERE name = 'Espresso'")
    )
    row = result.fetchone()
    if row:
        espresso_id = row[0]
        current_aliases = row[1] or ""
        # Add "double espresso" and "triple espresso" to aliases
        alias_set = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}
        alias_set.add("double espresso")
        alias_set.add("triple espresso")
        new_aliases = ", ".join(sorted(alias_set))
        conn.execute(
            sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": new_aliases, "id": espresso_id}
        )
        print(f"Updated Espresso aliases: {new_aliases}")

    # 3. Delete Iced Chai Tea menu item
    result = conn.execute(
        sa.text("DELETE FROM menu_items WHERE name = 'Iced Chai Tea' RETURNING id, name")
    )
    deleted = result.fetchone()
    if deleted:
        print(f"Deleted menu item: {deleted[1]} (id={deleted[0]})")
    else:
        print("Warning: Iced Chai Tea not found")

    # 4. Delete Double Espresso menu item
    result = conn.execute(
        sa.text("DELETE FROM menu_items WHERE name = 'Double Espresso' RETURNING id, name")
    )
    deleted = result.fetchone()
    if deleted:
        print(f"Deleted menu item: {deleted[1]} (id={deleted[0]})")
    else:
        print("Warning: Double Espresso not found")

    # 5. Add espresso shot modifier options to sized_beverage extras
    # First, get the extras attribute definition for sized_beverage
    result = conn.execute(
        sa.text("""
            SELECT ad.id
            FROM attribute_definitions ad
            JOIN item_types it ON ad.item_type_id = it.id
            WHERE it.slug = 'sized_beverage' AND ad.slug = 'extras'
        """)
    )
    row = result.fetchone()
    if row:
        extras_attr_id = row[0]

        # Check if double_shot and triple_shot already exist
        result = conn.execute(
            sa.text("""
                SELECT slug FROM attribute_options
                WHERE attribute_definition_id = :attr_id AND slug IN ('double_shot', 'triple_shot')
            """),
            {"attr_id": extras_attr_id}
        )
        existing = {r[0] for r in result.fetchall()}

        # Get max display order
        result = conn.execute(
            sa.text("""
                SELECT COALESCE(MAX(display_order), 0)
                FROM attribute_options
                WHERE attribute_definition_id = :attr_id
            """),
            {"attr_id": extras_attr_id}
        )
        max_order = result.fetchone()[0]

        # Add double_shot option if not exists
        if "double_shot" not in existing:
            conn.execute(
                sa.text("""
                    INSERT INTO attribute_options
                    (attribute_definition_id, slug, display_name, price_modifier, is_default, is_available, display_order)
                    VALUES (:attr_id, 'double_shot', 'Double Shot', 0.50, false, true, :order)
                """),
                {"attr_id": extras_attr_id, "order": max_order + 1}
            )
            print("Added double_shot modifier: +$0.50")

        # Add triple_shot option if not exists
        if "triple_shot" not in existing:
            conn.execute(
                sa.text("""
                    INSERT INTO attribute_options
                    (attribute_definition_id, slug, display_name, price_modifier, is_default, is_available, display_order)
                    VALUES (:attr_id, 'triple_shot', 'Triple Shot', 1.00, false, true, :order)
                """),
                {"attr_id": extras_attr_id, "order": max_order + 2}
            )
            print("Added triple_shot modifier: +$1.00")
    else:
        print("Warning: sized_beverage extras attribute not found")


def downgrade() -> None:
    """Restore deleted menu items and remove modifiers."""
    conn = op.get_bind()

    # 1. Restore Iced Chai Tea menu item
    conn.execute(
        sa.text("""
            INSERT INTO menu_items (name, category, base_price, aliases)
            VALUES ('Iced Chai Tea', 'drink', 5.00, 'chai, iced chai')
        """)
    )
    print("Restored Iced Chai Tea menu item")

    # 2. Restore Double Espresso menu item
    conn.execute(
        sa.text("""
            INSERT INTO menu_items (name, category, base_price, aliases)
            VALUES ('Double Espresso', 'drink', 4.00, 'espresso, double espresso')
        """)
    )
    print("Restored Double Espresso menu item")

    # 3. Remove "iced chai" from Chai Tea aliases
    result = conn.execute(
        sa.text("SELECT id, aliases FROM menu_items WHERE name = 'Chai Tea'")
    )
    row = result.fetchone()
    if row:
        chai_id = row[0]
        current_aliases = row[1] or ""
        alias_set = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}
        alias_set.discard("iced chai")
        alias_set.discard("iced chai tea")
        new_aliases = ", ".join(sorted(alias_set))
        conn.execute(
            sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": new_aliases, "id": chai_id}
        )

    # 4. Remove "double espresso" and "triple espresso" from Espresso aliases
    result = conn.execute(
        sa.text("SELECT id, aliases FROM menu_items WHERE name = 'Espresso'")
    )
    row = result.fetchone()
    if row:
        espresso_id = row[0]
        current_aliases = row[1] or ""
        alias_set = {a.strip().lower() for a in current_aliases.split(",") if a.strip()}
        alias_set.discard("double espresso")
        alias_set.discard("triple espresso")
        new_aliases = ", ".join(sorted(alias_set))
        conn.execute(
            sa.text("UPDATE menu_items SET aliases = :aliases WHERE id = :id"),
            {"aliases": new_aliases, "id": espresso_id}
        )

    # 5. Remove double_shot and triple_shot modifiers
    conn.execute(
        sa.text("DELETE FROM attribute_options WHERE slug IN ('double_shot', 'triple_shot')")
    )
    print("Removed double_shot and triple_shot modifiers")
