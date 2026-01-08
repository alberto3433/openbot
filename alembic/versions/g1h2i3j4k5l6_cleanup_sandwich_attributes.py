"""Cleanup sandwich attributes - remove duplicates and fix naming

Revision ID: g1h2i3j4k5l6
Revises: final_ingr01
Create Date: 2026-01-07

This migration:
1. Remove duplicate options across sandwich types (bread, cheese, toppings, proteins)
2. Fix cheese naming (remove "Cheese" suffix)
3. Fix display order for salad_sandwich and spread_sandwich (start at 1)
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'g1h2i3j4k5l6'
down_revision = 'final_ingr01'
branch_labels = None
depends_on = None


def remove_duplicates(conn, item_type_id, attr_slug, item_name):
    """Remove duplicate options for an attribute, keeping the first occurrence."""
    attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = :slug
        """),
        {"item_type_id": item_type_id, "slug": attr_slug}
    ).fetchone()

    if not attr:
        return

    attr_id = attr[0]

    # Find duplicates
    duplicates = conn.execute(
        text("""
            SELECT slug, MIN(id) as keep_id, COUNT(*) as cnt
            FROM attribute_options
            WHERE item_type_attribute_id = :attr_id
            GROUP BY slug
            HAVING COUNT(*) > 1
        """),
        {"attr_id": attr_id}
    ).fetchall()

    for row in duplicates:
        slug = row[0]
        keep_id = row[1]
        conn.execute(
            text("""
                DELETE FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
                AND slug = :slug
                AND id != :keep_id
            """),
            {"attr_id": attr_id, "slug": slug, "keep_id": keep_id}
        )
        print(f"  {item_name}: Removed duplicate {attr_slug} option: {slug}")


def fix_cheese_naming(conn, item_type_id, item_name):
    """Remove 'Cheese' suffix from cheese display names."""
    cheese_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'cheese'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if not cheese_attr:
        return

    cheese_attr_id = cheese_attr[0]

    # Standardize cheese naming
    cheese_updates = [
        ('american', 'American'),
        ('swiss', 'Swiss'),
        ('cheddar', 'Cheddar'),
        ('muenster', 'Muenster'),
        ('provolone', 'Provolone'),
        ('pepper_jack', 'Pepper Jack'),
        ('feta', 'Feta'),
    ]

    for slug, display_name in cheese_updates:
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = :display_name
                WHERE item_type_attribute_id = :attr_id AND slug = :slug
            """),
            {"attr_id": cheese_attr_id, "slug": slug, "display_name": display_name}
        )

    print(f"  {item_name}: Standardized cheese naming")


def upgrade() -> None:
    """Clean up sandwich attributes."""
    conn = op.get_bind()

    # =========================================================================
    # 1. deli_sandwich cleanup
    # =========================================================================
    deli = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'deli_sandwich'")
    ).fetchone()

    if deli:
        item_type_id = deli[0]
        print(f"Cleaning up deli_sandwich (id={item_type_id})")

        remove_duplicates(conn, item_type_id, 'bread', 'deli_sandwich')
        remove_duplicates(conn, item_type_id, 'cheese', 'deli_sandwich')
        remove_duplicates(conn, item_type_id, 'toppings', 'deli_sandwich')
        remove_duplicates(conn, item_type_id, 'extra_protein', 'deli_sandwich')
        fix_cheese_naming(conn, item_type_id, 'deli_sandwich')

    # =========================================================================
    # 2. fish_sandwich cleanup
    # =========================================================================
    fish = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'fish_sandwich'")
    ).fetchone()

    if fish:
        item_type_id = fish[0]
        print(f"Cleaning up fish_sandwich (id={item_type_id})")

        remove_duplicates(conn, item_type_id, 'bread', 'fish_sandwich')
        remove_duplicates(conn, item_type_id, 'cheese', 'fish_sandwich')
        remove_duplicates(conn, item_type_id, 'toppings', 'fish_sandwich')
        fix_cheese_naming(conn, item_type_id, 'fish_sandwich')

    # =========================================================================
    # 3. spread_sandwich cleanup
    # =========================================================================
    spread = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'spread_sandwich'")
    ).fetchone()

    if spread:
        item_type_id = spread[0]
        print(f"Cleaning up spread_sandwich (id={item_type_id})")

        # Fix display order (currently starts at 0)
        display_order_updates = [
            ('spread', 1),
            ('bread', 2),
            ('toasted', 3),
            ('extra_spread', 4),
            ('cheese', 5),
            ('proteins', 6),
            ('toppings', 7),
            ('condiments', 8),
        ]

        for slug, order in display_order_updates:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET display_order = :order
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": item_type_id, "slug": slug, "order": order}
            )
        print("  spread_sandwich: Fixed display order")

        remove_duplicates(conn, item_type_id, 'cheese', 'spread_sandwich')
        remove_duplicates(conn, item_type_id, 'proteins', 'spread_sandwich')
        remove_duplicates(conn, item_type_id, 'toppings', 'spread_sandwich')
        fix_cheese_naming(conn, item_type_id, 'spread_sandwich')

    # =========================================================================
    # 4. salad_sandwich cleanup
    # =========================================================================
    salad_sand = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'salad_sandwich'")
    ).fetchone()

    if salad_sand:
        item_type_id = salad_sand[0]
        print(f"Cleaning up salad_sandwich (id={item_type_id})")

        # Fix display order (currently starts at 0)
        display_order_updates = [
            ('salad', 1),
            ('bread', 2),
            ('toasted', 3),
            ('extras', 4),
        ]

        for slug, order in display_order_updates:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET display_order = :order
                    WHERE item_type_id = :item_type_id AND slug = :slug
                """),
                {"item_type_id": item_type_id, "slug": slug, "order": order}
            )
        print("  salad_sandwich: Fixed display order")

    print("Sandwich cleanup complete")


def downgrade() -> None:
    """
    This migration makes data changes that are difficult to reverse.
    """
    print("WARNING: Downgrade not fully implemented - data changes cannot be easily reversed")
