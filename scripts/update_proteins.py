"""
Consolidate and update protein attributes based on Zucker's Extra Protein menu.

This script:
1. Renames protein/extra_proteins to extra_protein with display "Extra Protein"
2. Creates extra_protein for fish_sandwich (missing)
3. Updates protein prices to match image
4. Adds missing proteins (Egg Salad, Bacon)
5. Updates ingredients table
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
import os
from sqlalchemy import create_engine, text

# Proteins from the image with their prices
PROTEINS = {
    'Bacon': 2.50,
    'Turkey Bacon': 2.95,
    'Smoked Turkey': 3.45,
    'Black Forest Ham': 3.45,
    'Corned Beef': 3.45,
    'Pastrami': 3.45,
    'Egg Salad': 2.55,
}

# Additional proteins to keep (not in image but should exist)
ADDITIONAL_PROTEINS = {
    'Applewood Smoked Bacon': 2.50,
    'Sausage': 2.75,
    'Sausage Patty': 2.75,
    'Chicken Sausage': 2.95,
    'Ham': 3.45,  # Same as Black Forest Ham
    'Nova Scotia Salmon': 6.00,
    'Roast Beef': 3.45,
    "Esposito's Sausage": 2.75,
}

engine = create_engine(os.environ['DATABASE_URL'])

with engine.connect() as conn:
    print("=" * 60)
    print("STEP 1: Rename protein attributes to extra_protein")
    print("=" * 60)

    # Rename existing protein/extra_proteins attributes
    result = conn.execute(text('''
        UPDATE item_type_attributes
        SET slug = 'extra_protein', display_name = 'Extra Protein'
        WHERE slug IN ('protein', 'extra_proteins')
        RETURNING id, slug, display_name
    '''))
    for r in result:
        print(f"  Renamed attr {r.id} to '{r.slug}' / '{r.display_name}'")

    print()
    print("=" * 60)
    print("STEP 2: Create extra_protein for fish_sandwich")
    print("=" * 60)

    # Check if fish_sandwich has extra_protein
    result = conn.execute(text('''
        SELECT ita.id FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE it.slug = 'fish_sandwich' AND ita.slug = 'extra_protein'
    '''))
    fish_protein_attr = result.fetchone()

    if fish_protein_attr:
        print(f"  fish_sandwich already has extra_protein (attr {fish_protein_attr.id})")
        fish_attr_id = fish_protein_attr.id
    else:
        # Get fish_sandwich item type ID
        result = conn.execute(text("SELECT id FROM item_types WHERE slug = 'fish_sandwich'"))
        fish_type_id = result.fetchone().id

        # Get max display_order for fish_sandwich attributes
        result = conn.execute(text('''
            SELECT COALESCE(MAX(display_order), 0) as max_order
            FROM item_type_attributes WHERE item_type_id = :type_id
        '''), {'type_id': fish_type_id})
        max_order = result.fetchone().max_order

        # Create extra_protein attribute for fish_sandwich
        result = conn.execute(text('''
            INSERT INTO item_type_attributes
            (item_type_id, slug, display_name, input_type, is_required, display_order)
            VALUES (:type_id, 'extra_protein', 'Extra Protein', 'multi_select', false, :order)
            RETURNING id
        '''), {'type_id': fish_type_id, 'order': max_order + 1})
        fish_attr_id = result.fetchone().id
        print(f"  Created extra_protein for fish_sandwich (attr {fish_attr_id})")

    print()
    print("=" * 60)
    print("STEP 3: Update protein prices")
    print("=" * 60)

    # Combine all proteins
    all_proteins = {**PROTEINS, **ADDITIONAL_PROTEINS}

    # Update prices for existing options
    for name, price in all_proteins.items():
        result = conn.execute(text('''
            UPDATE attribute_options ao
            SET price_modifier = :price
            FROM item_type_attributes ita
            WHERE ao.item_type_attribute_id = ita.id
            AND ita.slug = 'extra_protein'
            AND ao.display_name = :name
        '''), {'name': name, 'price': price})
        if result.rowcount > 0:
            print(f"  Updated {result.rowcount} option(s): {name} -> ${price:.2f}")

    # Also update "Ham" to match "Black Forest Ham" price
    conn.execute(text('''
        UPDATE attribute_options ao
        SET price_modifier = 3.45
        FROM item_type_attributes ita
        WHERE ao.item_type_attribute_id = ita.id
        AND ita.slug = 'extra_protein'
        AND ao.display_name = 'Ham'
    '''))

    print()
    print("=" * 60)
    print("STEP 4: Add missing proteins to all item types")
    print("=" * 60)

    # Get extra_protein attribute IDs for each item type
    result = conn.execute(text('''
        SELECT it.slug as item_type, ita.id as attr_id
        FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE ita.slug = 'extra_protein'
    '''))
    attr_ids = {r.item_type: r.attr_id for r in result}

    for item_type, attr_id in attr_ids.items():
        print(f"\n  {item_type} (attr {attr_id}):")

        # Get existing options
        result = conn.execute(text('''
            SELECT LOWER(display_name) as name FROM attribute_options
            WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        existing = {r.name for r in result}

        # Get max display_order
        result = conn.execute(text('''
            SELECT COALESCE(MAX(display_order), 0) as max_order
            FROM attribute_options WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        max_order = result.fetchone().max_order

        # Add missing proteins from image
        for name, price in all_proteins.items():
            if name.lower() not in existing:
                max_order += 1
                slug = name.lower().replace(' ', '_').replace("'", '')
                conn.execute(text('''
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier, display_order, is_default, is_available)
                    VALUES (:attr_id, :slug, :name, :price, :order, false, true)
                '''), {
                    'attr_id': attr_id,
                    'slug': f"{item_type}_{slug}",
                    'name': name,
                    'price': price,
                    'order': max_order,
                })
                print(f"    Added: {name} (${price:.2f})")

    print()
    print("=" * 60)
    print("STEP 5: Update ingredients table")
    print("=" * 60)

    # Check which ingredients exist
    result = conn.execute(text("SELECT name FROM ingredients"))
    existing_ingredients = {r.name.lower() for r in result}

    # Add/update ingredients
    for name, price in all_proteins.items():
        if name.lower() in existing_ingredients:
            # Update price
            result = conn.execute(text('''
                UPDATE ingredients SET base_price = :price WHERE LOWER(name) = LOWER(:name)
            '''), {'name': name, 'price': price})
            if result.rowcount > 0:
                print(f"  Updated: {name} -> ${price:.2f}")
        else:
            # Add new ingredient
            conn.execute(text('''
                INSERT INTO ingredients (name, category, base_price, is_available, track_inventory, unit)
                VALUES (:name, 'protein', :price, true, false, 'each')
            '''), {'name': name, 'price': price})
            print(f"  Added: {name} (${price:.2f})")

    conn.commit()

    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Verify
    for item_type in ['egg_sandwich', 'deli_sandwich', 'fish_sandwich', 'omelette']:
        result = conn.execute(text('''
            SELECT COUNT(*) as count
            FROM attribute_options ao
            JOIN item_type_attributes ita ON ao.item_type_attribute_id = ita.id
            JOIN item_types it ON ita.item_type_id = it.id
            WHERE it.slug = :item_type AND ita.slug = 'extra_protein'
        '''), {'item_type': item_type})
        count = result.fetchone().count
        print(f"  {item_type}: {count} protein options")

    print()
    print("DONE!")
