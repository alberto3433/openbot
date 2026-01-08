"""Cleanup egg_sandwich attributes - remove duplicates and fix classification

Revision ID: d8e9f0g1h2i3
Revises: b5c6d7e8f9g0
Create Date: 2026-01-07

This migration:
1. Remove duplicate bread options (everything_bagel, whole_wheat_bagel)
2. Clean up protein - remove duplicates (keep base proteins without upcharge), remove egg_white
3. Clean up cheese - remove duplicates (keep base without upcharge), standardize naming
4. Clean up toppings - remove duplicates (spinach), remove egg-related items
5. Fix jalapeno encoding issue
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'd8e9f0g1h2i3'
down_revision = 'c6d7e8f9g0h1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clean up egg_sandwich attributes."""
    conn = op.get_bind()

    # Get egg_sandwich item type ID
    egg_sandwich_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'egg_sandwich'")
    ).fetchone()

    if not egg_sandwich_type:
        print("WARNING: egg_sandwich item type not found - skipping")
        return

    item_type_id = egg_sandwich_type[0]

    # =========================================================================
    # 1. Remove duplicate bread options
    # =========================================================================
    bread_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'bread'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if bread_attr:
        bread_attr_id = bread_attr[0]

        # Find and remove duplicates - keep the first occurrence (lower id)
        duplicates = conn.execute(
            text("""
                SELECT slug, MIN(id) as keep_id, COUNT(*) as cnt
                FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
                GROUP BY slug
                HAVING COUNT(*) > 1
            """),
            {"attr_id": bread_attr_id}
        ).fetchall()

        for row in duplicates:
            slug = row[0]
            keep_id = row[1]
            # Delete all except the one we're keeping
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id
                    AND slug = :slug
                    AND id != :keep_id
                """),
                {"attr_id": bread_attr_id, "slug": slug, "keep_id": keep_id}
            )
            print(f"Removed duplicate bread option: {slug} (kept id={keep_id})")

    # =========================================================================
    # 2. Clean up protein - remove duplicates and egg_white
    # =========================================================================
    protein_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'protein'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if protein_attr:
        protein_attr_id = protein_attr[0]

        # Remove egg_white from protein (belongs in egg_style)
        conn.execute(
            text("""
                DELETE FROM attribute_options
                WHERE item_type_attribute_id = :attr_id AND slug = 'egg_white'
            """),
            {"attr_id": protein_attr_id}
        )
        print("Removed egg_white from protein (belongs in egg_style)")

        # Remove duplicate proteins - keep the base ones without upcharge (lower id)
        duplicates = conn.execute(
            text("""
                SELECT slug, MIN(id) as keep_id, COUNT(*) as cnt
                FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
                GROUP BY slug
                HAVING COUNT(*) > 1
            """),
            {"attr_id": protein_attr_id}
        ).fetchall()

        for row in duplicates:
            slug = row[0]
            keep_id = row[1]
            # Delete all except the one we're keeping
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id
                    AND slug = :slug
                    AND id != :keep_id
                """),
                {"attr_id": protein_attr_id, "slug": slug, "keep_id": keep_id}
            )
            print(f"Removed duplicate protein option: {slug} (kept id={keep_id})")

    # =========================================================================
    # 3. Clean up cheese - remove duplicates, standardize naming
    # =========================================================================
    cheese_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'cheese'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if cheese_attr:
        cheese_attr_id = cheese_attr[0]

        # Remove duplicate cheeses - keep the base ones without upcharge (lower id)
        duplicates = conn.execute(
            text("""
                SELECT slug, MIN(id) as keep_id, COUNT(*) as cnt
                FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
                GROUP BY slug
                HAVING COUNT(*) > 1
            """),
            {"attr_id": cheese_attr_id}
        ).fetchall()

        for row in duplicates:
            slug = row[0]
            keep_id = row[1]
            # Delete all except the one we're keeping
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id
                    AND slug = :slug
                    AND id != :keep_id
                """),
                {"attr_id": cheese_attr_id, "slug": slug, "keep_id": keep_id}
            )
            print(f"Removed duplicate cheese option: {slug} (kept id={keep_id})")

        # Standardize cheese naming - remove "Cheese" suffix
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = 'American'
                WHERE item_type_attribute_id = :attr_id AND slug = 'american'
            """),
            {"attr_id": cheese_attr_id}
        )
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = 'Swiss'
                WHERE item_type_attribute_id = :attr_id AND slug = 'swiss'
            """),
            {"attr_id": cheese_attr_id}
        )
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = 'Cheddar'
                WHERE item_type_attribute_id = :attr_id AND slug = 'cheddar'
            """),
            {"attr_id": cheese_attr_id}
        )
        print("Standardized cheese naming (removed 'Cheese' suffix)")

    # =========================================================================
    # 4. Clean up toppings - remove duplicates and egg-related items
    # =========================================================================
    toppings_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'toppings'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if toppings_attr:
        toppings_attr_id = toppings_attr[0]

        # Remove egg-related items (handled by egg_style and egg_quantity)
        egg_items = ['egg', 'scrambled_eggs', 'extra_egg', 'egg_white']
        for slug in egg_items:
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id AND slug = :slug
                """),
                {"attr_id": toppings_attr_id, "slug": slug}
            )
        print(f"Removed egg-related items from toppings: {egg_items}")

        # Remove duplicate toppings - keep the first occurrence
        duplicates = conn.execute(
            text("""
                SELECT slug, MIN(id) as keep_id, COUNT(*) as cnt
                FROM attribute_options
                WHERE item_type_attribute_id = :attr_id
                GROUP BY slug
                HAVING COUNT(*) > 1
            """),
            {"attr_id": toppings_attr_id}
        ).fetchall()

        for row in duplicates:
            slug = row[0]
            keep_id = row[1]
            # Delete all except the one we're keeping
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id
                    AND slug = :slug
                    AND id != :keep_id
                """),
                {"attr_id": toppings_attr_id, "slug": slug, "keep_id": keep_id}
            )
            print(f"Removed duplicate topping: {slug} (kept id={keep_id})")

        # Fix jalapeno encoding - standardize to 'Jalapeno' (ASCII-safe)
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = 'Jalapeno'
                WHERE item_type_attribute_id = :attr_id
                AND (slug = 'jalapeno' OR slug LIKE '%jalap%')
            """),
            {"attr_id": toppings_attr_id}
        )
        print("Fixed jalapeno encoding")

    print("Egg sandwich cleanup complete")


def downgrade() -> None:
    """
    This migration makes data changes that are difficult to reverse.
    """
    print("WARNING: Downgrade not fully implemented - data changes cannot be easily reversed")
