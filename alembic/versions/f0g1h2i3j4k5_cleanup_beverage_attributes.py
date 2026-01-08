"""Cleanup beverage attributes - fix display order and remove duplicates

Revision ID: f0g1h2i3j4k5
Revises: e9f0g1h2i3j4
Create Date: 2026-01-07

This migration:
1. sized_beverage: Fix display order conflicts (size/style at 2, milk/sweetener at 4)
2. sized_beverage: Remove duplicate milk options (keep _milk suffix versions)
3. espresso: Fix display order conflicts (5 attributes at order 0)
4. espresso: Standardize syrup naming (remove "Syrup" suffix)
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'f0g1h2i3j4k5'
down_revision = 'e9f0g1h2i3j4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clean up beverage attributes."""
    conn = op.get_bind()

    # =========================================================================
    # 1. Fix sized_beverage display order and duplicates
    # =========================================================================
    sized_bev = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'sized_beverage'")
    ).fetchone()

    if sized_bev:
        item_type_id = sized_bev[0]
        print(f"Cleaning up sized_beverage (id={item_type_id})")

        # Fix display order
        # Current: drink_type=1, size=2, style=2, iced=3, sweetener=4, milk=4, syrup=5, extras=6
        # Target:  drink_type=1, size=2, style=3, iced=4, milk=5, sweetener=6, syrup=7, extras=8
        display_order_updates = [
            ('drink_type', 1),
            ('size', 2),
            ('style', 3),
            ('iced', 4),
            ('milk', 5),
            ('sweetener', 6),
            ('syrup', 7),
            ('extras', 8),
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
        print("  Fixed sized_beverage attribute display order")

        # Remove duplicate milk options (keep _milk suffix versions, remove short versions)
        milk_attr = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'milk'
            """),
            {"item_type_id": item_type_id}
        ).fetchone()

        if milk_attr:
            milk_attr_id = milk_attr[0]

            # Remove short slug duplicates (whole, skim, oat, almond, soy)
            short_slugs = ['whole', 'skim', 'oat', 'almond', 'soy']
            for slug in short_slugs:
                conn.execute(
                    text("""
                        DELETE FROM attribute_options
                        WHERE item_type_attribute_id = :attr_id AND slug = :slug
                    """),
                    {"attr_id": milk_attr_id, "slug": slug}
                )
            print(f"  Removed duplicate milk options: {short_slugs}")

            # Standardize milk display names (remove "Milk" suffix where redundant)
            milk_name_updates = [
                ('whole_milk', 'Whole'),
                ('half_n_half', 'Half & Half'),
                ('lactose_free', 'Lactose Free'),
                ('almond_milk', 'Almond'),
                ('oat_milk', 'Oat'),
                ('soy_milk', 'Soy'),
            ]

            for slug, display_name in milk_name_updates:
                conn.execute(
                    text("""
                        UPDATE attribute_options
                        SET display_name = :display_name
                        WHERE item_type_attribute_id = :attr_id AND slug = :slug
                    """),
                    {"attr_id": milk_attr_id, "slug": slug, "display_name": display_name}
                )
            print("  Standardized milk display names")

    # =========================================================================
    # 2. Fix espresso display order and syrup naming
    # =========================================================================
    espresso = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'espresso'")
    ).fetchone()

    if espresso:
        item_type_id = espresso[0]
        print(f"Cleaning up espresso (id={item_type_id})")

        # Fix display order
        # Current: extra_shot=0, decaf=0, milk=0, sweetener=0, syrup=0, shots=1
        # Target:  shots=1, milk=2, sweetener=3, syrup=4, extra_shot=5, decaf=6
        display_order_updates = [
            ('shots', 1),
            ('milk', 2),
            ('sweetener', 3),
            ('syrup', 4),
            ('extra_shot', 5),
            ('decaf', 6),
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
        print("  Fixed espresso attribute display order")

        # Standardize syrup naming (remove "Syrup" suffix)
        syrup_attr = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'syrup'
            """),
            {"item_type_id": item_type_id}
        ).fetchone()

        if syrup_attr:
            syrup_attr_id = syrup_attr[0]

            syrup_updates = [
                ('hazelnut_syrup', 'hazelnut', 'Hazelnut'),
                ('vanilla_syrup', 'vanilla', 'Vanilla'),
            ]

            for old_slug, new_slug, display_name in syrup_updates:
                conn.execute(
                    text("""
                        UPDATE attribute_options
                        SET slug = :new_slug, display_name = :display_name
                        WHERE item_type_attribute_id = :attr_id AND slug = :old_slug
                    """),
                    {"attr_id": syrup_attr_id, "old_slug": old_slug, "new_slug": new_slug, "display_name": display_name}
                )
            print("  Standardized syrup naming (removed 'Syrup' suffix)")

        # Also standardize milk display names for espresso
        milk_attr = conn.execute(
            text("""
                SELECT id FROM item_type_attributes
                WHERE item_type_id = :item_type_id AND slug = 'milk'
            """),
            {"item_type_id": item_type_id}
        ).fetchone()

        if milk_attr:
            milk_attr_id = milk_attr[0]

            milk_name_updates = [
                ('half_n_half', 'Half & Half'),
                ('almond_milk', 'Almond'),
                ('oat_milk', 'Oat'),
                ('soy_milk', 'Soy'),
            ]

            for slug, display_name in milk_name_updates:
                conn.execute(
                    text("""
                        UPDATE attribute_options
                        SET display_name = :display_name
                        WHERE item_type_attribute_id = :attr_id AND slug = :slug
                    """),
                    {"attr_id": milk_attr_id, "slug": slug, "display_name": display_name}
                )
            print("  Standardized espresso milk display names")

    print("Beverage cleanup complete")


def downgrade() -> None:
    """
    This migration makes data changes that are difficult to reverse.
    """
    print("WARNING: Downgrade not fully implemented - data changes cannot be easily reversed")
