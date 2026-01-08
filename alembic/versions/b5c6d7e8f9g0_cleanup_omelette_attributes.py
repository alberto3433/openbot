"""Cleanup omelette attributes - remove duplicates and fix classification

Revision ID: b5c6d7e8f9g0
Revises: a4b5c6d7e8f9
Create Date: 2026-01-07

This migration:
1. Removes redundant 'eggs' attribute (egg_style already handles this)
2. Cleans up 'filling' to only have actual fillings (veggies that go inside)
3. Removes cheeses from filling (already in cheese attribute)
4. Removes proteins from filling (already in protein attribute)
5. Standardizes cheese naming (no "Cheese" suffix)
6. Removes duplicate protein options (esposito's_sausage)
7. Removes upcharges from base filling options (only extras should have upcharges)
"""
from alembic import op
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'b5c6d7e8f9g0'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Clean up omelette attributes."""
    conn = op.get_bind()

    # Get omelette item type ID
    omelette_type = conn.execute(
        text("SELECT id FROM item_types WHERE slug = 'omelette'")
    ).fetchone()

    if not omelette_type:
        print("WARNING: omelette item type not found - skipping")
        return

    omelette_id = omelette_type[0]

    # =========================================================================
    # 1. Remove redundant 'eggs' attribute (egg_style handles egg type selection)
    # =========================================================================
    eggs_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'eggs'
        """),
        {"item_type_id": omelette_id}
    ).fetchone()

    if eggs_attr:
        eggs_attr_id = eggs_attr[0]
        # Delete options first
        conn.execute(
            text("DELETE FROM attribute_options WHERE item_type_attribute_id = :attr_id"),
            {"attr_id": eggs_attr_id}
        )
        # Delete the attribute
        conn.execute(
            text("DELETE FROM item_type_attributes WHERE id = :attr_id"),
            {"attr_id": eggs_attr_id}
        )
        print("Removed redundant 'eggs' attribute")

    # =========================================================================
    # 2. Get filling attribute ID and clean it up
    # =========================================================================
    filling_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'filling'
        """),
        {"item_type_id": omelette_id}
    ).fetchone()

    if filling_attr:
        filling_attr_id = filling_attr[0]

        # Remove cheeses from filling (they're in cheese attribute)
        cheeses_to_remove = ['american_cheese', 'cheddar', 'swiss', 'muenster']
        for cheese in cheeses_to_remove:
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id AND slug = :slug
                """),
                {"attr_id": filling_attr_id, "slug": cheese}
            )
        print(f"Removed cheeses from filling: {cheeses_to_remove}")

        # Remove proteins from filling (they're in protein attribute)
        proteins_to_remove = ['turkey_bacon', 'sausage', 'nova_salmon', 'corned_beef', 'pastrami', 'ham']
        for protein in proteins_to_remove:
            conn.execute(
                text("""
                    DELETE FROM attribute_options
                    WHERE item_type_attribute_id = :attr_id AND slug = :slug
                """),
                {"attr_id": filling_attr_id, "slug": protein}
            )
        print(f"Removed proteins from filling: {proteins_to_remove}")

        # Remove upcharges from remaining filling options (veggies)
        # These are base fillings, not extras
        conn.execute(
            text("""
                UPDATE attribute_options
                SET price_modifier = 0
                WHERE item_type_attribute_id = :attr_id
            """),
            {"attr_id": filling_attr_id}
        )
        print("Removed upcharges from filling options (only extras should have upcharges)")

    # =========================================================================
    # 3. Standardize cheese naming - remove "Cheese" suffix from display names
    # =========================================================================
    cheese_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'cheese'
        """),
        {"item_type_id": omelette_id}
    ).fetchone()

    if cheese_attr:
        cheese_attr_id = cheese_attr[0]

        # Update display names to be consistent (no "Cheese" suffix)
        cheese_updates = [
            ('cheddar', 'Cheddar'),
            ('feta', 'Feta'),
            ('pepper_jack', 'Pepper Jack'),
            ('american', 'American'),
            ('swiss', 'Swiss'),
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

        # Add muenster if not present (was only in filling before)
        existing_muenster = conn.execute(
            text("""
                SELECT id FROM attribute_options
                WHERE item_type_attribute_id = :attr_id AND slug = 'muenster'
            """),
            {"attr_id": cheese_attr_id}
        ).fetchone()

        if not existing_muenster:
            conn.execute(
                text("""
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier, is_default, is_available, display_order)
                    VALUES (:attr_id, 'muenster', 'Muenster', 0, false, true, 5)
                """),
                {"attr_id": cheese_attr_id}
            )
            print("Added muenster to cheese options")

        print("Standardized cheese naming")

    # =========================================================================
    # 4. Clean up protein attribute - remove duplicates
    # =========================================================================
    protein_attr = conn.execute(
        text("""
            SELECT id FROM item_type_attributes
            WHERE item_type_id = :item_type_id AND slug = 'protein'
        """),
        {"item_type_id": omelette_id}
    ).fetchone()

    if protein_attr:
        protein_attr_id = protein_attr[0]

        # Remove duplicate esposito's_sausage (keep espositos_sausage)
        conn.execute(
            text("""
                DELETE FROM attribute_options
                WHERE item_type_attribute_id = :attr_id AND slug = 'esposito''s_sausage'
            """),
            {"attr_id": protein_attr_id}
        )

        # Rename espositos_sausage to have better display name
        conn.execute(
            text("""
                UPDATE attribute_options
                SET display_name = 'Esposito''s Sausage'
                WHERE item_type_attribute_id = :attr_id AND slug = 'espositos_sausage'
            """),
            {"attr_id": protein_attr_id}
        )

        print("Cleaned up protein duplicates")

    # =========================================================================
    # 5. Reorder attributes with egg_quantity right after egg_style
    # =========================================================================
    # Define desired order: egg_quantity should come right after egg_style
    desired_order = [
        'includes_side_choice',
        'side_options',
        'spread',
        'filling',
        'cheese',
        'egg_style',
        'egg_quantity',  # Right after egg_style
        'protein',
        'side_choice',
        'bagel_choice',
        'veggies',
        'condiments',
        'extras',
    ]

    # Get all attributes
    attrs = conn.execute(
        text("""
            SELECT id, slug FROM item_type_attributes
            WHERE item_type_id = :item_type_id
        """),
        {"item_type_id": omelette_id}
    ).fetchall()

    # Create mapping of slug to id
    slug_to_id = {attr[1]: attr[0] for attr in attrs}

    # Assign display_order based on desired order
    for order, slug in enumerate(desired_order):
        if slug in slug_to_id:
            conn.execute(
                text("""
                    UPDATE item_type_attributes
                    SET display_order = :new_order
                    WHERE id = :attr_id
                """),
                {"attr_id": slug_to_id[slug], "new_order": order}
            )

    print("Reordered attributes with egg_quantity after egg_style")


def downgrade() -> None:
    """
    This migration makes data changes that are difficult to reverse.
    A full downgrade would require re-creating deleted options and
    restoring original display names and upcharges.
    """
    print("WARNING: Downgrade not fully implemented - data changes cannot be easily reversed")
