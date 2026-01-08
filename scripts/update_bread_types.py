"""
Update bread/bagel types based on Zucker's menu image.

This script:
1. Adds missing bread/bagel ingredients to ingredients table
2. Updates bread attribute options for all sandwich types
3. Updates bagel_choice options for omelettes
4. Updates bagel_type options for bagel item type
5. Fixes upcharges (GF +$1.85, Croissant +$1.80, GF Wrap +$1.00)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()
import os
from sqlalchemy import create_engine, text

# All bread types from the image with their upcharges
# Most are FREE ($0.00), only GF and Croissant have upcharges
BREAD_TYPES = {
    # Standard bagels - FREE
    'Plain Bagel': 0.00,
    'Everything Bagel': 0.00,
    'Sesame Bagel': 0.00,
    'Poppy Bagel': 0.00,
    'Onion Bagel': 0.00,
    'Cinnamon Raisin Bagel': 0.00,
    'Garlic Bagel': 0.00,
    'Salt Bagel': 0.00,
    'Whole Wheat Bagel': 0.00,
    'Whole Wheat Everything Bagel': 0.00,
    'Pumpernickel Bagel': 0.00,

    # Flatz - FREE
    'Whole Wheat Flatz': 0.00,
    'Whole Wheat Everything Flatz': 0.00,

    # Sourdough bagels - FREE
    'Plain Sourdough Bagel': 0.00,
    'Sesame Sourdough Bagel': 0.00,
    'Everything Sourdough Bagel': 0.00,

    # Sourdough Flatz - FREE
    'Plain Sourdough Bagel Flatz': 0.00,
    'Everything Sourdough Bagel Flatz': 0.00,

    # Other bagel-like - FREE
    'Bialy': 0.00,

    # Gluten Free - UPCHARGE
    'GF Plain Bagel': 1.85,
    'GF Everything Bagel': 1.85,

    # Croissant - UPCHARGE
    'Croissant': 1.80,

    # Breads - FREE
    'White Bread': 0.00,
    'Rye': 0.00,
    'Whole Wheat Bread': 0.00,

    # Wraps - FREE (except GF)
    'Whole Wheat Wrap': 0.00,
    'GF Wrap': 1.00,

    # Roll - FREE
    'Challah Roll': 0.00,
}

# Mapping of display names that may already exist with different names
NAME_VARIATIONS = {
    'gluten free plain bagel': 'GF Plain Bagel',
    'gluten free everything bagel': 'GF Everything Bagel',
    'gluten free wrap': 'GF Wrap',
    'wheat flatz': 'Whole Wheat Flatz',
    'wheat everything flatz': 'Whole Wheat Everything Flatz',
    'everything wheat bagel': 'Whole Wheat Everything Bagel',
}

# Base prices for ingredients (standalone bagel prices)
INGREDIENT_BASE_PRICES = {
    'Plain Bagel': 2.20,
    'Everything Bagel': 2.20,
    'Sesame Bagel': 2.20,
    'Poppy Bagel': 2.20,
    'Onion Bagel': 2.20,
    'Cinnamon Raisin Bagel': 2.20,
    'Garlic Bagel': 2.20,
    'Salt Bagel': 2.20,
    'Whole Wheat Bagel': 2.20,
    'Whole Wheat Everything Bagel': 2.20,
    'Pumpernickel Bagel': 2.20,
    'Whole Wheat Flatz': 2.50,
    'Whole Wheat Everything Flatz': 2.50,
    'Plain Sourdough Bagel': 2.50,
    'Sesame Sourdough Bagel': 2.50,
    'Everything Sourdough Bagel': 2.50,
    'Plain Sourdough Bagel Flatz': 2.50,
    'Everything Sourdough Bagel Flatz': 2.50,
    'Bialy': 2.20,
    'GF Plain Bagel': 4.05,  # 2.20 + 1.85
    'GF Everything Bagel': 4.05,
    'Croissant': 4.00,  # 2.20 + 1.80
    'White Bread': 0.00,
    'Rye': 0.00,
    'Whole Wheat Bread': 0.00,
    'Whole Wheat Wrap': 0.00,
    'GF Wrap': 1.00,
    'Challah Roll': 2.50,
}

engine = create_engine(os.environ['DATABASE_URL'])

with engine.connect() as conn:
    print("=" * 60)
    print("STEP 1: Add missing ingredients")
    print("=" * 60)

    # Get existing ingredients
    result = conn.execute(text("SELECT LOWER(name) as name FROM ingredients"))
    existing_ingredients = {r.name for r in result}

    added_count = 0
    for name, upcharge in BREAD_TYPES.items():
        if name.lower() not in existing_ingredients:
            base_price = INGREDIENT_BASE_PRICES.get(name, 2.20)
            conn.execute(text('''
                INSERT INTO ingredients (name, category, base_price, is_available, track_inventory, unit)
                VALUES (:name, 'bread', :price, true, false, 'each')
            '''), {'name': name, 'price': base_price})
            print(f"  Added: {name} (${base_price:.2f})")
            added_count += 1

    if added_count == 0:
        print("  No missing ingredients to add")

    print()
    print("=" * 60)
    print("STEP 2: Update sandwich bread attribute options")
    print("=" * 60)

    # Get bread attribute IDs for sandwiches
    result = conn.execute(text('''
        SELECT it.slug as item_type, ita.id as attr_id
        FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE it.slug IN ('egg_sandwich', 'deli_sandwich', 'fish_sandwich')
        AND ita.slug = 'bread'
    '''))
    sandwich_bread_attrs = {r.item_type: r.attr_id for r in result}

    for item_type, attr_id in sandwich_bread_attrs.items():
        print(f"\n  {item_type} (attr {attr_id}):")

        # Get existing options (lowercase for comparison)
        result = conn.execute(text('''
            SELECT LOWER(display_name) as name FROM attribute_options
            WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        existing_options = {r.name for r in result}

        # Get max display_order
        result = conn.execute(text('''
            SELECT COALESCE(MAX(display_order), 0) as max_order
            FROM attribute_options WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        max_order = result.fetchone().max_order

        # Update existing options with correct prices
        for name, upcharge in BREAD_TYPES.items():
            # Check if exists (with variations)
            name_lower = name.lower()
            exists = name_lower in existing_options

            # Check for name variations
            for variation, canonical in NAME_VARIATIONS.items():
                if canonical == name and variation in existing_options:
                    exists = True
                    # Update the variation to correct price
                    conn.execute(text('''
                        UPDATE attribute_options
                        SET price_modifier = :price
                        WHERE item_type_attribute_id = :attr_id
                        AND LOWER(display_name) = :name
                    '''), {'attr_id': attr_id, 'name': variation, 'price': upcharge})
                    break

            if exists:
                # Update price
                result = conn.execute(text('''
                    UPDATE attribute_options
                    SET price_modifier = :price
                    WHERE item_type_attribute_id = :attr_id
                    AND LOWER(display_name) = :name
                '''), {'attr_id': attr_id, 'name': name_lower, 'price': upcharge})
                if result.rowcount > 0:
                    print(f"    Updated price: {name} -> ${upcharge:.2f}")
            else:
                # Add new option
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
                    'price': upcharge,
                    'order': max_order,
                })
                price_str = f"+${upcharge:.2f}" if upcharge > 0 else "FREE"
                print(f"    Added: {name} ({price_str})")

    print()
    print("=" * 60)
    print("STEP 3: Update omelette bagel_choice options")
    print("=" * 60)

    # Get bagel_choice attribute ID for omelette
    result = conn.execute(text('''
        SELECT ita.id as attr_id
        FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE it.slug = 'omelette' AND ita.slug = 'bagel_choice'
    '''))
    row = result.fetchone()

    if row:
        attr_id = row.attr_id
        print(f"\n  omelette bagel_choice (attr {attr_id}):")

        # Get existing options
        result = conn.execute(text('''
            SELECT LOWER(display_name) as name FROM attribute_options
            WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        existing_options = {r.name for r in result}

        # Get max display_order
        result = conn.execute(text('''
            SELECT COALESCE(MAX(display_order), 0) as max_order
            FROM attribute_options WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        max_order = result.fetchone().max_order

        # Omelette bagel options - exclude non-bagel breads like White Bread, Rye, etc.
        bagel_only_types = {k: v for k, v in BREAD_TYPES.items()
                          if 'bagel' in k.lower() or 'bialy' in k.lower() or 'flatz' in k.lower()}

        for name, upcharge in bagel_only_types.items():
            name_lower = name.lower()
            if name_lower not in existing_options:
                max_order += 1
                slug = name.lower().replace(' ', '_').replace("'", '')
                conn.execute(text('''
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier, display_order, is_default, is_available)
                    VALUES (:attr_id, :slug, :name, :price, :order, false, true)
                '''), {
                    'attr_id': attr_id,
                    'slug': f"omelette_{slug}",
                    'name': name,
                    'price': upcharge,
                    'order': max_order,
                })
                price_str = f"+${upcharge:.2f}" if upcharge > 0 else "FREE"
                print(f"    Added: {name} ({price_str})")
            else:
                # Update price
                conn.execute(text('''
                    UPDATE attribute_options
                    SET price_modifier = :price
                    WHERE item_type_attribute_id = :attr_id
                    AND LOWER(display_name) = :name
                '''), {'attr_id': attr_id, 'name': name_lower, 'price': upcharge})

        # Set Plain Bagel as default
        conn.execute(text('''
            UPDATE attribute_options SET is_default = false
            WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        conn.execute(text('''
            UPDATE attribute_options SET is_default = true
            WHERE item_type_attribute_id = :attr_id
            AND LOWER(display_name) = 'plain bagel'
        '''), {'attr_id': attr_id})
        print("    Set 'Plain Bagel' as default")
    else:
        print("  No bagel_choice attribute found for omelette")

    print()
    print("=" * 60)
    print("STEP 4: Update bagel item bagel_type options")
    print("=" * 60)

    # Get bagel_type attribute ID for bagel item type
    result = conn.execute(text('''
        SELECT ita.id as attr_id
        FROM item_type_attributes ita
        JOIN item_types it ON ita.item_type_id = it.id
        WHERE it.slug = 'bagel' AND ita.slug = 'bagel_type'
    '''))
    row = result.fetchone()

    if row:
        attr_id = row.attr_id
        print(f"\n  bagel bagel_type (attr {attr_id}):")

        # Get existing options
        result = conn.execute(text('''
            SELECT display_name, LOWER(display_name) as name_lower FROM attribute_options
            WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        existing_options = {}
        for r in result:
            existing_options[r.name_lower] = r.display_name

        # Get max display_order
        result = conn.execute(text('''
            SELECT COALESCE(MAX(display_order), 0) as max_order
            FROM attribute_options WHERE item_type_attribute_id = :attr_id
        '''), {'attr_id': attr_id})
        max_order = result.fetchone().max_order

        # For bagel item type, only include bagel options (no bread/wraps)
        bagel_only_types = {k: v for k, v in BREAD_TYPES.items()
                          if 'bagel' in k.lower() or 'bialy' in k.lower() or 'flatz' in k.lower()}

        for name, upcharge in bagel_only_types.items():
            name_lower = name.lower()
            # Handle short names like "Plain" -> "Plain Bagel"
            short_name = name.replace(' Bagel', '').lower()

            if name_lower in existing_options or short_name in existing_options:
                # Update existing option - may need to rename from "Plain" to "Plain Bagel"
                existing_name = existing_options.get(name_lower) or existing_options.get(short_name)
                if existing_name and existing_name != name:
                    # Rename to full name
                    conn.execute(text('''
                        UPDATE attribute_options
                        SET display_name = :new_name, price_modifier = :price
                        WHERE item_type_attribute_id = :attr_id
                        AND LOWER(display_name) = :old_name
                    '''), {'attr_id': attr_id, 'old_name': short_name, 'new_name': name, 'price': upcharge})
                    print(f"    Renamed: {existing_name} -> {name}")
                else:
                    conn.execute(text('''
                        UPDATE attribute_options
                        SET price_modifier = :price
                        WHERE item_type_attribute_id = :attr_id
                        AND LOWER(display_name) = :name
                    '''), {'attr_id': attr_id, 'name': name_lower, 'price': upcharge})
            else:
                # Add new option
                max_order += 1
                slug = name.lower().replace(' ', '_').replace("'", '')
                conn.execute(text('''
                    INSERT INTO attribute_options
                    (item_type_attribute_id, slug, display_name, price_modifier, display_order, is_default, is_available)
                    VALUES (:attr_id, :slug, :name, :price, :order, false, true)
                '''), {
                    'attr_id': attr_id,
                    'slug': f"bagel_{slug}",
                    'name': name,
                    'price': upcharge,
                    'order': max_order,
                })
                price_str = f"+${upcharge:.2f}" if upcharge > 0 else "FREE"
                print(f"    Added: {name} ({price_str})")
    else:
        print("  No bagel_type attribute found for bagel item type")

    conn.commit()

    print()
    print("=" * 60)
    print("VERIFICATION")
    print("=" * 60)

    # Count options per item type
    for item_type, attr_slug in [
        ('egg_sandwich', 'bread'),
        ('deli_sandwich', 'bread'),
        ('fish_sandwich', 'bread'),
        ('omelette', 'bagel_choice'),
        ('bagel', 'bagel_type'),
    ]:
        result = conn.execute(text('''
            SELECT COUNT(*) as count
            FROM attribute_options ao
            JOIN item_type_attributes ita ON ao.item_type_attribute_id = ita.id
            JOIN item_types it ON ita.item_type_id = it.id
            WHERE it.slug = :item_type AND ita.slug = :attr_slug
        '''), {'item_type': item_type, 'attr_slug': attr_slug})
        count = result.fetchone().count
        print(f"  {item_type} ({attr_slug}): {count} options")

    print()
    print("DONE!")
