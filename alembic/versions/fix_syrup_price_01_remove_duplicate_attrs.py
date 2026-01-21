"""Remove duplicate milk_sweetener_syrup ItemTypeAttribute entries

Revision ID: fix_syrup_price_01
Revises: c5071c50236f
Create Date: 2025-01-20

This migration fixes the vanilla syrup pricing issue.

Problem:
---------
Vanilla syrup (and other syrups) were not being priced correctly despite
having GlobalAttributeOption.price_modifier = $0.65 set properly.

Root Cause:
-----------
There were DUPLICATE 'milk_sweetener_syrup' attributes for espresso and
sized_beverage item types:

1. ItemTypeAttribute with loads_from_ingredients=True and ingredient_group='milk_sweetener_syrup'
   - This ingredient_group doesn't match any ItemTypeIngredient entries
     (actual groups are 'milk', 'sweetener', 'syrup')
   - Result: attribute has 0 options

2. ItemTypeGlobalAttribute link to GlobalAttribute 'milk_sweetener_syrup'
   - This correctly includes all 16 options (milks, sweeteners, syrups)
   - Including vanilla_syrup with price_modifier=0.65

The pricing code in lookup_modifier_price() iterates through attributes and
returns on the first match. It finds the empty ItemTypeAttribute first,
searches through 0 options, doesn't find vanilla_syrup, and returns $0.

Fix:
----
Remove the duplicate ItemTypeAttribute entries since the GlobalAttribute
properly handles this attribute with correct options and pricing.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision = 'fix_syrup_price_01'
down_revision = 'c5071c50236f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Remove duplicate ItemTypeAttribute entries for 'milk_sweetener_syrup'
    # These are redundant since GlobalAttribute handles this with proper options

    # First, log what we're about to delete
    result = conn.execute(text("""
        SELECT ita.id, it.slug as item_type, ita.ingredient_group
        FROM item_type_attributes ita
        JOIN item_types it ON it.id = ita.item_type_id
        WHERE ita.slug = 'milk_sweetener_syrup'
    """))
    rows = list(result)
    for row in rows:
        print(f"Removing ItemTypeAttribute id={row[0]} for {row[1]}.milk_sweetener_syrup (ingredient_group={row[2]!r})")

    # Delete the duplicate ItemTypeAttribute entries
    conn.execute(text("""
        DELETE FROM item_type_attributes
        WHERE slug = 'milk_sweetener_syrup'
    """))

    print(f"Deleted {len(rows)} duplicate milk_sweetener_syrup ItemTypeAttribute entries")


def downgrade() -> None:
    conn = op.get_bind()

    # Re-create the ItemTypeAttribute entries (though they were problematic)
    # Get espresso and sized_beverage item type IDs
    result = conn.execute(text("""
        SELECT id, slug FROM item_types WHERE slug IN ('espresso', 'sized_beverage')
    """))
    item_types = {row[1]: row[0] for row in result}

    for slug, type_id in item_types.items():
        conn.execute(text("""
            INSERT INTO item_type_attributes
            (item_type_id, slug, display_name, input_type, is_required, allow_none,
             ask_in_conversation, loads_from_ingredients, ingredient_group, display_order)
            VALUES (:type_id, 'milk_sweetener_syrup', 'Milk, Sweetener, or Syrup',
                    'multi_select', false, true, true, true, 'milk_sweetener_syrup', 100)
        """), {"type_id": type_id})
        print(f"Re-created milk_sweetener_syrup ItemTypeAttribute for {slug}")
