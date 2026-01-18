"""Split milk_sweetener_syrup into separate ingredient groups

Revision ID: split_mss_001
Revises: 61205c36fc16
Create Date: 2026-01-18

This migration makes get_modifier_fields_for_item_type() fully data-driven by:

1. Splitting the combined 'milk_sweetener_syrup' ingredient_group back into
   separate groups ('milk', 'sweetener', 'syrup') based on each ingredient's
   actual category.

2. Ensuring IngredientCategory table has correct field configuration:
   - milk: code_field_name='milk', is_multi_select=True
   - sweetener: code_field_name='sweetener', is_multi_select=True
   - syrup: code_field_name='syrup', is_multi_select=True
   - spread: code_field_name='spread', is_multi_select=True

This eliminates the hardcoded special-case in the code that checked for
'milk_sweetener_syrup' and split by ingredient.category.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'split_mss_001'
down_revision = '61205c36fc16'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Split milk_sweetener_syrup into separate groups based on ingredient category
    # For each item_type_ingredients record with ingredient_group='milk_sweetener_syrup',
    # update to use the actual ingredient category (milk, sweetener, or syrup)
    conn.execute(text("""
        UPDATE item_type_ingredients iti
        SET ingredient_group = i.category
        FROM ingredients i
        WHERE iti.ingredient_id = i.id
        AND iti.ingredient_group = 'milk_sweetener_syrup'
        AND i.category IN ('milk', 'sweetener', 'syrup')
    """))

    # Count how many were updated
    result = conn.execute(text("""
        SELECT COUNT(*) FROM item_type_ingredients
        WHERE ingredient_group IN ('milk', 'sweetener', 'syrup')
    """))
    count = result.scalar()
    print(f"Split milk_sweetener_syrup: {count} records now use individual category groups")

    # Step 2: Update IngredientCategory to ensure correct field configuration
    # All these categories should support multiple selections (e.g., "extra milk", "2 sugars")
    categories_to_update = [
        ('milk', 'milk', True),
        ('sweetener', 'sweetener', True),
        ('syrup', 'syrup', True),
        ('spread', 'spread', True),
    ]

    for slug, code_field_name, is_multi_select in categories_to_update:
        # Check if category exists
        result = conn.execute(text("""
            SELECT id, code_field_name, is_multi_select
            FROM ingredient_categories
            WHERE slug = :slug
        """), {"slug": slug})
        row = result.fetchone()

        if row:
            # Update existing category
            conn.execute(text("""
                UPDATE ingredient_categories
                SET code_field_name = :code_field_name,
                    is_multi_select = :is_multi_select
                WHERE slug = :slug
            """), {
                "slug": slug,
                "code_field_name": code_field_name,
                "is_multi_select": is_multi_select,
            })
            print(f"Updated ingredient_category '{slug}': code_field_name={code_field_name}, is_multi_select={is_multi_select}")
        else:
            # Insert new category if it doesn't exist
            conn.execute(text("""
                INSERT INTO ingredient_categories (slug, display_name, code_field_name, is_multi_select, display_order)
                VALUES (:slug, :display_name, :code_field_name, :is_multi_select, :display_order)
            """), {
                "slug": slug,
                "display_name": slug.replace("_", " ").title(),
                "code_field_name": code_field_name,
                "is_multi_select": is_multi_select,
                "display_order": 99,  # Will be at end, can be reordered later
            })
            print(f"Created ingredient_category '{slug}': code_field_name={code_field_name}, is_multi_select={is_multi_select}")


def downgrade() -> None:
    conn = op.get_bind()

    # Step 1: Consolidate milk, sweetener, syrup back into milk_sweetener_syrup
    # Only for beverage item types (espresso, sized_beverage)
    result = conn.execute(text("""
        SELECT id FROM item_types WHERE slug IN ('espresso', 'sized_beverage')
    """))
    beverage_type_ids = [row[0] for row in result]

    if beverage_type_ids:
        conn.execute(text("""
            UPDATE item_type_ingredients
            SET ingredient_group = 'milk_sweetener_syrup'
            WHERE item_type_id = ANY(:type_ids)
            AND ingredient_group IN ('milk', 'sweetener', 'syrup')
        """), {"type_ids": beverage_type_ids})

    # Step 2: Revert is_multi_select for spread (was likely False before)
    # Note: We don't revert milk/sweetener/syrup since they may have been
    # multi-select before, and we're just being safe with the spread change
    conn.execute(text("""
        UPDATE ingredient_categories
        SET is_multi_select = FALSE
        WHERE slug = 'spread'
    """))
