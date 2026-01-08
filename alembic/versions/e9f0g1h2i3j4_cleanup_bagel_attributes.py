"""Cleanup bagel attributes - fix display order and standardize slugs

Revision ID: e9f0g1h2i3j4
Revises: espresso_ingr01
Create Date: 2026-01-07

This migration:
1. Fix display order conflict (Spread and Extra Protein both at order=3)
2. Standardize protein slugs (remove bagel_ prefix for consistency)
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'e9f0g1h2i3j4'
down_revision = 'espresso_ingr01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clean up bagel attributes."""
    conn = op.get_bind()

    # Get bagel item type ID
    bagel_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()

    if not bagel_type:
        print("WARNING: bagel item type not found - skipping")
        return

    item_type_id = bagel_type[0]

    # =========================================================================
    # 1. Fix display order for attributes
    # =========================================================================
    # Current: bagel_type=1, toasted=2, spread=3, extra_protein=3, cheese=4, topping=5
    # Target:  bagel_type=1, toasted=2, spread=3, extra_protein=4, cheese=5, topping=6

    display_order_updates = [
        ('bagel_type', 1),
        ('toasted', 2),
        ('spread', 3),
        ('extra_protein', 4),
        ('cheese', 5),
        ('topping', 6),
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
    print("Fixed attribute display order")

    # =========================================================================
    # 2. Standardize protein slugs - remove bagel_ prefix
    # =========================================================================
    extra_protein_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'extra_protein'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if extra_protein_attr:
        attr_id = extra_protein_attr[0]

        # Map old slugs to new slugs (remove bagel_ prefix)
        slug_updates = [
            ('bagel_turkey_bacon', 'turkey_bacon', 'Turkey Bacon'),
            ('bagel_smoked_turkey', 'smoked_turkey', 'Smoked Turkey'),
            ('bagel_black_forest_ham', 'black_forest_ham', 'Black Forest Ham'),
            ('bagel_corned_beef', 'corned_beef', 'Corned Beef'),
            ('bagel_egg_salad', 'egg_salad', 'Egg Salad'),
            ('bagel_applewood_smoked_bacon', 'applewood_smoked_bacon', 'Applewood Smoked Bacon'),
            ('bagel_sausage_patty', 'sausage_patty', 'Sausage Patty'),
            ('bagel_chicken_sausage', 'chicken_sausage', 'Chicken Sausage'),
            ('bagel_roast_beef', 'roast_beef', 'Roast Beef'),
            ('bagel_espositos_sausage', 'espositos_sausage', "Esposito's Sausage"),
        ]

        for old_slug, new_slug, display_name in slug_updates:
            conn.execute(
                text("""
                    UPDATE attribute_options
                    SET slug = :new_slug, display_name = :display_name
                    WHERE item_type_attribute_id = :attr_id AND slug = :old_slug
                """),
                {"attr_id": attr_id, "old_slug": old_slug, "new_slug": new_slug, "display_name": display_name}
            )
            print(f"Renamed protein slug: {old_slug} -> {new_slug}")

    print("Bagel cleanup complete")


def downgrade() -> None:
    """Reverse the bagel cleanup."""
    conn = op.get_bind()

    bagel_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'bagel'")
    ).fetchone()

    if not bagel_type:
        return

    item_type_id = bagel_type[0]

    # Restore original display order
    display_order_updates = [
        ('extra_protein', 3),
        ('cheese', 4),
        ('topping', 5),
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

    # Restore bagel_ prefix on slugs
    extra_protein_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'extra_protein'
        """),
        {"item_type_id": item_type_id}
    ).fetchone()

    if extra_protein_attr:
        attr_id = extra_protein_attr[0]

        slug_updates = [
            ('turkey_bacon', 'bagel_turkey_bacon'),
            ('smoked_turkey', 'bagel_smoked_turkey'),
            ('black_forest_ham', 'bagel_black_forest_ham'),
            ('corned_beef', 'bagel_corned_beef'),
            ('egg_salad', 'bagel_egg_salad'),
            ('applewood_smoked_bacon', 'bagel_applewood_smoked_bacon'),
            ('sausage_patty', 'bagel_sausage_patty'),
            ('chicken_sausage', 'bagel_chicken_sausage'),
            ('roast_beef', 'bagel_roast_beef'),
            ('espositos_sausage', 'bagel_espositos_sausage'),
        ]

        for new_slug, old_slug in slug_updates:
            conn.execute(
                text("""
                    UPDATE attribute_options
                    SET slug = :old_slug
                    WHERE item_type_attribute_id = :attr_id AND slug = :new_slug
                """),
                {"attr_id": attr_id, "old_slug": old_slug, "new_slug": new_slug}
            )
