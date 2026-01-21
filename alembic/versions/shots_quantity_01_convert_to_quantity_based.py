"""Convert shots from discrete options to quantity-based system

Revision ID: shots_quantity_01
Revises: move_special_instructions_to_order
Create Date: 2025-01-21

This migration converts espresso shots from discrete options (Single/Double/Triple/Quad)
to a quantity-based system like syrups where users say "2 shots" and quantity is tracked.

Changes:
1. Create a single "Shot" ingredient (category: "shot")
2. Link to sized_beverage with ingredient_group='shots' (for adding shots to coffee)
3. Link to espresso with ingredient_group='extra_shots' (for additional shots)
4. Delete old discrete shot ingredients and options
5. Update question_text templates
6. Set max_selections=4 for shot limits

This enables natural input like "2 shots" or "three extra shots" instead of
"double" or "triple" which was causing display issues like "2 Double".
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'shots_quantity_01'
down_revision = 'move_special_instructions_to_order'
branch_labels = None
depends_on = None


# Old discrete shot ingredients to remove
OLD_SHOT_INGREDIENTS = [
    'Single Shot',
    'Double Shot Espresso',
    'Triple Shot Espresso',
    'Quad Shot',
    'Extra Shot',
    'Double Shot',
    'Triple Shot',
]

# Old discrete shot options to remove from global_attribute_options
OLD_SHOT_OPTION_SLUGS = [
    'single_shot',
    'double_shot_espresso',
    'triple_shot_espresso',
    'quad_shot',
    'single',
    'double',
    'triple',
    'quad',
]


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # Step 1: Create the "Shot" ingredient
    # =========================================================================
    print("Step 1: Creating 'Shot' ingredient...")

    # Check if it already exists
    result = conn.execute(
        text("SELECT id FROM ingredients WHERE name = 'Shot'")
    )
    shot_ingredient_id = None
    row = result.fetchone()

    if row is None:
        # Create the slug
        shot_slug = 'shot'

        # Check if slug exists and make unique if needed
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE slug = :slug"),
            {"slug": shot_slug}
        )
        if result.fetchone():
            shot_slug = 'espresso_shot'

        conn.execute(
            text("""
                INSERT INTO ingredients (name, slug, category, unit, track_inventory, is_available,
                                       is_vegan, is_vegetarian, is_gluten_free, is_dairy_free, is_kosher)
                VALUES ('Shot', :slug, 'shot', 'shot', false, true,
                        true, true, true, true, true)
            """),
            {"slug": shot_slug}
        )
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = 'Shot'")
        )
        shot_ingredient_id = result.fetchone()[0]
        print(f"  Created 'Shot' ingredient with id={shot_ingredient_id}, slug={shot_slug}")
    else:
        shot_ingredient_id = row[0]
        print(f"  'Shot' ingredient already exists with id={shot_ingredient_id}")

    # =========================================================================
    # Step 2: Get item type IDs
    # =========================================================================
    print("\nStep 2: Getting item type IDs...")

    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'sized_beverage'"))
    row = result.fetchone()
    sized_beverage_id = row[0] if row else None

    result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'espresso'"))
    row = result.fetchone()
    espresso_id = row[0] if row else None

    print(f"  sized_beverage_id={sized_beverage_id}, espresso_id={espresso_id}")

    # =========================================================================
    # Step 3: Link Shot ingredient to sized_beverage (ingredient_group='shots')
    # =========================================================================
    if sized_beverage_id:
        print("\nStep 3a: Linking Shot to sized_beverage with ingredient_group='shots'...")

        # Check if link exists
        result = conn.execute(
            text("""
                SELECT id FROM item_type_ingredients
                WHERE item_type_id = :item_type_id
                  AND ingredient_id = :ingredient_id
                  AND ingredient_group = 'shots'
            """),
            {"item_type_id": sized_beverage_id, "ingredient_id": shot_ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'shots', 1, false, true)
                """),
                {"item_type_id": sized_beverage_id, "ingredient_id": shot_ingredient_id}
            )
            print("  Created link: sized_beverage -> Shot (shots)")
        else:
            print("  Link already exists")

    # =========================================================================
    # Step 4: Link Shot ingredient to espresso (ingredient_group='extra_shots')
    # =========================================================================
    if espresso_id:
        print("\nStep 3b: Linking Shot to espresso with ingredient_group='extra_shots'...")

        # Check if link exists
        result = conn.execute(
            text("""
                SELECT id FROM item_type_ingredients
                WHERE item_type_id = :item_type_id
                  AND ingredient_id = :ingredient_id
                  AND ingredient_group = 'extra_shots'
            """),
            {"item_type_id": espresso_id, "ingredient_id": shot_ingredient_id}
        )
        if result.fetchone() is None:
            conn.execute(
                text("""
                    INSERT INTO item_type_ingredients
                    (item_type_id, ingredient_id, ingredient_group, display_order, is_default, is_available)
                    VALUES (:item_type_id, :ingredient_id, 'extra_shots', 1, false, true)
                """),
                {"item_type_id": espresso_id, "ingredient_id": shot_ingredient_id}
            )
            print("  Created link: espresso -> Shot (extra_shots)")
        else:
            print("  Link already exists")

    # =========================================================================
    # Step 5: Delete old discrete shot item_type_ingredients links
    # =========================================================================
    print("\nStep 4: Removing old discrete shot links from item_type_ingredients...")

    # Get IDs of old shot ingredients
    old_ingredient_ids = []
    for name in OLD_SHOT_INGREDIENTS:
        result = conn.execute(
            text("SELECT id FROM ingredients WHERE name = :name"),
            {"name": name}
        )
        row = result.fetchone()
        if row:
            old_ingredient_ids.append(row[0])

    if old_ingredient_ids:
        # Delete links for sized_beverage and espresso
        for item_type_id in [sized_beverage_id, espresso_id]:
            if item_type_id:
                deleted_count = 0
                for ing_id in old_ingredient_ids:
                    result = conn.execute(
                        text("""
                            DELETE FROM item_type_ingredients
                            WHERE item_type_id = :item_type_id
                              AND ingredient_id = :ingredient_id
                        """),
                        {"item_type_id": item_type_id, "ingredient_id": ing_id}
                    )
                    deleted_count += result.rowcount
                print(f"  Deleted {deleted_count} old shot links for item_type_id={item_type_id}")

    # =========================================================================
    # Step 6: Delete old discrete shot global_attribute_options
    # =========================================================================
    print("\nStep 5: Removing old discrete shot options from global_attribute_options...")

    # Get shots global attribute ID
    result = conn.execute(
        text("SELECT id FROM global_attributes WHERE slug = 'shots'")
    )
    row = result.fetchone()
    shots_attr_id = row[0] if row else None

    if shots_attr_id:
        for slug in OLD_SHOT_OPTION_SLUGS:
            result = conn.execute(
                text("""
                    DELETE FROM global_attribute_options
                    WHERE global_attribute_id = :attr_id AND slug = :slug
                """),
                {"attr_id": shots_attr_id, "slug": slug}
            )
            if result.rowcount > 0:
                print(f"  Deleted option: {slug}")

    # =========================================================================
    # Step 7: Delete old discrete shot ingredients
    # =========================================================================
    print("\nStep 6: Removing old discrete shot ingredients...")

    for name in OLD_SHOT_INGREDIENTS:
        # First check if ingredient has any remaining links
        result = conn.execute(
            text("""
                SELECT COUNT(*) FROM item_type_ingredients iti
                JOIN ingredients i ON iti.ingredient_id = i.id
                WHERE i.name = :name
            """),
            {"name": name}
        )
        link_count = result.fetchone()[0]

        if link_count == 0:
            result = conn.execute(
                text("DELETE FROM ingredients WHERE name = :name"),
                {"name": name}
            )
            if result.rowcount > 0:
                print(f"  Deleted ingredient: {name}")

    # =========================================================================
    # Step 8: Update item_type_global_attributes for shots
    # =========================================================================
    print("\nStep 7: Updating shot attributes with question_text and max_selections...")

    if shots_attr_id and sized_beverage_id:
        conn.execute(
            text("""
                UPDATE item_type_global_attributes
                SET question_text = 'How many shots?',
                    max_selections = 4,
                    ask_in_conversation = false
                WHERE item_type_id = :item_type_id
                  AND global_attribute_id = :attr_id
            """),
            {"item_type_id": sized_beverage_id, "attr_id": shots_attr_id}
        )
        print("  Updated sized_beverage shots: question='How many shots?', max=4")

    if shots_attr_id and espresso_id:
        conn.execute(
            text("""
                UPDATE item_type_global_attributes
                SET question_text = 'How many extra shots?',
                    max_selections = 4,
                    ask_in_conversation = false
                WHERE item_type_id = :item_type_id
                  AND global_attribute_id = :attr_id
            """),
            {"item_type_id": espresso_id, "attr_id": shots_attr_id}
        )
        print("  Updated espresso shots: question='How many extra shots?', max=4")

    # =========================================================================
    # Step 9: Add ingredient_category entry for 'shot' if needed
    # =========================================================================
    print("\nStep 8: Ensuring 'shot' ingredient category exists...")

    result = conn.execute(
        text("SELECT id FROM ingredient_categories WHERE slug = 'shot'")
    )
    if result.fetchone() is None:
        conn.execute(
            text("""
                INSERT INTO ingredient_categories (slug, display_name, modifier_type, display_order, is_multi_select)
                VALUES ('shot', 'Shots', 'beverage', 50, true)
            """)
        )
        print("  Created ingredient_category: shot")
    else:
        print("  ingredient_category 'shot' already exists")

    print("\nMigration complete!")


def downgrade() -> None:
    """Revert to discrete shot options."""
    conn = op.get_bind()

    # Remove the new Shot ingredient links
    result = conn.execute(
        text("SELECT id FROM ingredients WHERE name = 'Shot'")
    )
    row = result.fetchone()
    if row:
        shot_ingredient_id = row[0]
        conn.execute(
            text("DELETE FROM item_type_ingredients WHERE ingredient_id = :id"),
            {"id": shot_ingredient_id}
        )
        conn.execute(
            text("DELETE FROM ingredients WHERE id = :id"),
            {"id": shot_ingredient_id}
        )

    # Remove shot ingredient category
    conn.execute(
        text("DELETE FROM ingredient_categories WHERE slug = 'shot'")
    )

    # Note: Re-creating the old discrete options would require full data
    # This is a partial downgrade - the old options are not restored
    print("Downgrade complete. Note: Old discrete shot options not restored.")
